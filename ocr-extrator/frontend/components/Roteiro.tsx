"use client";

import {
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ReactNode, Ref } from "react";

import { entrevistaDeTeste } from "@/lib/amostraEntrevista";
import { analisarResposta, consultarCep, escutarTrecho, obterRoteiro, recomendarEntrevista } from "@/lib/api";
import { conferirCpf, formatarCep, formatarCpf } from "@/lib/documentos";
import type {
  AnaliseResposta,
  Bloco,
  CampoOuvido,
  EnderecoCep,
  Lembrete,
  Pergunta,
  PerguntaPendente,
  RecomendacaoEntrevista,
  RoteiroCompleto,
} from "@/lib/types";
import { CapturaEntrevista } from "@/lib/transcricao";
import type { EstadoCaptura } from "@/lib/transcricao";
import AudioDaEntrevista from "./AudioDaEntrevista";
import Conducao from "./Conducao";
import ConferenciaResposta from "./ConferenciaResposta";
import VideoDaEntrevista from "./VideoDaEntrevista";
import PainelEscuta from "./PainelEscuta";
import estilos from "./Roteiro.module.css";
import transcricaoEstilos from "./EntrevistaAoVivo.module.css";

/* Conduz a entrevista pergunta a pergunta.
 *
 * O microfone é UM só para a entrevista inteira, vivendo aqui no topo. Cada
 * pergunta gravável apenas liga e desliga o envio — se cada uma tivesse sua
 * própria captura, o navegador pediria permissão e piscaria o indicador a cada
 * pergunta, e o entrevistador perderia o fio da conversa.
 *
 * Só as perguntas narrativas trazem gravador. Nome, CPF e RG são digitados:
 * número ditado o Whisper erra, e ninguém confere dígito lido de ouvido. */

type Respostas = Record<string, string | string[]>;

/** O que a chamada, na coluna ao lado, precisa poder fazer com o roteiro. */
export interface ManipuladorRoteiro {
  /** Passa a transcrever a voz que chega pela chamada, no lugar do microfone. */
  usarFaixaDaChamada: (trilha: MediaStreamTrack) => Promise<void>;
  /** A chamada caiu: solta a fonte, para o gravador não prometer o que não tem. */
  aoPerderChamada: () => void;
  /** Há vídeo gravado e não baixado — fechar a tela agora o destrói. */
  temVideoPendente: () => boolean;
  /** Quantas respostas ouvidas ainda esperam confirmação (nome e CPF).
   *
   * Quem encerra o atendimento é a tela de fora, mas o dado é daqui — e sair
   * sem confirmar descarta em silêncio justamente os dois campos que
   * identificam o cliente no contrato e na procuração. */
  sugestoesPendentes: () => number;
  /** Fecha a gravação e espera o áudio inteiro chegar ao disco.
   *
   * Só no FIM do atendimento: a gravação corre durante a avaliação, os
   * documentos e o envio dos primeiros arquivos, que é justamente quando o
   * cliente diz coisas que valem estar no áudio. Devolve o `entrevistaId`, que
   * é por onde o arquivo é baixado depois. */
  encerrarGravacao: () => Promise<string>;
  /** Tudo que foi transcrito, na ordem, com o instante de cada trecho.
   *
   * É a transcrição BRUTA: a conversa como ela saiu do Whisper, sem passar
   * pelo roteiro. O que está nos campos é o que a escuta interpretou; isto é o
   * que foi dito — e é o que sobra para conferir uma interpretação duvidosa
   * seis meses depois. */
  transcricaoBruta: () => { quando: number; texto: string }[];
}

/** De onde vem o áudio que está sendo transcrito. */
type Fonte = "nenhuma" | "microfone" | "chamada";

/** A conferência de UMA resposta narrativa. */
interface EstadoConferencia {
  carregando: boolean;
  analise: AnaliseResposta | null;
  erro: string | null;
}

/* Abaixo disto a resposta ainda está sendo dada e não há o que conferir. É o
 * mesmo piso do backend (`analise_resposta.MINIMO_CARACTERES`); repetido aqui
 * para não gastar uma ida à API só para ouvir "curta demais". */
const MINIMO_PARA_CONFERIR = 40;

/* Por quanto tempo, depois do último campo preenchido, a entrevista conta como
 * FLUINDO.
 *
 * Enquanto ela flui, a cobrança dos 10s recolhe: o relógio continua correndo e
 * a linha continua na tela, mas a placa vermelha some. O cliente está
 * respondendo o roteiro — fora de ordem, mas respondendo — e gritar PARE por
 * cima disso é o alarme virar paisagem. Um alarme que fica no ar por minutos
 * deixa de ser lido, e aí ele não serve para o caso em que importa: o cliente
 * falando do filho, da vizinha, sem nada entrando em campo nenhum.
 *
 * 20s porque é o intervalo típico entre dois preenchimentos numa conversa
 * corrida — abaixo disso a placa piscaria a cada pausa para respirar. */
const SEGUNDOS_FLUINDO = 20;

/** Tem valor? Mesmo critério de `escuta._respondida`, no backend. */
function respondida(valor: string | string[] | undefined): boolean {
  return Array.isArray(valor) ? valor.length > 0 : Boolean(String(valor ?? "").trim());
}

interface Props {
  codigo?: string;
  /** As respostas conforme mudam, sem esperar o fim.
   *
   * O `entrevistaId` sobe junto porque o áudio sobrevive a esta tela: quem
   * encerra o atendimento precisa continuar podendo baixar o arquivo.
   *
   * As etapas seguintes do atendimento (avaliação, documentos, assinatura) ficam
   * na mesma rolagem, logo abaixo do roteiro, e precisam do que já foi
   * respondido enquanto a entrevista ainda corre — o contrato pede nome e CPF,
   * e eles chegam nas duas primeiras perguntas. */
  onRespostas?: (
    respostas: Respostas,
    relatoUnificado: string,
    entrevistaId: string,
  ) => void;
  ref?: Ref<ManipuladorRoteiro>;
}

