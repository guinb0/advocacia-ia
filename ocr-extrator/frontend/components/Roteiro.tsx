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

import { analisarResposta, consultarCep, obterRoteiro, processarEntrevista, recomendarEntrevista } from "@/lib/api";
import { conferirCpf, formatarCep, formatarCpf } from "@/lib/documentos";
import type {
  AnaliseResposta,
  Bloco,
  EnderecoCep,
  Pergunta,
  RecomendacaoEntrevista,
  RoteiroCompleto,
} from "@/lib/types";
import { CapturaEntrevista } from "@/lib/transcricao";
import type { EstadoCaptura } from "@/lib/transcricao";
import ConferenciaResposta from "./ConferenciaResposta";
import VideoDaEntrevista from "./VideoDaEntrevista";
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
export type FaseEntrevista = "preparacao" | "entrevista" | "processando" | "revisao";

/** O que a chamada, na coluna ao lado, precisa poder fazer com o roteiro. */
export interface ManipuladorRoteiro {
  /** Passa a transcrever a voz que chega pela chamada, no lugar do microfone. */
  usarFaixaDaChamada: (trilha: MediaStreamTrack) => Promise<void>;
  /** A chamada caiu: solta a fonte, para o gravador não prometer o que não tem. */
  aoPerderChamada: () => void;
  /** Há vídeo gravado e não baixado — fechar a tela agora o destrói. */
  temVideoPendente: () => boolean;
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

/** Tem valor? Mesmo critério de `escuta._respondida`, no backend. */
function respondida(valor: string | string[] | undefined): boolean {
  return Array.isArray(valor) ? valor.length > 0 : Boolean(String(valor ?? "").trim());
}

function formatarDuracao(totalSegundos: number): string {
  const horas = Math.floor(totalSegundos / 3600);
  const minutos = Math.floor((totalSegundos % 3600) / 60);
  const segundos = totalSegundos % 60;
  return [horas, minutos, segundos].map((n) => String(n).padStart(2, "0")).join(":");
}

interface Props {
  codigo?: string;
  /** Resultado pós-processamento e alterações feitas durante a revisão. */
  onRespostas?: (
    respostas: Respostas,
    relatoUnificado: string,
    entrevistaId: string,
  ) => void;
  onFase?: (fase: FaseEntrevista) => void;
  ref?: Ref<ManipuladorRoteiro>;
}

export default function Roteiro({
  codigo = "empregado_publico",
  onRespostas,
  onFase,
  ref,
}: Props) {
  const [roteiro, setRoteiro] = useState<RoteiroCompleto | null>(null);
  const [respostas, setRespostas] = useState<Respostas>({});
  const [fase, setFase] = useState<FaseEntrevista>("preparacao");
  const [transcricaoVisivel, setTranscricaoVisivel] = useState("");
  const [inicioEntrevista, setInicioEntrevista] = useState<number | null>(null);
  const [duracaoEntrevista, setDuracaoEntrevista] = useState(0);
  const [incertas, setIncertas] = useState<Array<{ pergunta_id: string; motivo: string }>>([]);
  const [erroProcessamento, setErroProcessamento] = useState<string | null>(null);
  const finalizarTranscricao = useRef<((texto: string) => void) | null>(null);
  const transcricaoConsolidada = useRef("");
  const [erro, setErro] = useState<string | null>(null);
  const [estadoMic, setEstadoMic] = useState<EstadoCaptura>("sem-audio");
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

  /* Vídeo gravado e ainda não baixado. Ao contrário do áudio, ele não está em
   * lugar nenhum além desta aba — concluir a entrevista o destrói. */
  const videoPendente = useRef(false);

  /* A conversa inteira, como o Whisper a devolveu, na ordem.
   *
   * Num ref e não em estado: cresce a cada frase de uma conversa de trinta
   * minutos, e nada na tela depende dela — ela é lida uma vez, no fim, para
   * virar arquivo. Em estado, cada trecho redesenharia o roteiro inteiro. */
  const transcricaoBruta = useRef<{ quando: number; texto: string }[]>([]);

  const captura = useRef<CapturaEntrevista | null>(null);
  // Espelho para os callbacks da captura, que são fixados na construção.
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

  const aoMudarFase = useRef(onFase);
  aoMudarFase.current = onFase;
  useEffect(() => {
    aoMudarFase.current?.(fase);
  }, [fase]);

  useEffect(() => {
    if (fase !== "entrevista" || inicioEntrevista === null) return;
    const atualizar = () => setDuracaoEntrevista(Math.floor((Date.now() - inicioEntrevista) / 1000));
    atualizar();
    const id = window.setInterval(atualizar, 1000);
    return () => window.clearInterval(id);
  }, [fase, inicioEntrevista]);

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

  if (captura.current === null && typeof window !== "undefined") {
    captura.current = new CapturaEntrevista({
      onParcial: (texto) => {
        // A primeira palavra transcrita já responde o que o aviso explicava.
        setAviso(null);
        setParcial(texto);
      },
      onAviso: setAviso,
      /* Um trecho estável entra somente no registro da conversa. */
      onTrecho: (texto) => {
        if (!texto.trim()) return;
        // Guardado ANTES de ir para a escuta: o arquivo bruto é o que foi dito,
        // não o que o modelo entendeu — inclusive o que ele descartou.
        transcricaoBruta.current.push({ quando: Date.now(), texto: texto.trim() });
        // Durante a conversa isto é somente registro. Nenhuma chamada à IA e
        // nenhuma alteração do formulário acontece antes da finalização.
        setTranscricaoVisivel((anterior) =>
          [anterior, texto.trim()].filter(Boolean).join(" "),
        );
      },
      onFinal: (texto) => {
        transcricaoConsolidada.current = texto.trim();
        if (texto.trim()) setTranscricaoVisivel(texto.trim());
        if (finalizarTranscricao.current) {
          finalizarTranscricao.current(texto.trim());
          finalizarTranscricao.current = null;
        }
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
        if (finalizarTranscricao.current) {
          finalizarTranscricao.current(
            transcricaoBruta.current.map((item) => item.texto).join(" "),
          );
          finalizarTranscricao.current = null;
        }
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
      transcricaoBruta: () =>
        transcricaoConsolidada.current
          ? [{
              quando: transcricaoBruta.current[0]?.quando ?? Date.now(),
              texto: transcricaoConsolidada.current,
            }]
          : [...transcricaoBruta.current],
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

  /** Abre uma única captura contínua para toda a entrevista. */
  const comecarEntrevista = useCallback(async () => {
    setErro(null);
    /* Some com o painel do áudio ANTES de voltar a gravar.
     *
     * Ele fecha a gravação do id que recebe: deixado na tela durante uma
     * entrevista nova, encerraria a conversa que acabou de começar. */
    try {
      if (!captura.current) throw new Error("A gravação ainda não está pronta.");
      if (estadoMic === "sem-audio") await captura.current.selecionarAudio();
      // O mesmo clique que abre a entrevista abre a sessão contínua no servidor:
      // não existe estado de entrevista em andamento sem gravação de áudio.
      await captura.current.iniciarEntrevista();
      if (fonteAtual.current !== "chamada") setFonte("microfone");
      setTranscricaoVisivel("");
      transcricaoConsolidada.current = "";
      transcricaoBruta.current = [];
      setInicioEntrevista(Date.now());
      setDuracaoEntrevista(0);
      setErroProcessamento(null);
      setFase("entrevista");
    } catch (e) {
      const m = e instanceof Error ? e.message : "Não foi possível abrir o microfone.";
      setErro(/NotAllowedError|denied/i.test(m) ? "Permissão de microfone negada." : m);
    }
  }, [estadoMic]);

  const finalizarEntrevista = useCallback(async () => {
    if (!captura.current || fase !== "entrevista") return;
    setFase("processando");
    setErroProcessamento(null);

    const transcricaoFinal = new Promise<string>((resolve) => {
      finalizarTranscricao.current = resolve;
      window.setTimeout(() => {
        if (!finalizarTranscricao.current) return;
        finalizarTranscricao.current = null;
        resolve(transcricaoBruta.current.map((item) => item.texto).join(" "));
      }, 60_000);
    });

    captura.current.finalizarResposta();
    await captura.current.aguardarEnvio();

    try {
      const texto = (await transcricaoFinal).trim() ||
        transcricaoBruta.current.map((item) => item.texto).join(" ");
      const [resultado] = await Promise.all([
        processarEntrevista(texto, respostasRef.current, codigo),
        captura.current.encerrarGravacao(),
      ]);
      respostasRef.current = resultado.respostas;
      setRespostas(resultado.respostas);
      setIncertas(resultado.incertas);
      setFase("revisao");
    } catch (e) {
      // Mesmo quando a IA falha, a entrevista e a transcrição continuam
      // disponíveis para revisão e preenchimento manual.
      await captura.current.encerrarGravacao().catch(() => undefined);
      setErroProcessamento(
        e instanceof Error
          ? e.message
          : "Não foi possível organizar a entrevista. A transcrição foi preservada.",
      );
      setFase("revisao");
    }
  }, [codigo, fase]);

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
    if (fase !== "revisao") return;
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
  }, [relatoConsolidado, lacunasObrigatorias, feitas, fase]);

  /* Publica resultados somente na revisão; durante a conversa o formulário
   * externo continua intocado. */
  const aoMudar = useRef(onRespostas);
  aoMudar.current = onRespostas;
  useEffect(() => {
    if (!aoMudar.current || fase !== "revisao") return;
    aoMudar.current(
      respostas,
      montarRelato(blocosVisiveis, respostas),
      captura.current?.entrevistaId ?? "",
    );
  }, [respostas, blocosVisiveis, fase]);

  if (erro && !roteiro) return <p className={estilos.vazio}>{erro}</p>;
  if (!roteiro) return <p className={estilos.vazio}>Carregando o roteiro…</p>;

  const temMic = estadoMic !== "sem-audio";

  return (
    <div className={estilos.tela}>
      {/* No TOPO e sem poder ser fechado: enquanto isto estiver na tela, o que
        * for falado não vira campo preenchido. É a única coisa que importa. */}
      {sessaoCaiu && (
        <div className={estilos.sessaoCaiu} role="alert">
          <strong>Sua sessão de acesso expirou.</strong>{" "}
          A gravação e a transcrição continuam registrando a conversa, mas será
          necessário entrar novamente para processar os resultados.
        </div>
      )}
      <div className={estilos.cabecalho}>
        <div>
          <h2 className={estilos.titulo}>{roteiro.nome}</h2>
          <span className={estilos.fonte}>
            {fase === "preparacao" && "Preparação"}
            {fase === "entrevista" && "Entrevista em andamento"}
            {fase === "processando" && "Entrevista finalizada — processando informações"}
            {fase === "revisao" && "Resultados para revisão"}
          </span>
        </div>
        <div className={transcricaoEstilos.acoes}>
          {fase === "preparacao" && fonte !== "chamada" && (
            <button
              type="button"
              className={transcricaoEstilos.secundario}
              onClick={ligarMicrofone}
            >
              {temMic ? "Trocar microfone" : "Ligar microfone"}
            </button>
          )}
          {fase === "entrevista" && (
            <span className={estilos.progresso}>{formatarDuracao(duracaoEntrevista)}</span>
          )}
          {fase === "revisao" && <span className={estilos.progresso}>{feitas}/{total}</span>}
        </div>
      </div>

      {fase === "revisao" && <div className={estilos.barra}>
        <i
          className={estilos.preenchimento}
          style={{ width: `${total ? (feitas / total) * 100 : 0}%` }}
        />
      </div>}

      {/* O vídeo fica aqui em cima porque gravar em vídeo se decide no começo
        * da conversa — e porque ele não é guardado em lugar nenhum, então quem
        * quiser precisa ver a opção antes, não depois. */}
      <VideoDaEntrevista
        permitirInicio={fase === "preparacao"}
        finalizar={fase === "processando" || fase === "revisao"}
        onPendente={(pendente) => {
          videoPendente.current = pendente;
        }}
      />

      {erro && <div className={transcricaoEstilos.erro}>{erro}</div>}
      {aviso && <p className={transcricaoEstilos.aviso} aria-live="polite">{aviso}</p>}

      {fase === "preparacao" && (
        <section className={estilos.etapaEntrevista}>
          <span className={estilos.blocoTitulo}>ANTES DE COMEÇAR</span>
          <p className={estilos.objetivo}>
            Identifique o cliente e confirme a fonte de áudio. Depois disso, a
            conversa será registrada sem preencher campos durante a entrevista.
          </p>
          <label className={estilos.campoPreparacao}>
            <span>Nome completo</span>
            <input
              className={estilos.campo}
              value={String(respostas.nome ?? "")}
              onChange={(e) => responder("nome", e.target.value)}
            />
          </label>
          <label className={estilos.campoPreparacao}>
            <span>CPF</span>
            <input
              className={estilos.campo}
              inputMode="numeric"
              value={String(respostas.cpf ?? "")}
              onChange={(e) => responder("cpf", formatarCpf(e.target.value))}
            />
          </label>
          <div className={estilos.inicioEntrevista}>
            <button
              type="button"
              className={transcricaoEstilos.botao}
              onClick={comecarEntrevista}
              disabled={faltaParaComecar.length > 0}
            >
              Iniciar entrevista
            </button>
            <span>
              {fonte === "chamada"
                ? "A voz do cliente na chamada será gravada e transcrita."
                : temMic
                  ? "Microfone pronto para gravar e transcrever a conversa."
                  : "O microfone será solicitado ao iniciar."}
            </span>
          </div>
          {faltaParaComecar.length > 0 && (
            <p className={transcricaoEstilos.aviso}>
              Informe {faltaParaComecar.join(" e ")} para iniciar.
            </p>
          )}
        </section>
      )}

      {fase === "entrevista" && (
        <section className={estilos.etapaEntrevista}>
          <div className={estilos.estadoEntrevista}>
            <span>
              <i className={estilos.indicadorGravando} />
              {estadoMic === "sem-audio" ? "Captura interrompida" : "Em andamento"}
            </span>
            <strong>{formatarDuracao(duracaoEntrevista)}</strong>
          </div>
          <p className={estilos.objetivo}>
            A conversa está sendo gravada e transcrita. O formulário será preparado
            somente depois da finalização.
          </p>
          <details className={estilos.transcricaoSessao} open>
            <summary>Transcrição da conversa</summary>
            <div className={transcricaoEstilos.transcricao} aria-live="polite">
              {[transcricaoVisivel, parcial].filter(Boolean).join(" ") || "Aguardando a conversa…"}
            </div>
          </details>
          <details className={estilos.guiaEntrevista}>
            <summary>Consultar roteiro de perguntas</summary>
            {roteiro.saudacao.length > 0 && (
              <section>
                <strong>Abertura</strong>
                {roteiro.saudacao.map((texto, indice) => <p key={indice}>{texto}</p>)}
              </section>
            )}
            {roteiro.blocos
              .filter((bloco) => !bloco.delegado_a)
              .map((bloco) => (
                <section key={bloco.id}>
                  <strong>{bloco.titulo}</strong>
                  <ol>
                    {bloco.perguntas.map((pergunta) => <li key={pergunta.id}>{pergunta.texto}</li>)}
                  </ol>
                </section>
              ))}
            {roteiro.encerramento.length > 0 && (
              <section>
                <strong>Encerramento</strong>
                {roteiro.encerramento.map((texto, indice) => <p key={indice}>{texto}</p>)}
              </section>
            )}
          </details>
          <button
            type="button"
            className={transcricaoEstilos.botao}
            onClick={() => void finalizarEntrevista()}
          >
            Finalizar entrevista
          </button>
        </section>
      )}

      {fase === "processando" && (
        <section className={estilos.processando} role="status" aria-live="polite">
          <i className={estilos.processandoIndicador} />
          <div>
            <strong>Entrevista finalizada — processando informações</strong>
            <p>Estamos organizando a conversa e preparando os resultados para revisão.</p>
          </div>
        </section>
      )}

      {fase === "revisao" && (
        <section className={estilos.revisaoTopo}>
          <span className={estilos.blocoTitulo}>REVISÃO DOS RESULTADOS</span>
          <p>Confira e ajuste os campos antes de continuar o atendimento jurídico.</p>
          {erroProcessamento && (
            <div className={transcricaoEstilos.erro}>{erroProcessamento}</div>
          )}
          {incertas.length > 0 && (
            <details>
              <summary>{incertas.length} informação(ões) deixada(s) em aberto por segurança</summary>
              <ul>{incertas.map((item) => <li key={item.pergunta_id}>{item.motivo}</li>)}</ul>
            </details>
          )}
          <details className={estilos.transcricaoSessao}>
            <summary>Transcrição completa da entrevista</summary>
            <div className={transcricaoEstilos.transcricao}>{transcricaoVisivel}</div>
          </details>
        </section>
      )}

      {fase === "revisao" && <div>

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

      <div>
        <div>
          {/* A pergunta da vez, grudada no alto da coluna do roteiro. Vem ANTES
            * das perguntas todas porque é o que se lê ao cliente; o que está
            * embaixo é o formulário que se preenche. Fica DENTRO da coluna, e
            * não por cima do painel: os dois grudam ao rolar, e um passaria por
            * cima do outro. Enquanto a escuta não abriu ela só aponta por onde
            * começar — sem relógio, porque não há entrevista para cobrar ainda. */}
          {blocosVisiveis.map((bloco) => (
            <BlocoRoteiro
              key={bloco.id}
              bloco={bloco}
              respostas={respostas}
              onResponder={responder}
              conferencias={conferencias}
              onConferir={conferir}
              rodape={undefined}
            />
          ))}
        </div>

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

      </div>}

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
  onResponder,
  conferencias,
  onConferir,
  rodape,
}: {
  bloco: Bloco;
  respostas: Respostas;
  onResponder: (id: string, valor: string | string[]) => void;
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
            </div>

            {p.dica && <span className={estilos.dica}>{p.dica}</span>}

            <div className={estilos.resposta}>
              <CampoResposta
                pergunta={p}
                valor={respostas[p.id]}
                valorAlvo={p.preenche ? respostas[p.preenche] : undefined}
                onResponder={onResponder}
                onConferir={onConferir}
              />
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
  onConferir,
}: {
  pergunta: Pergunta;
  valor?: string | string[];
  /** Resposta atual do campo que a busca preenche — para não sobrescrevê-la. */
  valorAlvo?: string | string[];
  onResponder: (id: string, valor: string | string[]) => void;
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

  return (
    <>
      <textarea
        className={estilos.area}
        value={texto}
        onChange={(e) => onResponder(pergunta.id, e.target.value)}
        /* Conferir ao sair do campo é o equivalente digitado de "finalizar
         * resposta". Fazê-lo a cada tecla custaria uma chamada ao modelo por
         * letra; num botão à parte, ninguém clicaria no meio da entrevista. */
        onBlur={(e) => {
          if (pergunta.transcrever) onConferir(pergunta.id, e.target.value);
        }}
        placeholder={
          pergunta.transcrever ? "Revise ou complete a resposta." : "Digite a resposta."
        }
      />
    </>
  );
}