export default function Roteiro({
  codigo = "empregado_publico",
  onRespostas,
  ref,
}: Props) {
  const [roteiro, setRoteiro] = useState<RoteiroCompleto | null>(null);
  const [respostas, setRespostas] = useState<Respostas>({});
  const [erro, setErro] = useState<string | null>(null);
  /* Perguntas que saíram da vez sem resposta — o cliente não sabia, não quis,
   * ou o assunto não estava maduro. Não somem do roteiro: continuam pendentes
   * na lista e voltam à condução com um clique. É o que impede a sequência de
   * travar numa pergunta impossível com a cobrança tocando sem saída. */
  const [puladas, setPuladas] = useState<string[]>([]);
  /* Quando um campo QUALQUER foi preenchido pela última vez. É o sinal de que a
   * entrevista está andando, mesmo que fora da ordem do roteiro. */
  const [ultimoPreenchimento, setUltimoPreenchimento] = useState<number | null>(null);
  // A pergunta da vez, lida dentro da fila da escuta — que é fixada na
  // construção e não enxergaria o estado do React.
  const atualRef = useRef<string>("");

  const [estadoMic, setEstadoMic] = useState<EstadoCaptura>("sem-audio");
  const [gravandoId, setGravandoId] = useState<string | null>(null);
  /* Entre clicar em "Finalizar" e o texto voltar do servidor.
   *
   * A captura para no clique, mas o texto final é transcrito do áudio INTEIRO —
   * numa resposta de três minutos são vários segundos. Nesse intervalo a
   * pergunta continuava mostrando "Pausar" e "Finalizar", e os dois não faziam
   * nada: a captura já tinha parado, e os métodos saem calados quando não há
   * gravação. Era o "clico e não acontece nada". */
  const [finalizando, setFinalizando] = useState(false);
  const [parcial, setParcial] = useState("");
  const [aviso, setAviso] = useState<string | null>(null);
  const [fonte, setFonte] = useState<Fonte>("nenhuma");
  // Lido dentro de callbacks fixados na construção, que não enxergam o estado.
  const fonteAtual = useRef<Fonte>("nenhuma");
  fonteAtual.current = fonte;

  const [conferencias, setConferencias] = useState<Record<string, EstadoConferencia>>({});
  const [recomendacaoCaso, setRecomendacaoCaso] = useState<RecomendacaoEntrevista | null>(null);
  const [erroRecomendacao, setErroRecomendacao] = useState<string | null>(null);
  /* Sessão vencida no meio da entrevista.
   *
   * Aconteceu de verdade: o token dura 30 minutos, a entrevista de 42 perguntas
   * dura mais, e a partir dali cada trecho transcrito ia para a escuta e voltava
   * 401. A transcrição seguia funcionando, o painel seguia dizendo "ouvindo", e
   * NADA era preenchido — o entrevistador falou vários minutos sem saber que
   * estava sendo descartado. Falhar calado aqui custa a entrevista inteira. */
  const [sessaoCaiu, setSessaoCaiu] = useState(false);
  useEffect(() => {
    const caiu = () => setSessaoCaiu(true);
    window.addEventListener("acervo:sessao-expirada", caiu);
    return () => window.removeEventListener("acervo:sessao-expirada", caiu);
  }, []);
  const [atualizandoRecomendacao, setAtualizandoRecomendacao] = useState(false);
  const ultimoRelatoRecomendado = useRef("");

  /* A escuta chegou ao fim e o áudio pode ser oferecido. Quem grava é o
   * servidor, do mesmo PCM que alimenta a transcrição — ver `app/gravacao.py` e
   * `AudioDaEntrevista`, que cuida da conversão e do download. */
  const [escutaEncerrada, setEscutaEncerrada] = useState(false);
  /* Vídeo gravado e ainda não baixado. Ao contrário do áudio, ele não está em
   * lugar nenhum além desta aba — concluir a entrevista o destrói. */
  const videoPendente = useRef(false);

  /* ---------------------------------------------------- escuta contínua
   *
   * O microfone abre uma vez, no "podemos começar?", e não fecha mais. Cada
   * trecho que o servidor CONFIRMA (não o parcial, que ainda se reescreve) vai
   * para a escuta, que decide a que perguntas ele responde.
   *
   * `escutando` é o estado que substitui os 86 ciclos de gravar/finalizar. */
  const [escutando, setEscutando] = useState(false);
  const [ouvindo, setOuvindo] = useState(false);
  const [sugestoes, setSugestoes] = useState<CampoOuvido[]>([]);
  // Lido pelo `useImperativeHandle`, que é fixado na montagem e não enxergaria
  // o estado — é por ele que a tela de fora sabe o que falta conferir.
  const sugestoesRef = useRef<CampoOuvido[]>([]);
  sugestoesRef.current = sugestoes;
  const [lembretes, setLembretes] = useState<Lembrete[]>([]);
  const [faltando, setFaltando] = useState<PerguntaPendente[]>([]);
  const [ouvidas, setOuvidas] = useState<CampoOuvido[]>([]);
  const [erroEscuta, setErroEscuta] = useState<string | null>(null);
  const [saudacaoLida, setSaudacaoLida] = useState(false);
  /* Quando um trecho de fala foi reconhecido pela última vez.
   *
   * É o único sinal que distingue "conversa em silêncio" de "microfone mudo" —
   * e o segundo é o que já custou uma entrevista inteira transcrita como nada. */
  const [ultimaFala, setUltimaFala] = useState<number | null>(null);
  /* Quando o microfone captou som pela última vez — som QUALQUER, não fala
   * reconhecida. É o que separa "ninguém está falando" de "o microfone está
   * mudo", e sem essa distinção a tela não tem como avisar do segundo. */
  const [ultimoSom, setUltimoSom] = useState<number | null>(null);
  /* Nível TÍPICO da fala e velocidade com que o áudio chega. Existem para a
   * tela poder dizer POR QUE o texto não aparece, em vez de só mostrar que não
   * apareceu — que é indistinguível de "ninguém falou". */
  const [nivelTipico, setNivelTipico] = useState<number | null>(null);
  const [chegada, setChegada] = useState<number | null>(null);
  /* Em ref, e não em estado: chega ~2x por segundo e re-renderizar a cada
   * amostra redesenharia o roteiro inteiro sem nada mudar na tela. */
  const niveisComSom = useRef<number[]>([]);

  /* A conversa não espera a resposta da escuta anterior.
   *
   * Trechos chegam a cada poucos segundos e cada chamada leva alguns; sem fila,
   * duas rodadas simultâneas mandariam o mesmo `respostas` desatualizado e a
   * segunda desfaria o preenchimento da primeira. A fila serializa, e o trecho
   * que chega enquanto uma roda espera a vez. */
  const filaTrechos = useRef<string[]>([]);
  const escutaEmCurso = useRef(false);
  /* A conversa inteira, como o Whisper a devolveu, na ordem.
   *
   * Num ref e não em estado: cresce a cada frase de uma conversa de trinta
   * minutos, e nada na tela depende dela — ela é lida uma vez, no fim, para
   * virar arquivo. Em estado, cada trecho redesenharia o roteiro inteiro. */
  const transcricaoBruta = useRef<{ quando: number; texto: string }[]>([]);

  const captura = useRef<CapturaEntrevista | null>(null);
  // A pergunta em gravação, lida dentro dos callbacks da captura — que são
  // fixados na construção e não enxergariam o estado do React.
  const emGravacao = useRef<string | null>(null);
  // Espelhos para os mesmos callbacks: eles precisam do texto já respondido e do
  // enunciado da pergunta, e nenhum dos dois chega até lá pelo estado.
  const respostasRef = useRef<Respostas>({});
  respostasRef.current = respostas;
  const roteiroRef = useRef<RoteiroCompleto | null>(null);
  roteiroRef.current = roteiro;
  /* Último texto já conferido, por pergunta. Sem isto, sair e voltar à caixa de
   * texto dispararia uma conferência a cada clique — e cada uma é uma chamada
   * ao modelo, numa tela em que o entrevistador clica o tempo todo. */
  const conferido = useRef<Record<string, string>>({});

  useEffect(() => {
    obterRoteiro(codigo).then(setRoteiro).catch((e) => setErro(String(e)));
  }, [codigo]);

  /* O que já se sabe do caso, resumido para a conferência.
   *
   * Só respostas curtas — rastreio, escolhas, dados. Os relatos ficam de fora de
   * propósito: eles são o volume da entrevista, e mandá-los inteiros a cada
   * pergunta encareceria a conferência sem dizer mais nada do que o formato do
   * caso, que é o que evita a análise pedir o que outra pergunta já respondeu. */
  const contextoDoCaso = useCallback((exceto: string): string => {
    const atual = roteiroRef.current;
    if (!atual) return "";
    const partes: string[] = [];
    for (const bloco of atual.blocos) {
      for (const p of bloco.perguntas) {
        if (p.id === exceto || p.transcrever) continue;
        const v = respostasRef.current[p.id];
        const texto = Array.isArray(v) ? v.join(", ") : (v ?? "");
        if (texto && texto.length <= 120) partes.push(`${p.texto}: ${texto}`);
      }
    }
    return partes.join("\n").slice(0, 1500);
  }, []);

  const conferir = useCallback(
    (perguntaId: string, texto: string, forcar = false) => {
      const atual = roteiroRef.current;
      if (!atual) return;
      const pergunta = atual.blocos
        .flatMap((b) => b.perguntas)
        .find((p) => p.id === perguntaId);
      // Só as narrativas graváveis: conferir um CPF contra precedentes não diz
      // nada, e gastaria uma chamada por campo digitado.
      if (!pergunta?.transcrever) return;

      const limpo = texto.trim();
      if (limpo.length < MINIMO_PARA_CONFERIR) return;
      if (!forcar && conferido.current[perguntaId] === limpo) return;
      conferido.current[perguntaId] = limpo;

      setConferencias((c) => ({
        ...c,
        [perguntaId]: { carregando: true, analise: c[perguntaId]?.analise ?? null, erro: null },
      }));

      void analisarResposta(perguntaId, pergunta.texto, limpo, contextoDoCaso(perguntaId))
        .then((analise) =>
          setConferencias((c) => ({
            ...c,
            [perguntaId]: { carregando: false, analise, erro: null },
          })),
        )
        .catch((e) => {
          // A conferência falhando não pode parar a entrevista: o erro fica
          // discreto embaixo da pergunta e o roteiro segue.
          conferido.current[perguntaId] = "";
          setConferencias((c) => ({
            ...c,
            [perguntaId]: {
              carregando: false,
              analise: null,
              erro: e instanceof Error ? e.message : "Não foi possível conferir a resposta.",
            },
          }));
        });
    },
    [contextoDoCaso],
  );

  // Lido dentro dos callbacks da captura, que são fixados na construção.
  const conferirRef = useRef(conferir);
  conferirRef.current = conferir;

  /* Consome a fila de trechos, um por vez.
   *
   * Cada volta manda o trecho e o estado ATUAL das respostas: é assim que a
   * escuta sabe o que já foi respondido e não repete pergunta. Por isso a
   * serialização importa — mandar duas em paralelo é mandar duas vezes o mesmo
   * estado velho. */
  const consumirFila = useCallback(async () => {
    if (escutaEmCurso.current) return;
    escutaEmCurso.current = true;
    setOuvindo(true);
    try {
      while (filaTrechos.current.length > 0) {
        // Junta o que se acumulou: se três trechos entraram enquanto a chamada
        // anterior rodava, eles são uma frase só para quem vai interpretá-los.
        const trecho = filaTrechos.current.join(" ").trim();
        filaTrechos.current = [];
        if (!trecho) continue;

        const r = await escutarTrecho(trecho, respostasRef.current, "empregado_publico", atualRef.current);
        setErroEscuta(null);
        setFaltando(r.faltando);
        setLembretes(r.lembretes);
        if (r.sugestoes.length) {
          // Sugestão nova de um campo substitui a anterior daquele campo: o
          // cliente que repete o CPF está corrigindo, não acrescentando.
          setSugestoes((atuais) => [
            ...atuais.filter((s) => !r.sugestoes.some((n) => n.pergunta_id === s.pergunta_id)),
            ...r.sugestoes,
          ]);
        }
        if (r.preenchidas.length) {
          // Caiu em qualquer pergunta: a entrevista está andando, e a cobrança
          // recolhe enquanto isso durar.
          setUltimoPreenchimento(Date.now());
          setRespostas((atuais) => {
            const novo = { ...atuais };
            for (const p of r.preenchidas) {
              const anterior = String(novo[p.pergunta_id] ?? "").trim();
              // Acrescenta em vez de substituir: o cliente volta ao assunto
              // várias vezes numa conversa, e o segundo trecho complementa o
              // primeiro em vez de apagá-lo.
              novo[p.pergunta_id] = anterior ? `${anterior} ${p.valor}` : p.valor;
            }
            // A fila pode começar a interpretar o próximo trecho antes de o
            // React renderizar novamente. Atualizar o espelho aqui garante que
            // esse trecho já veja todos os complementos recém-aplicados.
            respostasRef.current = novo;
            return novo;
          });
          setOuvidas((atuais) => [
            ...atuais.filter((o) => !r.preenchidas.some((n) => n.pergunta_id === o.pergunta_id)),
            ...r.preenchidas,
          ]);
        }
      }
    } catch (e) {
      // A escuta falhando não pode parar a entrevista: a conversa continua e os
      // campos seguem editáveis à mão.
      setErroEscuta(
        e instanceof Error ? e.message : "A escuta automática falhou. Digite à mão.",
      );
    } finally {
      escutaEmCurso.current = false;
      setOuvindo(false);
    }
  }, []);

  const consumirFilaRef = useRef(consumirFila);
  consumirFilaRef.current = consumirFila;

  if (captura.current === null && typeof window !== "undefined") {
    captura.current = new CapturaEntrevista({
      onParcial: (texto) => {
        // A primeira palavra transcrita já responde o que o aviso explicava.
        setAviso(null);
        setParcial(texto);
      },
      onAviso: setAviso,
      /* Limiar medido nesta máquina: silêncio de microfone aberto fica em
       * 0,0004–0,0005 (está nos logs do serviço); fala passa de 0,01. 0,002
       * fica no meio, longe dos dois — não dispara com ruído de sala nem deixa
       * de disparar com voz baixa. */
      onNivel: (rms) => {
        if (rms <= 0.002) return;
        setUltimoSom(Date.now());
        /* MEDIANA dos blocos com som — não média, não pico. A média afunda com
         * as pausas (a maior parte de uma entrevista é silêncio) e o pico sobe
         * com um estalo de mesa. A mediana separou limpo os dois extremos
         * medidos aqui: microfone baixo 0,023, microfone bom 0,061.
         *
         * Só os blocos COM som entram: incluir o silêncio mediria quanto a
         * pessoa fala, não quão alto. */
        const b = niveisComSom.current;
        b.push(rms);
        if (b.length > 40) b.shift(); // ~20s de fala
        /* 20 blocos (~10s de fala) antes de opinar. Com 8 a mediana pulava a
         * cada frase e o aviso piscava — e aviso que pisca ninguém lê. */
        if (b.length >= 20) {
          const ordenado = [...b].sort((x, y) => x - y);
          setNivelTipico(ordenado[Math.floor(ordenado.length / 2)]);
        }
      },
      onChegada: setChegada,
      /* Um trecho parou de mudar. Vai para a fila, não direto para a API: dois
       * trechos podem confirmar quase juntos, e a fila os junta numa chamada. */
      onTrecho: (texto) => {
        if (!texto.trim()) return;
        setUltimaFala(Date.now());
        // Guardado ANTES de ir para a escuta: o arquivo bruto é o que foi dito,
        // não o que o modelo entendeu — inclusive o que ele descartou.
        transcricaoBruta.current.push({ quando: Date.now(), texto: texto.trim() });
        filaTrechos.current.push(texto);
        void consumirFilaRef.current();
      },
      onFinal: (texto) => {
        const id = emGravacao.current;
        if (id) {
          // Acrescenta em vez de substituir: é o que faz "adicionar complemento"
          // funcionar — o cliente completa a resposta depois de uma pausa, e o
          // trecho novo entra no fim do que já havia.
          const novo = [String(respostasRef.current[id] ?? ""), texto]
            .filter(Boolean)
            .join(" ");
          setRespostas((r) => ({ ...r, [id]: novo }));
          // A conferência roda sobre a resposta INTEIRA, não só o trecho novo:
          // o complemento costuma justamente preencher a lacuna apontada antes.
          conferirRef.current(id, novo);
        }
        emGravacao.current = null;
        setGravandoId(null);
        setFinalizando(false);
        setParcial("");
      },
      onEstado: (e) => {
        setEstadoMic(e);
        // A trilha acabou (microfone desconectado, chamada caída): sem fonte, o
        // botão de gravar não pode continuar oferecendo o que não existe.
        if (e === "sem-audio") setFonte("nenhuma");
      },
      onErro: (m) => {
        setErro(m);
        /* Destrava a pergunta.
         *
         * Sem isto, um erro na transcrição deixava `gravandoId` preso para
         * sempre: a pergunta continuava mostrando "Pausar" e "Finalizar", os
         * dois clicavam em nada (a captura já não estava gravando) e a única
         * saída era recarregar a página perdendo a entrevista. */
        emGravacao.current = null;
        setGravandoId(null);
        setFinalizando(false);
        setParcial("");
      },
    });
  }

  useEffect(
    () => () => {
      /* Sair da tela também fecha a gravação. Sem isto, quem clicasse em
       * "Fechar sem concluir" deixaria o áudio parado em WAV, sem MP4 e sem
       * ninguém para pedi-lo. O POST vai solto de propósito: o componente está
       * indo embora e não há mais tela para receber a resposta — o que importa
       * é o arquivo ficar convertido no disco. */
      void captura.current?.encerrarGravacao().catch(() => undefined);
      captura.current?.encerrar();
    },
    [],
  );

  useImperativeHandle(
    ref,
    () => ({
      usarFaixaDaChamada: async (trilha: MediaStreamTrack) => {
        await captura.current?.usarTrilha(trilha);
        setFonte("chamada");
        setErro(null);
      },
      aoPerderChamada: () => {
        // Só solta se a fonte era a chamada: quem estava no microfone continua
        // no microfone, mesmo que a chamada do lado tenha caído.
        if (fonteAtual.current === "chamada") {
          captura.current?.encerrar();
          setFonte("nenhuma");
        }
      },
      temVideoPendente: () => videoPendente.current,
      sugestoesPendentes: () => sugestoesRef.current.length,
      encerrarGravacao: async () => {
        await encerrarEscutaRef.current();
        return captura.current?.entrevistaId ?? "";
      },
      transcricaoBruta: () => [...transcricaoBruta.current],
    }),
    [],
  );

  const ligarMicrofone = useCallback(async () => {
    setErro(null);
    try {
      await captura.current?.selecionarAudio();
      setFonte("microfone");
    } catch (e) {
      const m = e instanceof Error ? e.message : "Não foi possível abrir o microfone.";
      setErro(/NotAllowedError|denied/i.test(m) ? "Permissão de microfone negada." : m);
    }
  }, []);

  /* Começa a gravar — ou volta a gravar por cima de uma resposta que já existe.
   *
   * São a mesma operação: o `onFinal` acrescenta ao que já havia. O que muda é
   * só o rótulo do botão, e é a diferença entre "gravar a resposta" e
   * "complementar o que ele já disse" — que é o que se faz depois de ler a
   * conferência e descobrir que faltou perguntar da CAT. */
  const gravar = useCallback(async (perguntaId: string) => {
    setErro(null);
    setParcial("");
    setEscutaEncerrada(false); // gravar de novo é gravação em curso, não fecho
    try {
      emGravacao.current = perguntaId;
      setGravandoId(perguntaId);
      await captura.current?.iniciarResposta(perguntaId);
    } catch (e) {
      emGravacao.current = null;
      setGravandoId(null);
      setErro(e instanceof Error ? e.message : "Não foi possível iniciar.");
    }
  }, []);

  /* Abre a escuta da entrevista inteira. É o "podemos começar?" do roteiro.
   *
   * Daqui em diante ninguém aperta gravar: a conversa corre e o roteiro se
   * preenche atrás dela. */
  const comecarEntrevista = useCallback(async () => {
    setErro(null);
    setErroEscuta(null);
    /* Some com o painel do áudio ANTES de voltar a gravar.
     *
     * Ele fecha a gravação do id que recebe: deixado na tela durante uma
     * entrevista nova, encerraria a conversa que acabou de começar. */
    setEscutaEncerrada(false);
    try {
      if (!captura.current) throw new Error("A gravação ainda não está pronta.");
      if (estadoMic === "sem-audio") await captura.current.selecionarAudio();
      // O mesmo clique que abre a entrevista abre a sessão contínua no servidor:
      // não existe estado de entrevista em andamento sem gravação de áudio.
      await captura.current.iniciarEntrevista();
      emGravacao.current = null;
      setEscutando(true);
      setFonte("microfone");
      // Abre o painel com o que o roteiro pede, antes de alguém falar.
      filaTrechos.current = [];
      void escutarTrecho("", respostasRef.current)
        .then((r) => setFaltando(r.faltando))
        .catch(() => undefined);
    } catch (e) {
      const m = e instanceof Error ? e.message : "Não foi possível abrir o microfone.";
      setErro(/NotAllowedError|denied/i.test(m) ? "Permissão de microfone negada." : m);
    }
  }, [estadoMic]);

  const encerrarEscuta = useCallback(async () => {
    // Fecha a resposta ANTES: é o que faz o navegador parar de mandar bytes.
    captura.current?.finalizarResposta();
    setEscutando(false);
    /* E só então oferece o áudio. O `aguardarEnvio` é o que separa "a fala
     * inteira está no arquivo" de "faltou o fim": o encerramento vai por HTTP,
     * numa conexão diferente da que leva o PCM, e poderia chegar primeiro. */
    await captura.current?.aguardarEnvio();
    setEscutaEncerrada(true);
  }, []);

  // Lido pelo `useImperativeHandle`, fixado na montagem: é assim que a tela de
  // fora fecha a gravação no fim do atendimento, e não antes.
  const encerrarEscutaRef = useRef(encerrarEscuta);
  encerrarEscutaRef.current = encerrarEscuta;

  const aceitarSugestao = useCallback((perguntaId: string, valor: string) => {
    setRespostas((r) => ({ ...r, [perguntaId]: valor }));
    setSugestoes((s) => s.filter((x) => x.pergunta_id !== perguntaId));
  }, []);

  const descartarSugestao = useCallback((perguntaId: string) => {
    setSugestoes((s) => s.filter((x) => x.pergunta_id !== perguntaId));
  }, []);

  /** Rola até o campo e o destaca — o painel é índice, não só relatório. */
  const irPara = useCallback((perguntaId: string) => {
    const alvo = document.getElementById(`pergunta-${perguntaId}`);
    if (!alvo) return;
    alvo.scrollIntoView({ behavior: "smooth", block: "center" });
    alvo.querySelector("textarea,input,select,button")?.setAttribute("data-realce", "1");
    (alvo.querySelector("textarea,input") as HTMLElement | null)?.focus();
  }, []);

  /* Tira a pergunta da vez sem respondê-la. Ela continua pendente: o painel a
   * mostra em "falta perguntar" e a condução a devolve quando o roteiro acabar,
   * ou antes, no "retomar". */
  const pular = useCallback((perguntaId: string) => {
    setPuladas((p) => (p.includes(perguntaId) ? p : [...p, perguntaId]));
  }, []);

  const retomarPuladas = useCallback(() => setPuladas([]), []);

  const pausar = useCallback(() => captura.current?.pausar(), []);
  const retomar = useCallback(() => captura.current?.retomar(), []);
  const finalizar = useCallback(() => {
    // Marca ANTES de mandar parar: o servidor pode levar segundos para devolver
    // o texto, e é essa marca que troca os botões por "Transcrevendo…" em vez
    // de deixar dois botões inertes na tela.
    setFinalizando(true);
    captura.current?.finalizarResposta();
  }, []);

  const responder = useCallback((id: string, valor: string | string[]) => {
    setRespostas((r) => ({ ...r, [id]: valor }));
  }, []);

  /* Só entram os módulos cujo rastreio deu positivo: quem não sofreu assalto
   * não percorre o módulo de assalto. */
  const blocosVisiveis = useMemo(() => {
    if (!roteiro) return [];
    const positivos = new Set(
      Object.entries(roteiro.mapa_rastreio)
        .filter(([perguntaId]) => respostas[perguntaId] === "sim")
        .map(([, modulo]) => modulo),
    );
    return roteiro.blocos.filter((b) => !b.modulo || positivos.has(b.modulo));
  }, [roteiro, respostas]);

  /* A SEQUÊNCIA — a ordem em que as perguntas são feitas, que é a ordem do
   * documento do escritório e nenhuma outra.
   *
   * Blocos delegados ficam de fora: a qualificação passou ao Departamento de
   * Documentação, que a colhe depois do encerramento (ver `roteiros.py`). Ela
   * segue na tela, para quem for colhê-la, mas arrastar o entrevistador por
   * catorze campos de cadastro no meio da conversa é o formulário que o
   * escritório mandou tirar do começo da entrevista. */
  const sequencia = useMemo(
    () =>
      blocosVisiveis
        .filter((b) => !b.delegado_a)
        .flatMap((b) => b.perguntas.map((pergunta) => ({ pergunta, bloco: b.titulo }))),
    [blocosVisiveis],
  );

  /* Pergunta que já tem sugestão esperando um clique NÃO é pergunta a fazer.
   *
   * Nome e CPF nunca entram sozinhos: a escuta os manda como sugestão, e quem
   * confirma é quem está ouvindo (ver `escuta.DADOS_PERMITIDOS` — dígito
   * transcrito ninguém confere de ouvido). Só que "esperando confirmação" é
   * outra coisa que "o cliente não respondeu": ele já falou o nome dele.
   *
   * Sem esta linha a condução parava nas duas primeiras perguntas do roteiro
   * até alguém achar o clique no painel ao lado — com a cobrança de PARE no ar
   * o tempo todo, mandando insistir numa pergunta que o cliente já tinha
   * respondido. A confirmação continua obrigatória; ela é que não trava mais a
   * conversa, e a pergunta volta à vez sozinha se a sugestão for descartada. */
  const aguardandoConfirmacao = useMemo(
    () => new Map(sugestoes.map((s) => [s.pergunta_id, s.valor] as const)),
    [sugestoes],
  );

  /* A pergunta da vez: a primeira ainda em aberto, na ordem.
   *
   * O que o cliente adiantar fora de ordem já entrou pela escuta e some daqui
   * sozinho — é assim que a entrevista encurta sem que ninguém perca o fio.
   * Quem escolhe a pergunta é o roteiro; o entrevistador só a lê. */
  const posicaoNatural = useMemo(
    () =>
      sequencia.findIndex(
        ({ pergunta }) =>
          !respondida(respostas[pergunta.id]) &&
          !puladas.includes(pergunta.id) &&
          !aguardandoConfirmacao.has(pergunta.id),
      ),
    [sequencia, respostas, puladas, aguardandoConfirmacao],
  );

  /* Resposta aceita libera a próxima pergunta no mesmo render. A captura e a
   * fila de interpretação continuam independentes da pergunta visível, então
   * uma fala posterior ainda pode complementar qualquer resposta anterior. */
  const posicaoAtual = posicaoNatural;
  const atual = posicaoAtual >= 0 ? sequencia[posicaoAtual] : null;
  atualRef.current = atual?.pergunta.id ?? "";
  /** A entrevista anda: caiu resposta em ALGUMA pergunta há pouco. */
  const fluindo =
    ultimoPreenchimento !== null &&
    Date.now() - ultimoPreenchimento < SEGUNDOS_FLUINDO * 1000;

  /* Nome e CPF são DIGITADOS, e são a condição para o microfone abrir.
   *
   * Regra do escritório, e ela resolve um problema medido: a escuta escrevia
   * "Guilherme Inunes" no lugar de "Guilherme Nunes", e o modelo — certo —
   * recusava-se a preencher a partir de texto ilegível. O campo ficava vazio
   * sem explicação, e o contrato, a procuração e a declaração nasciam sem os
   * dois dados que identificam o cliente.
   *
   * Digitados antes de começar, não há o que ouvir: quando a escuta abre, eles
   * já estão respondidos, e a condução parte da terceira pergunta. */
  const faltaParaComecar = useMemo(() => {
    const pendentes: string[] = [];
    if (!respondida(respostas["nome"])) pendentes.push("o nome completo");
    if (conferirCpf(String(respostas["cpf"] ?? "")).valido !== true) {
      pendentes.push("um CPF válido");
    }
    return pendentes;
  }, [respostas]);

  const { total, feitas } = useMemo(() => {
    const resp = sequencia.filter(({ pergunta }) => respondida(respostas[pergunta.id]));
    return { total: sequencia.length, feitas: resp.length };
  }, [sequencia, respostas]);

  const relatoConsolidado = useMemo(
    () => montarRelato(blocosVisiveis, respostas),
    [blocosVisiveis, respostas],
  );
  const lacunasObrigatorias = useMemo(
    () =>
      sequencia
        .filter(({ pergunta }) => pergunta.obrigatoria && !respondida(respostas[pergunta.id]))
        .map(({ pergunta }) => pergunta.texto),
    [sequencia, respostas],
  );

  /* Espera a fala virar resposta consolidada. Trechos provisórios do Whisper não
   * mudam `respostas`; e o debounce evita uma consulta por campo quando a escuta
   * preenche vários de uma vez. A última leitura boa permanece visível em falha. */
  useEffect(() => {
    if (relatoConsolidado.length < 160 || feitas < 3) return;
    if (relatoConsolidado === ultimoRelatoRecomendado.current) return;
    const timer = window.setTimeout(() => {
      setAtualizandoRecomendacao(true);
      recomendarEntrevista(relatoConsolidado, lacunasObrigatorias)
        .then((resultado) => {
          setRecomendacaoCaso(resultado);
          setErroRecomendacao(null);
          ultimoRelatoRecomendado.current = relatoConsolidado;
        })
        .catch((falha) =>
          setErroRecomendacao(
            falha instanceof Error ? falha.message : "Recomendação temporariamente indisponível.",
          ),
        )
        .finally(() => setAtualizandoRecomendacao(false));
    }, 3500);
    return () => window.clearTimeout(timer);
  }, [relatoConsolidado, lacunasObrigatorias, feitas]);

  /* Sobe o que já foi respondido, sem esperar o fim da entrevista.
   *
   * O ref é para o callback poder ser inline no pai (novo a cada render) sem
   * disparar este efeito a cada volta — o que interessa é a mudança das
   * RESPOSTAS. */
  const aoMudar = useRef(onRespostas);
  aoMudar.current = onRespostas;
  useEffect(() => {
    if (!aoMudar.current) return;
    aoMudar.current(
      respostas,
      montarRelato(blocosVisiveis, respostas),
      captura.current?.entrevistaId ?? "",
    );
  }, [respostas, blocosVisiveis]);

  if (erro && !roteiro) return <p className={estilos.vazio}>{erro}</p>;
  if (!roteiro) return <p className={estilos.vazio}>Carregando o roteiro…</p>;

  const temMic = estadoMic !== "sem-audio";

  return (
    <div className={estilos.tela}>
      {/* No TOPO e sem poder ser fechado: enquanto isto estiver na tela, o que
        * for falado não vira campo preenchido. É a única coisa que importa. */}
      {sessaoCaiu && (
        <div className={estilos.sessaoCaiu} role="alert">
          <strong>Sua sessão expirou — o que está sendo dito NÃO está sendo salvo.</strong>{" "}
          A transcrição continua na tela, mas o roteiro parou de ser preenchido.
          Recarregue a página (F5) para voltar a gravar; o que já foi preenchido
          está guardado.
        </div>
      )}
      <div className={estilos.cabecalho}>
        <div>
          <h2 className={estilos.titulo}>{roteiro.nome}</h2>
        </div>
        <div className={transcricaoEstilos.acoes}>
          {/* O botão que abre a entrevista inteira. Substitui os 86 ciclos de
              gravar/finalizar: daqui em diante o microfone fica aberto e o
              roteiro se preenche atrás da conversa. */}
          {escutando && (
            <button
              type="button"
              className={transcricaoEstilos.secundario}
              onClick={() => void encerrarEscuta()}
            >
              Encerrar escuta
            </button>
          )}

          {/* Com a chamada no ar, o microfone daqui não entra na transcrição —
              ele serve para o entrevistado ouvir o advogado, e quem cuida disso
              é o painel da chamada. Oferecer "ligar microfone" aqui convidaria a
              trocar a voz do cliente pela do entrevistador sem perceber. */}
          {fonte !== "chamada" && !escutando && (
            <button
              type="button"
              className={transcricaoEstilos.secundario}
              onClick={ligarMicrofone}
              disabled={gravandoId !== null}
            >
              {temMic ? "Trocar microfone" : "Ligar microfone"}
            </button>
          )}

          <span className={estilos.fonte}>
            {fonte === "chamada"
              ? "transcrevendo a voz do entrevistado"
              : fonte === "microfone"
                ? "transcrevendo este microfone"
                : "sem áudio"}
          </span>

          <button
            type="button"
            className={estilos.teste}
            onClick={() => {
              const amostra = entrevistaDeTeste(roteiro.blocos);
              // Completa o que falta sem apagar respostas que já foram
              // digitadas ou transcritas pelo cliente.
              setRespostas((atuais) => {
                const preenchidas = { ...amostra };
                for (const [id, valor] of Object.entries(atuais)) {
                  if (respondida(valor)) preenchidas[id] = valor;
                }
                return preenchidas;
              });
              setPuladas([]);
              setAviso("Campos vazios preenchidos automaticamente com dados fictícios para teste.");
            }}
            title="Completa os campos vazios com uma entrevista fictícia; não substitui respostas existentes"
          >
            Preencher automaticamente
          </button>

          <span className={estilos.progresso}>
            {feitas}/{total}
          </span>
        </div>
      </div>

      <div className={estilos.barra}>
        <i
          className={estilos.preenchimento}
          style={{ width: `${total ? (feitas / total) * 100 : 0}%` }}
        />
      </div>

      {/* O vídeo fica aqui em cima porque gravar em vídeo se decide no começo
        * da conversa — e porque ele não é guardado em lugar nenhum, então quem
        * quiser precisa ver a opção antes, não depois. */}
      <VideoDaEntrevista
        onPendente={(pendente) => {
          videoPendente.current = pendente;
        }}
      />

      {erro && <div className={transcricaoEstilos.erro}>{erro}</div>}

      {aviso && (
        <p className={transcricaoEstilos.aviso} aria-live="polite">
          {aviso}
        </p>
      )}

      {/* A porta de entrada: sem nome e CPF, o microfone não abre.
        *
        * O aviso diz o que falta e leva até o campo, em vez de deixar um botão
        * cinza sem explicação — que é como o entrevistador descobriria a regra,
        * com o cliente esperando. */}
      {!escutando && faltaParaComecar.length > 0 && (
        <p className={transcricaoEstilos.aviso}>
          <strong>Digite {faltaParaComecar.join(" e ")} para começar.</strong> São os dois
          dados que abrem o atendimento e que o contrato, a procuração e a declaração
          exigem — e os únicos que não se colhem de ouvido, porque número e nome próprio
          a transcrição erra.{" "}
          <button
            type="button"
            className={estilos.saudacaoAlternar}
            onClick={() => irPara(respondida(respostas["nome"]) ? "cpf" : "nome")}
          >
            ir ao campo
          </button>
        </p>
      )}

      {!temMic && !escutando && faltaParaComecar.length === 0 && (
        <p className={transcricaoEstilos.aviso}>
          Clique em <strong>Começar a entrevista</strong> para abrir o microfone. Daí em
          diante a conversa é transcrita e o roteiro se preenche sozinho — você não
          precisa gravar pergunta por pergunta.
        </p>
      )}

      {/* O áudio passou a ser GUARDADO, não só transcrito. A saudação do roteiro
        * promete sigilo e não fala em gravação; enquanto ela não falar, quem
        * avisa é o entrevistador — e o lembrete fica onde ele olha antes de
        * abrir o microfone, não escondido num rodapé. */}
      {escutando && (
        <p className={transcricaoEstilos.aviso}>
          A conversa está sendo <strong>gravada e transcrita</strong>, e o áudio fica
          guardado nesta máquina. Avise o cliente — o roteiro promete sigilo, mas não
          menciona gravação.
        </p>
      )}

      {/* A saudação, palavra por palavra, para ser LIDA ao cliente.
        *
        * Fica recolhida depois de lida porque ela é longa e ocupa a tela que o
        * roteiro precisa; mas não some, porque a atendente pode querer voltar a
        * uma frase. Ver `roteiros.SAUDACAO`. */}
      {roteiro.saudacao?.length > 0 && (
        <section className={estilos.saudacao}>
          <div className={estilos.saudacaoTopo}>
            <span className={estilos.saudacaoRotulo}>LEIA AO CLIENTE</span>
            <button
              type="button"
              className={estilos.saudacaoAlternar}
              onClick={() => setSaudacaoLida((v) => !v)}
            >
              {saudacaoLida ? "mostrar de novo" : "já li"}
            </button>
          </div>
          {!saudacaoLida &&
            roteiro.saudacao.map((p, i) => (
              <p key={i} className={estilos.saudacaoTexto}>
                {p}
              </p>
            ))}
        </section>
      )}

      {(recomendacaoCaso || atualizandoRecomendacao || erroRecomendacao) && (
        <section className={estilos.recomendacao} aria-live="polite">
          <div className={estilos.recomendacaoTopo}>
            <strong>Vale abrir este caso?</strong>
            {atualizandoRecomendacao && <span>atualizando com as respostas…</span>}
          </div>
          {recomendacaoCaso && (
            <>
              <div className={`${estilos.veredito} ${estilos[`veredito_${recomendacaoCaso.recomendado}`]}`}>
                {recomendacaoCaso.recomendado === "sim" ? "SIM — levar para análise" :
                  recomendacaoCaso.recomendado === "com_ressalva" ? "COM RESSALVAS" :
                  recomendacaoCaso.recomendado === "atencao" ? "ATENÇÃO ANTES DE ABRIR" :
                  "AMOSTRA INSUFICIENTE"}
              </div>
              <p>{recomendacaoCaso.motivo}</p>
              {recomendacaoCaso.analise_comparativa && (() => {
                const analise = recomendacaoCaso.analise_comparativa;
                const refs = (indices: string[]) => indices.map((indice) => {
                  const ref = analise.referencias[indice];
                  if (!ref) return indice;
                  const rotulo = `${indice}: ${ref.processo ?? "processo sem número"}`;
                  return ref.url ? <a key={indice} href={ref.url} target="_blank" rel="noreferrer">{rotulo}</a> : <span key={indice}>{rotulo}</span>;
                }).reduce<React.ReactNode[]>((todos, item, i) => i ? [...todos, ", ", item] : [item], []);
                return (
                  <div className={estilos.comparativa}>
                    <h4>O que os processos semelhantes indicam</h4>
                    <p>{analise.sintese}</p>
                    {analise.pontos_comuns.length > 0 && (
                      <details open><summary>Pontos realmente em comum</summary><ul>{analise.pontos_comuns.map((item, i) => <li key={i}><strong>{item.ponto}</strong> — {item.impacto} <small>Força {item.forca}: {refs(item.precedentes)}</small></li>)}</ul></details>
                    )}
                    {analise.diferencas_decisivas.length > 0 && (
                      <details open><summary>O que separou resultados favoráveis e improcedentes</summary><ul>{analise.diferencas_decisivas.map((item, i) => <li key={i}><strong>{item.ponto}</strong> — {item.por_que_importa}<small>Favoráveis: {refs(item.precedentes_favoraveis)} · Contrários: {refs(item.precedentes_contrarios)}</small></li>)}</ul></details>
                    )}
                    {analise.provas_prioritarias.length > 0 && (
                      <details open><summary>Provas para buscar agora</summary><ul>{analise.provas_prioritarias.map((item, i) => <li key={i}><strong>{item.prova}</strong> — {item.motivo}<small>{refs(item.precedentes)}</small></li>)}</ul></details>
                    )}
                    {analise.perguntas_criticas.length > 0 && (
                      <details open><summary>Perguntas que podem mudar a avaliação</summary><ol>{analise.perguntas_criticas.map((item) => <li key={item}>{item}</li>)}</ol></details>
                    )}
                  </div>
                );
              })()}
              {recomendacaoCaso.lacunas_obrigatorias.length > 0 && (
                <details><summary>{recomendacaoCaso.lacunas_obrigatorias.length} pontos obrigatórios ainda faltam</summary><ul>{recomendacaoCaso.lacunas_obrigatorias.slice(0, 8).map((item) => <li key={item}>{item}</li>)}</ul></details>
              )}
              {recomendacaoCaso.precedentes.length > 0 && (
                <details><summary>{recomendacaoCaso.precedentes.length} processos semelhantes consultados</summary><ul>{recomendacaoCaso.precedentes.slice(0, 8).map((p, i) => <li key={`${p.processo}-${i}`}>{p.url ? <a href={p.url} target="_blank" rel="noreferrer">{p.processo || `Precedente ${i + 1}`}</a> : (p.processo || `Precedente ${i + 1}`)} — {p.resultado || "resultado não classificado"} · {(p.similaridade * 100).toFixed(0)}%</li>)}</ul></details>
              )}
              <small>{recomendacaoCaso.aviso}</small>
            </>
          )}
          {erroRecomendacao && <p className={estilos.recomendacaoErro}>{erroRecomendacao} A entrevista continua normalmente.</p>}
        </section>
      )}

      <div className={escutando ? estilos.comPainel : undefined}>
        <div>
          {/* A pergunta da vez, grudada no alto da coluna do roteiro. Vem ANTES
            * das perguntas todas porque é o que se lê ao cliente; o que está
            * embaixo é o formulário que se preenche. Fica DENTRO da coluna, e
            * não por cima do painel: os dois grudam ao rolar, e um passaria por
            * cima do outro. Enquanto a escuta não abriu ela só aponta por onde
            * começar — sem relógio, porque não há entrevista para cobrar ainda. */}
          <Conducao
            pergunta={atual?.pergunta ?? null}
            bloco={atual?.bloco ?? ""}
            posicao={posicaoAtual + 1}
            total={total}
            puladas={puladas.length}
            sugestoes={sugestoes}
            retomadas={roteiro.retomadas ?? []}
            fechosPorTipo={roteiro.fechos_por_tipo ?? {}}
            ativo={escutando && estadoMic !== "pausado"}
            respondendo={false}
            fluindo={fluindo}
            onIrPara={irPara}
            onPular={pular}
            onRetomarPuladas={retomarPuladas}
            onAceitar={aceitarSugestao}
            onDescartar={descartarSugestao}
          />

          {blocosVisiveis.map((bloco) => (
            <BlocoRoteiro
              key={bloco.id}
              bloco={bloco}
              respostas={respostas}
              perguntaAtual={atual?.pergunta.id ?? ""}
              puladas={puladas}
              aguardando={aguardandoConfirmacao}
              onResponder={responder}
              gravandoId={gravandoId}
              pausado={estadoMic === "pausado"}
              finalizando={finalizando}
              parcial={parcial}
              temMic={temMic}
              escutando={escutando}
              onGravar={gravar}
              onPausar={pausar}
              onRetomar={retomar}
              onFinalizar={finalizar}
              conferencias={conferencias}
              onConferir={conferir}
              rodape={
                !escutando &&
                bloco.perguntas.some((p) => p.id === "nome") &&
                bloco.perguntas.some((p) => p.id === "cpf") ? (
                  <div className={estilos.inicioEntrevista}>
                    <button
                      type="button"
                      className={transcricaoEstilos.botao}
                      onClick={comecarEntrevista}
                      disabled={gravandoId !== null || faltaParaComecar.length > 0}
                      title={
                        faltaParaComecar.length > 0
                          ? `Digite ${faltaParaComecar.join(" e ")} antes de começar`
                          : "Começa a entrevista, a gravação e a transcrição"
                      }
                    >
                      Começar e gravar entrevista
                    </button>
                    <span>
                      Ao clicar, o microfone abre e o áudio começa a ser gravado e
                      transcrito automaticamente.
                    </span>
                  </div>
                ) : undefined
              }
            />
          ))}
        </div>

        {escutando && (
          <PainelEscuta
            preenchidas={ouvidas}
            aConferir={sugestoes.length}
            lembretes={lembretes}
            faltando={faltando}
            interpretando={ouvindo}
            captando={escutando && estadoMic !== "sem-audio"}
            pausado={estadoMic === "pausado"}
            ultimaFala={ultimaFala}
            ultimoSom={ultimoSom}
            nivelTipico={nivelTipico}
            chegada={chegada}
            erro={erroEscuta}
            onIrPara={irPara}
          />
        )}
      </div>

      {/* O encerramento, também para ser lido. Só aparece quando há o que
        * encerrar — no começo da entrevista ele seria ruído. */}
      {roteiro.encerramento?.length > 0 && feitas > 0 && (
        <details className={estilos.encerramento}>
          <summary className={estilos.encerramentoTitulo}>
            Encerramento — o que dizer ao final ({roteiro.encerramento.length} parágrafos)
          </summary>
          {roteiro.encerramento.map((p, i) => (
            <p key={i} className={estilos.saudacaoTexto}>
              {p}
            </p>
          ))}
        </details>
      )}

      {/* O áudio, depois de encerrada a escuta. Antes disso não há arquivo, e um
        * botão que não baixa nada é pior que botão nenhum. */}
      {escutaEncerrada && (
        <AudioDaEntrevista entrevistaId={captura.current?.entrevistaId ?? ""} />
      )}

      {/* Não há botão de concluir aqui.
        *
        * O atendimento não acaba no fim das perguntas: a avaliação, os
        * documentos e a assinatura vêm logo abaixo, na mesma rolagem, e um
        * "concluir entrevista" no meio disso encerraria a gravação e a chamada
        * justamente quando o roteiro manda permanecer nelas. Quem encerra é a
        * tela de fora (`EntrevistaComChamada`), no fim de tudo. */}
    </div>
  );
}

/** Junta as respostas num texto corrido — é o que alimenta a triagem. */
function montarRelato(blocos: Bloco[], respostas: Respostas): string {
  const partes: string[] = [];
  for (const bloco of blocos) {
    const doBloco = bloco.perguntas
      .map((p) => {
        const v = respostas[p.id];
        const texto = Array.isArray(v) ? v.join(", ") : v;
        return texto ? `${p.texto}\n${texto}` : "";
      })
      .filter(Boolean);
    if (doBloco.length) partes.push(`## ${bloco.titulo}\n\n${doBloco.join("\n\n")}`);
  }
  return partes.join("\n\n");
}

function BlocoRoteiro({
  bloco,
  respostas,
  perguntaAtual,
  puladas,
  aguardando,
  onResponder,
  gravandoId,
  pausado,
  finalizando,
  parcial,
  temMic,
  escutando,
  onGravar,
  onPausar,
  onRetomar,
  onFinalizar,
  conferencias,
  onConferir,
  rodape,
}: {
  bloco: Bloco;
  respostas: Respostas;
  /** A pergunta da vez na sequência — marcada na lista para o olho achar. */
  perguntaAtual: string;
  puladas: string[];
  /** Ouvidas e esperando conferência, por id -> o que a escuta ouviu. Saíram da
   *  vez, mas não estão respondidas — e o valor aparece para o entrevistador
   *  VER que o sistema pegou, sem ter de parar a conversa para confirmar. */
  aguardando: Map<string, string>;
  onResponder: (id: string, valor: string | string[]) => void;
  gravandoId: string | null;
  pausado: boolean;
  finalizando: boolean;
  parcial: string;
  temMic: boolean;
  /** A entrevista está com o microfone aberto: os botões por pergunta somem. */
  escutando: boolean;
  onGravar: (id: string) => void;
  onPausar: () => void;
  onRetomar: () => void;
  onFinalizar: () => void;
  conferencias: Record<string, EstadoConferencia>;
  onConferir: (id: string, texto: string, forcar?: boolean) => void;
  /** Ação contextual depois do bloco de identificação (nome e CPF). */
  rodape?: ReactNode;
}) {
  return (
    <section className={estilos.bloco}>
      <span className={estilos.blocoTitulo}>{bloco.titulo.toUpperCase()}</span>
      {bloco.objetivo && <p className={estilos.objetivo}>{bloco.objetivo}</p>}

      {/* O bloco que NÃO se percorre na entrevista.
        *
        * Ele ficava aqui igual aos outros, e nada na tela dizia que a condução
        * pula estes campos de propósito — quem não conhecia o roteiro começava
        * a datilografar a qualificação com o cliente esperando. */}
      {bloco.delegado_a && (
        <p className={estilos.delegado}>
          <strong>Não percorrer nesta entrevista.</strong> Esta etapa é do{" "}
          {bloco.delegado_a}, depois do encerramento.
          {bloco.instrucao && <span className={estilos.delegadoNota}>{bloco.instrucao}</span>}
        </p>
      )}

      <ul className={estilos.lista}>
        {bloco.perguntas.map((p, i) => (
          <li
            key={p.id}
            // A âncora que o painel usa para rolar até aqui.
            id={`pergunta-${p.id}`}
            className={[
              estilos.pergunta,
              respostas[p.id] ? estilos.respondida : "",
              p.id === perguntaAtual ? estilos.daVez : "",
            ]
              .filter(Boolean)
              .join(" ")}
          >
            <div className={estilos.enunciado}>
              <span className={estilos.numero}>{String(i + 1).padStart(2, "0")}</span>
              <span className={estilos.texto}>
                {p.texto}
                {p.obrigatoria && <span className={estilos.obrigatoria}>*</span>}
              </span>
              {/* A mesma pergunta que está na barra do topo. Sem esta marca, o
                * entrevistador que rolou a tela precisa reler a barra para
                * saber onde ela caiu no formulário. */}
              {p.id === perguntaAtual && <span className={estilos.marcaDaVez}>AGORA</span>}
              {/* Ouvida, não confirmada. A condução seguiu em frente para não
                * travar a conversa; a marca é o que impede a pergunta de passar
                * por respondida quando ainda depende de um clique. */}
              {aguardando.has(p.id) && (
                <span className={estilos.marcaConferir}>OUVIDO · CONFIRA NO FIM</span>
              )}
              {puladas.includes(p.id) && (
                <span className={estilos.marcaPulada}>DEIXADA PARA DEPOIS</span>
              )}
              {p.transcrever && <span className={estilos.marcaGravavel}>VOZ</span>}
            </div>

            {p.dica && <span className={estilos.dica}>{p.dica}</span>}

            <div className={estilos.resposta}>
              <CampoResposta
                pergunta={p}
                valor={respostas[p.id]}
                valorAlvo={p.preenche ? respostas[p.preenche] : undefined}
                onResponder={onResponder}
                gravando={gravandoId === p.id}
                pausado={gravandoId === p.id && pausado}
                finalizando={gravandoId === p.id && finalizando}
                parcial={gravandoId === p.id ? parcial : ""}
                temMic={temMic}
                escutando={escutando}
                ocupado={gravandoId !== null && gravandoId !== p.id}
                onGravar={onGravar}
                onPausar={onPausar}
                onRetomar={onRetomar}
                onFinalizar={onFinalizar}
                onConferir={onConferir}
              />

              {/* O que a escuta ouviu, à mostra no próprio campo.
                *
                * Sem isto o entrevistador fala o nome, o campo continua vazio e
                * a conclusão óbvia é "não pegou nada" — foi exatamente o que
                * aconteceu quando a caixa de confirmação saiu do painel. O
                * valor fica visível; confirmar continua sendo no fim. */}
              {aguardando.has(p.id) && (
                <span className={estilos.ouvido}>
                  ouvi <strong>“{aguardando.get(p.id)}”</strong> — entra no campo quando
                  você confirmar, no fim do roteiro
                </span>
              )}
            </div>

            {/* A conferência mora embaixo da pergunta que a gerou: lida em
              * qualquer outro lugar, ela obrigaria a procurar de qual resposta
              * está falando — e o cliente está esperando. */}
            {p.transcrever && conferencias[p.id] && (
              <ConferenciaResposta
                analise={conferencias[p.id].analise}
                carregando={conferencias[p.id].carregando}
                erro={conferencias[p.id].erro}
                onRefazer={() =>
                  onConferir(p.id, String(respostas[p.id] ?? ""), true)
                }
              />
            )}
          </li>
        ))}
      </ul>
      {rodape}
    </section>
  );
}

/* CEP digitado, endereço preenchido.
 *
 * A entrevista é o gargalo do escritório: cada campo datilografado é tempo com
 * o cliente na frente. O CEP é o único dado do roteiro que uma base pública
 * resolve de graça e sem pedir procuração — e resolve quatro campos de uma vez.
 * O que ele NÃO traz é o número da casa, e por isso o texto preenchido deixa
 * "nº ___" à vista: endereço sem número não serve para citação.
 *
 * CPF continua digitado e conferido pelo dígito verificador. Não existe base
 * pública que troque um CPF por um nome — quem promete isso vende dado vazado.
 * A discussão está em `app/consultas.py`. */
function CampoCep({
  pergunta,
  valor,
  valorAlvo,
  onResponder,
}: {
  pergunta: Pergunta;
  valor: string;
  valorAlvo: string;
  onResponder: (id: string, valor: string | string[]) => void;
}) {
  const [buscando, setBuscando] = useState(false);
  const [achado, setAchado] = useState<EnderecoCep | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  // Uma consulta por CEP: sem isto, cada tecla depois do oitavo dígito
  // (ou qualquer re-render) bateria de novo na base pública.
  const consultado = useRef("");
  // Lidos dentro do efeito sem entrar nas dependências: mudam a cada tecla do
  // campo de endereço, e não é isso que deve disparar uma consulta.
  const alvo = useRef(valorAlvo);
  alvo.current = valorAlvo;
  const responder = useRef(onResponder);
  responder.current = onResponder;

  const digitos = valor.replace(/\D/g, "");

  useEffect(() => {
    if (digitos.length !== 8) {
      consultado.current = "";
      setAchado(null);
      setErro(null);
      return;
    }
    if (consultado.current === digitos) return;
    consultado.current = digitos;

    let cancelado = false;
    setBuscando(true);
    setErro(null);
    consultarCep(digitos)
      .then((endereco) => {
        if (cancelado) return;
        setAchado(endereco);
        // Não sobrescreve o que já foi digitado: o endereço na tela pode ter
        // número e complemento que a base não tem. A troca fica no botão.
        if (!alvo.current.trim()) {
          responder.current(pergunta.preenche, endereco.endereco_formatado);
        }
      })
      .catch((e) => {
        if (!cancelado) setErro(e instanceof Error ? e.message : "Não foi possível consultar o CEP.");
      })
      .finally(() => {
        if (!cancelado) setBuscando(false);
      });

    return () => {
      cancelado = true;
    };
  }, [digitos, pergunta.preenche]);

  return (
    <>
      <input
        className={estilos.campo}
        type="text"
        inputMode="numeric"
        value={valor}
        maxLength={9}
        placeholder="00000-000"
        onChange={(e) => onResponder(pergunta.id, formatarCep(e.target.value))}
      />

      {buscando && <span className={estilos.campoDica}>consultando o endereço…</span>}
      {erro && <span className={estilos.campoErro}>{erro}</span>}

      {achado && !erro && !buscando && (
        <span className={estilos.campoOk}>
          {achado.endereco_formatado}
          <em className={estilos.fonte}>via {achado.fonte}</em>
          {alvo.current.trim() && alvo.current !== achado.endereco_formatado && (
            <button
              type="button"
              className={estilos.usar}
              onClick={() => onResponder(pergunta.preenche, achado.endereco_formatado)}
            >
              Substituir o endereço digitado
            </button>
          )}
        </span>
      )}
    </>
  );
}

function CampoResposta({
  pergunta,
  valor,
  valorAlvo,
  onResponder,
  gravando,
  pausado,
  finalizando,
  parcial,
  temMic,
  escutando,
  ocupado,
  onGravar,
  onPausar,
  onRetomar,
  onFinalizar,
  onConferir,
}: {
  pergunta: Pergunta;
  valor?: string | string[];
  /** Resposta atual do campo que a busca preenche — para não sobrescrevê-la. */
  valorAlvo?: string | string[];
  onResponder: (id: string, valor: string | string[]) => void;
  gravando: boolean;
  pausado: boolean;
  /** Esperando o texto final voltar do servidor. */
  finalizando: boolean;
  parcial: string;
  temMic: boolean;
  /** A entrevista corre com o microfone aberto. */
  escutando: boolean;
  /** Outra pergunta está gravando — o microfone é um só para a entrevista. */
  ocupado: boolean;
  onGravar: (id: string) => void;
  onPausar: () => void;
  onRetomar: () => void;
  onFinalizar: () => void;
  onConferir: (id: string, texto: string, forcar?: boolean) => void;
}) {
  const texto = typeof valor === "string" ? valor : "";

  if (pergunta.tipo === "sim_nao") {
    return (
      <div className={estilos.opcoes}>
        {["sim", "não"].map((o) => (
          <button
            key={o}
            type="button"
            className={`${estilos.opcao} ${o === "sim" ? estilos.opcaoSim : ""} ${
              texto === o ? estilos.opcaoAtiva : ""
            }`}
            onClick={() => onResponder(pergunta.id, texto === o ? "" : o)}
          >
            {o}
          </button>
        ))}
      </div>
    );
  }

  if (pergunta.tipo === "escolha") {
    return (
      <div className={estilos.opcoes}>
        {pergunta.opcoes.map((o) => (
          <button
            key={o}
            type="button"
            className={`${estilos.opcao} ${texto === o ? estilos.opcaoAtiva : ""}`}
            onClick={() => onResponder(pergunta.id, texto === o ? "" : o)}
          >
            {o}
          </button>
        ))}
      </div>
    );
  }

  if (pergunta.tipo === "lista") {
    return (
      <select
        className={estilos.seletor}
        value={texto}
        onChange={(e) => onResponder(pergunta.id, e.target.value)}
        aria-label={pergunta.texto}
      >
        <option value="">—</option>
        {pergunta.opcoes.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    );
  }

  if (pergunta.tipo === "documentos") {
    const marcados = Array.isArray(valor) ? valor : [];
    return (
      <div className={estilos.checks}>
        {pergunta.opcoes.map((o) => (
          <label key={o} className={estilos.check}>
            <input
              type="checkbox"
              checked={marcados.includes(o)}
              onChange={(e) =>
                onResponder(
                  pergunta.id,
                  e.target.checked ? [...marcados, o] : marcados.filter((x) => x !== o),
                )
              }
            />
            {o}
          </label>
        ))}
      </div>
    );
  }

  if (pergunta.busca === "cep") {
    return (
      <CampoCep
        pergunta={pergunta}
        valor={texto}
        valorAlvo={typeof valorAlvo === "string" ? valorAlvo : ""}
        onResponder={onResponder}
      />
    );
  }

  if (pergunta.validacao === "cpf") {
    /* O CPF é conferido aqui, não depois: o dígito verificador só serve para
     * pegar erro de digitação, e erro de digitação se corrige perguntando de
     * novo — o que só dá para fazer com o cliente ainda na frente. Descoberto
     * na conferência da papelada, meses depois, o mesmo aviso não vale nada. */
    const veredito = conferirCpf(texto);
    return (
      <>
        <input
          className={`${estilos.campo} ${veredito.valido === false ? estilos.campoInvalido : ""}`}
          type="text"
          inputMode="numeric"
          value={texto}
          maxLength={14}
          onChange={(e) => onResponder(pergunta.id, formatarCpf(e.target.value))}
          aria-invalid={veredito.valido === false}
          aria-describedby={veredito.mensagem ? `dv-${pergunta.id}` : undefined}
        />
        {veredito.mensagem && (
          <span
            id={`dv-${pergunta.id}`}
            className={
              veredito.valido === false
                ? estilos.campoErro
                : veredito.valido
                  ? estilos.campoOk
                  : estilos.campoDica
            }
            // O aviso muda a cada tecla; sem `polite` o leitor de tela leria
            // "faltam 7 dígitos, faltam 6 dígitos" por cima da digitação.
            aria-live="polite"
          >
            {veredito.mensagem}
          </span>
        )}
      </>
    );
  }

  if (pergunta.tipo === "dado" || pergunta.tipo === "data") {
    return (
      <input
        className={estilos.campo}
        type={pergunta.tipo === "data" ? "date" : "text"}
        value={texto}
        onChange={(e) => onResponder(pergunta.id, e.target.value)}
      />
    );
  }

  // relato — com gravador quando marcado, sempre editável por teclado.
  const emCurso = gravando || pausado;

  return (
    <>
      {/* Com o microfone aberto, os botões por pergunta somem.
        *
        * Era exatamente disso que o escritório reclamou: gravar/finalizar 86
        * vezes fazia o entrevistador administrar botões em vez de conversar. A
        * caixa de texto continua editável — o que a escuta preenche, a mão
        * corrige. */}
      {pergunta.transcrever && !escutando && (
        <div className={estilos.opcoes} style={{ marginBottom: 8 }}>
          {!emCurso && (
            <button
              type="button"
              className={transcricaoEstilos.botao}
              onClick={() => onGravar(pergunta.id)}
              disabled={!temMic || ocupado}
              title={
                !temMic
                  ? "Ligue o microfone no topo da tela"
                  : ocupado
                    ? "Outra pergunta está gravando — finalize aquela antes"
                    : ""
              }
            >
              {/* O rótulo muda porque a operação é a mesma mas a intenção não:
                * complementar é o que se faz depois de ler a conferência e
                * descobrir o que faltou perguntar. O trecho novo entra no fim
                * do que já estava escrito, sem apagar nada. */}
              {texto.trim() ? "Adicionar complemento" : "Gravar resposta"}
            </button>
          )}

          {emCurso && (
            <>
              <button
                type="button"
                className={transcricaoEstilos.secundario}
                onClick={pausado ? onRetomar : onPausar}
                // Depois de finalizar não há o que pausar: a captura já parou.
                // Desabilitar é o que faz o botão parar de mentir.
                disabled={finalizando}
              >
                {pausado ? "Retomar" : "Pausar"}
              </button>
              <button
                type="button"
                className={`${transcricaoEstilos.botao} ${
                  gravando && !finalizando ? transcricaoEstilos.gravando : ""
                }`}
                onClick={onFinalizar}
                disabled={finalizando}
              >
                {finalizando ? "Transcrevendo…" : "Finalizar resposta"}
              </button>
            </>
          )}

          {pausado && !finalizando && (
            <span className={estilos.pausa}>
              pausado — o que for dito agora não entra na resposta
            </span>
          )}

          {finalizando && (
            <span className={estilos.pausa}>
              transcrevendo a resposta inteira — o texto aparece em instantes
            </span>
          )}
        </div>
      )}

      <textarea
        className={estilos.area}
        value={gravando && parcial ? `${texto}${texto ? " " : ""}${parcial}` : texto}
        onChange={(e) => onResponder(pergunta.id, e.target.value)}
        /* Conferir ao sair do campo é o equivalente digitado de "finalizar
         * resposta". Fazê-lo a cada tecla custaria uma chamada ao modelo por
         * letra; num botão à parte, ninguém clicaria no meio da entrevista. */
        onBlur={(e) => {
          if (pergunta.transcrever && !emCurso) onConferir(pergunta.id, e.target.value);
        }}
        placeholder={
          pergunta.transcrever ? "Grave pelo microfone ou digite aqui." : "Digite a resposta."
        }
        readOnly={gravando}
      />
    </>
  );
}
