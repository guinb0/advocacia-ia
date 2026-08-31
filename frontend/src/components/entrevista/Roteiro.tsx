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

import { useSessao } from "@/lib/auth";
import { entrevistaDeTeste } from "@/lib/amostraEntrevista";
import { analisarResposta, baterAtendimentoDocumentacao, consultarCep, escutarTrecho, listarMunicipios, obterRoteiro, recomendarEntrevista, registrarAtendimentoDocumentacao } from "@/lib/api";
import type { MunicipioLocalidade } from "@/lib/api";
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
import AudioDaEntrevista from "@/components/entrevista/AudioDaEntrevista";
import Conducao from "@/components/entrevista/Conducao";
import ConferenciaResposta from "@/components/entrevista/ConferenciaResposta";
import VideoDaEntrevista from "@/components/entrevista/VideoDaEntrevista";
import RespostasDoRoteiro from "@/components/entrevista/RespostasDoRoteiro";
import EditorRoteiro from "@/components/entrevista/EditorRoteiro";
import SeletorDeRoteiro from "@/components/entrevista/SeletorDeRoteiro";

// TEMPORÁRIO — ambiente de testes sem consumo de transcrição/IA.
// Quando o usuário pedir para reativar, troque para `false` ou remova o desvio.
const TRANSCRICAO_TEMPORARIAMENTE_DESATIVADA = false;

const T_BOTAO =
  "border-[1.5px] border-tinta bg-transparent text-tinta text-[11px] font-semibold leading-none font-ui " +
  "tracking-[0.1em] uppercase px-[14px] py-[10px] cursor-pointer disabled:opacity-40 disabled:cursor-default " +
  "enabled:hover:bg-tinta enabled:hover:text-papel";
const T_BOTAO_GRAVANDO =
  "border-[1.5px] border-critico bg-transparent text-critico text-[11px] font-semibold leading-none font-ui " +
  "tracking-[0.1em] uppercase px-[14px] py-[10px] cursor-pointer disabled:opacity-40 disabled:cursor-default " +
  "enabled:hover:bg-critico enabled:hover:text-papel";
const T_SECUNDARIO =
  "border border-borda-forte bg-transparent text-tinta text-[10px] font-semibold leading-none font-ui " +
  "tracking-[0.08em] uppercase px-3 py-[9px] cursor-pointer enabled:hover:bg-papel-2";
const T_ERRO = "mt-3 border-[1.5px] border-critico text-critico p-[10px] font-normal text-[12px] leading-[1.5] font-ui";
const T_AVISO = "mt-[10px] mb-0 font-normal text-[11.5px] leading-[1.5] font-ui text-atencao";
const T_ACOES = "flex gap-[10px] items-center flex-wrap";

/* Bloco "vale abrir este caso?" — cartão de recomendação com veredito colorido
 * e a análise comparativa entre processos semelhantes. */
const RECOMENDACAO =
  "mt-4 mb-5 p-4 border border-borda bg-papel-2 font-normal text-[13px] leading-[1.55] font-ui";
const RECOMENDACAO_TOPO = "flex justify-between gap-3 text-tinta-3";
const VEREDITO_BASE = "inline-block mt-3 px-[9px] py-[5px] rounded-[3px] font-bold tracking-[0.03em]";
const VEREDITO_COR: Record<string, string> = {
  sim: "bg-ok-claro text-ok",
  com_ressalva: "bg-atencao-claro text-atencao",
  atencao: "bg-critico-claro text-critico",
};
const VEREDITO_INDEFINIDO = "bg-papel text-tinta-3";
const RESUMO_SUMMARY = "cursor-pointer font-semibold";
const RESUMO_LINK = "text-inherit underline";
const RESUMO_SMALL = "block mt-[10px] text-tinta-3";
/* Lista fora do escopo da comparativa (lacunas/precedentes): o reset antigo
 * zerava padding mas não list-style, então o marcador de disco ficava colado
 * na borda — reproduzido aqui de propósito, não é engano. */
const LISTA_BARE = "list-disc pl-0 m-0";
const COMPARATIVA = "mt-4 pt-3.5 border-t border-borda";
const COMPARATIVA_H4 = "m-0 mb-[6px] text-[15px]";
const COMPARATIVA_DETAILS = "mt-[10px] p-[10px_12px] bg-papel border border-borda [&[open]>summary]:mb-2";
const COMPARATIVA_LISTA = "m-0 pl-5";
const COMPARATIVA_ITEM = "[&+&]:mt-2";
const COMPARATIVA_SMALL = "block mt-[2px] text-tinta-3";

/** Botão de escolha (sim/não, lista curta). "sim" ativo vira verde; qualquer
 * outra opção ativa vira escuro — nunca os dois ao mesmo tempo. */
function classeOpcao(ativa: boolean, sim: boolean): string {
  const base =
    "border text-[10.5px] font-semibold leading-none font-ui tracking-[0.06em] uppercase px-3 py-2 cursor-pointer";
  if (!ativa) return `${base} border-borda-forte bg-transparent text-tinta hover:bg-papel-2`;
  return sim ? `${base} border-ok bg-ok text-papel` : `${base} border-tinta bg-tinta text-papel`;
}

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
const CAMPOS_TECNICOS_DIGITADOS = new Set([
  "nacionalidade", "nascimento", "estado_civil", "profissao", "rg", "rg_orgao",
  "rg_uf", "mae", "pai", "cep", "endereco", "telefone", "email", "pis",
]);
type TrechoAoVivo = { quando: number; texto: string; quem: "Entrevistador" | "Entrevistado" | "Falante não identificado" };

/* Tudo que o `PainelEscuta` ("A ENTREVISTA ATÉ AQUI") precisa para se desenhar.
 *
 * O painel deixou de morar ao lado do formulário: agora ele fica na coluna da
 * direita, embaixo do cartão CHAMADA (ver `EntrevistaComChamada`). Como o estado
 * que o alimenta nasce todo aqui dentro, o roteiro o publica para cima por
 * `onEscuta`, e quem o renderiza é a tela de fora. `onIrPara` viaja no pacote
 * porque é só `document.getElementById(...).scrollIntoView` — funciona de
 * qualquer lugar da página. */
export interface EstadoEscuta {
  transcricao: TrechoAoVivo[];
  parcial: string;
  preenchidas: CampoOuvido[];
  aConferir: number;
  lembretes: Lembrete[];
  faltando: PerguntaPendente[];
  interpretando: boolean;
  captando: boolean;
  pausado: boolean;
  ultimaFala: number | null;
  ultimoSom: number | null;
  nivelTipico: number | null;
  chegada: number | null;
  erro: string | null;
  onIrPara: (perguntaId: string) => void;
}

function palavras(texto: string): string[] {
  return texto.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().match(/[a-z0-9]+/g) ?? [];
}

function inferirFalante(
  texto: string,
  fonte: Fonte,
  roteiro: RoteiroCompleto | null,
  perguntaAtual: string,
  anterior: TrechoAoVivo["quem"] | null,
): TrechoAoVivo["quem"] {
  // Faixa remota do Jitsi: só a voz do outro lado chega. Sem heurística.
  if (fonte === "chamada") return "Entrevistado";
  const limpo = texto.trim();
  const normalizado = palavras(limpo).join(" ");

  /* Quem CONDUZ também fala em primeira pessoa ("meu nome é… da equipe de
   * acolhimento"). Se o "eu/meu" rodar antes, a saudação inteira vira
   * "Entrevistado" — e foi exatamente o que aconteceu na sessão com o
   * Guilherme. Estes padrões vêm ANTES do first-person de propósito. */
  if (
    /\b(equipe de acolhimento|sou da equipe|aqui da|lara.?melo|lari melo|vamos comecar|vamos iniciar|gostariamos|entrevista integra|confianca depositada|posso lhe|peco apenas|roteiro de acolhimento)\b/.test(
      normalizado,
    ) ||
    /\b(qual (que )?e (o |a )?(seu|sua)|como e (que e )?(o |a )?(seu|sua)|voce e |o senhor|a senhora|me diga|conte (me|pra mim))\b/.test(
      normalizado,
    )
  ) {
    return "Entrevistador";
  }

  if (/^(sim|nao|isso|exato|exatamente|correto|aham|uhum|nunca|claro)$/.test(normalizado)) {
    return "Entrevistado";
  }
  if (/\b(eu|meu|minha|comigo|trabalhei|trabalhava|sofri|recebi|ganhava|fui|tive)\b/.test(normalizado)) {
    return "Entrevistado";
  }
  const pergunta = roteiro?.blocos.flatMap((b) => b.perguntas).find((p) => p.id === perguntaAtual);
  if (limpo.endsWith("?")) return "Entrevistador";
  if (pergunta) {
    const ditas = palavras(limpo);
    const roteiroPalavras = new Set(palavras(pergunta.texto));
    if (ditas.length >= 4 && ditas.filter((p) => roteiroPalavras.has(p)).length / ditas.length >= 0.6) {
      return "Entrevistador";
    }
  }
  // Sobreposição com a saudação do roteiro — a abertura quase sempre é lida
  // em voz alta pelo atendente, e não tem "?" no fim.
  if (roteiro?.saudacao?.length) {
    const ditas = palavras(limpo);
    const saudacao = new Set(palavras(roteiro.saudacao.join(" ")));
    if (ditas.length >= 6 && ditas.filter((p) => saudacao.has(p)).length / ditas.length >= 0.45) {
      return "Entrevistador";
    }
  }
  if (anterior === "Entrevistador") return "Entrevistado";
  return "Falante não identificado";
}

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
  /** Volta da revisão ao ponto exato do roteiro que precisa de complemento. */
  irParaPergunta: (perguntaId: string) => void;
  /** Aplica ao roteiro as respostas consolidadas pela revisão final. */
  atualizarRespostas: (respostas: Record<string, string | string[]>) => void;
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

/* Quanto tempo a condução SEGURA uma pergunta que já foi respondida, enquanto
 * o cliente continua falando dela.
 *
 * O primeiro trecho que a escuta devolve já preenche o campo — e campo cheio
 * fazia a barra pular para a pergunta seguinte no meio da frase do cliente. O
 * entrevistador lia a próxima e cortava o raciocínio dele, que é o oposto do
 * que a condução existe para fazer: conduzir não é atropelar.
 *
 * A contagem reinicia a cada trecho novo que cai NESTA pergunta. Enquanto ele
 * desenvolve, a barra não anda; parou de cair trecho aqui (ele terminou, ou
 * mudou de assunto), ela anda. */
const SEGUNDOS_RESPOSTA_OBJETIVA = 1.5;
const SEGUNDOS_RESPOSTA_CURTA = 2.5;
const SEGUNDOS_RESPOSTA_LONGA = 5;

/* Teto do quanto uma pergunta pode ficar segurada, contado do PRIMEIRO trecho.
 *
 * A espera acima reinicia a cada trecho que cai nesta pergunta — e esse reinício
 * não tinha limite. Com áudio ruim os trechos pingam de cinco em cinco segundos
 * (às vezes só um fragmento mal reconhecido), cada um empurra o relógio de novo,
 * e a condução trava em "respondendo — deixe terminar" sem nunca liberar. Foi o
 * que aconteceu no "Foi vítima de assalto durante o trabalho?", uma pergunta de
 * sim ou não.
 *
 * 40s é generoso para quem está mesmo desenvolvendo uma resposta e curto o
 * bastante para não travar as 42 perguntas. Passado o teto a barra anda; o
 * cliente não é interrompido, porque a escuta continua atribuindo o que ele
 * disser à pergunta certa mesmo depois de a tela ter avançado. */
const MAXIMO_SEGURANDO_S = 40;

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
  /** O estado do painel "A ENTREVISTA ATÉ AQUI", para a tela de fora desenhá-lo
   *  na coluna da chamada. `null` enquanto a escuta não abriu (ou ao desmontar). */
  onEscuta?: (estado: EstadoEscuta | null) => void;
  ref?: Ref<ManipuladorRoteiro>;
}

export default function Roteiro({
  codigo = "empregado_publico",
  onRespostas,
  onEscuta,
  ref,
}: Props) {
  const [roteiro, setRoteiro] = useState<RoteiroCompleto | null>(null);
  /* O roteiro é editável no meio do atendimento. Só isto vive aqui em cima: o
   * painel de edição é um componente à parte, e o que ele devolve substitui o
   * `roteiro` desta sessão. As RESPOSTAS não são tocadas — elas são guardadas
   * por id de pergunta, e reescrever um enunciado não muda o id. */
  const [editandoRoteiro, setEditandoRoteiro] = useState(false);
  /* Escolher OUTRO roteiro do catálogo — o caso comum do botão "Alterar
   * roteiro". Editar o atual virou ação secundária dentro do seletor. */
  const [trocandoRoteiro, setTrocandoRoteiro] = useState(false);
  /* De qual arquivo veio o roteiro em edição, quando veio de um. Sobe junto ao
   * salvar para o catálogo registrar a procedência. */
  const [origemRoteiro, setOrigemRoteiro] = useState("");
  const [respostas, setRespostas] = useState<Respostas>({});
  const [erro, setErro] = useState<string | null>(null);
  /* Perguntas que saíram da vez sem resposta — o cliente não sabia, não quis,
   * ou o assunto não estava maduro. Não somem do roteiro: continuam pendentes
   * na lista e voltam à condução com um clique. É o que impede a sequência de
   * travar numa pergunta impossível com a cobrança tocando sem saída. */
  const [puladas, setPuladas] = useState<string[]>([]);
  /* A pergunta que ainda está recebendo resposta, e quando caiu o último
   * trecho dela. É o que segura a condução enquanto o cliente desenvolve. */
  const [respondendoAgora, setRespondendoAgora] = useState<{
    id: string;
    /** Último trecho que caiu nesta pergunta — reinicia a espera adaptativa. */
    em: number;
    /** PRIMEIRO trecho desta pergunta — é o que o teto mede, e por isso não
     *  pode ser reiniciado junto com `em`. */
    desde: number;
  } | null>(null);
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
  const [transcricaoVisivel, setTranscricaoVisivel] = useState<TrechoAoVivo[]>([]);
  const [municipios, setMunicipios] = useState<MunicipioLocalidade[]>([]);
  const [carregandoMunicipios, setCarregandoMunicipios] = useState(false);
  const [aviso, setAviso] = useState<string | null>(null);
  const [fonte, setFonte] = useState<Fonte>("nenhuma");
  // Lido dentro de callbacks fixados na construção, que não enxergam o estado.
  const fonteAtual = useRef<Fonte>("nenhuma");
  fonteAtual.current = fonte;

  const [conferencias, setConferencias] = useState<Record<string, EstadoConferencia>>({});
  const [recomendacaoCaso, setRecomendacaoCaso] = useState<RecomendacaoEntrevista | null>(null);
  const [erroRecomendacao, setErroRecomendacao] = useState<string | null>(null);
  const [atualizandoRecomendacao, setAtualizandoRecomendacao] = useState(false);
  const ultimoRelatoRecomendado = useRef("");

  /* A escuta chegou ao fim e o áudio pode ser oferecido. Quem grava é o
   * servidor, do mesmo PCM que alimenta a transcrição — ver `app/gravacao.py` e
   * `AudioDaEntrevista`, que cuida da conversão e do download. */
  const [escutaEncerrada, setEscutaEncerrada] = useState(false);
  /* A revisão da entrevista já rodou lá de fora.
   *
   * Vale como fim da conversa para efeito de tela: é quando as respostas
   * consolidadas chegam e quem conduz passa a querer VER o formulário para
   * completar o que faltou. Sem isto, o "ir ao campo" do painel de revisão
   * apontaria para uma pergunta que não está renderizada. */
  const [revisada, setRevisada] = useState(false);
  /* Vídeo gravado e ainda não baixado. Ao contrário do áudio, ele não está em
   * lugar nenhum além desta aba — concluir a entrevista o destrói. */
  const videoPendente = useRef(false);
  const irParaRef = useRef<(perguntaId: string) => void>(() => undefined);

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
  /* O bloco de identificação (nome, CPF, UF, município) vira um cabeçalho
   * recolhível assim que os quatro campos ficam válidos — o entrevistador
   * raramente volta a eles, e aberto empurram o roteiro para baixo. Recolhe
   * sozinho UMA vez (via `idRecolheuAuto`); reabrir e voltar a recolher fica a
   * cargo do usuário. Se um campo volta a ficar inválido, reabre e rearma. */
  const [idExpandida, setIdExpandida] = useState(true);
  const idRecolheuAuto = useRef(false);
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
  const ultimoFalante = useRef<TrechoAoVivo["quem"] | null>(null);

  const captura = useRef<CapturaEntrevista | null>(null);
  const inicioAutomatico = useRef(false);
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

  /* A interpretação por trecho foi removida do caminho ao vivo.
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

        const r = await escutarTrecho(
          trecho,
          respostasRef.current,
          roteiroRef.current?.codigo ?? codigo,
          atualRef.current,
        );
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
          /* Caiu trecho NA pergunta da vez: ele está respondendo ESTA, e a
           * condução espera ele terminar. Cair em outra pergunta não segura
           * nada — é resposta adiantada, e adiantar é justamente o que faz a
           * entrevista encurtar. */
          if (r.preenchidas.some((p) => p.pergunta_id === atualRef.current)) {
            setRespondendoAgora((anterior) => {
              const agora = Date.now();
              // Só preserva o `desde` se ainda for a MESMA pergunta; trocou de
              // pergunta, o teto recomeça, senão a segunda herdaria o relógio
              // gasto pela primeira e nem chegaria a segurar.
              return anterior && anterior.id === atualRef.current
                ? { ...anterior, em: agora }
                : { id: atualRef.current, em: agora, desde: agora };
            });
          }
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
  }, [codigo]);

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
        const trecho = { quando: Date.now(), texto: texto.trim() };
        transcricaoBruta.current.push(trecho);
        const quem = inferirFalante(
          texto,
          fonteAtual.current,
          roteiroRef.current,
          atualRef.current,
          ultimoFalante.current,
        );
        ultimoFalante.current = quem;
        setTranscricaoVisivel((atuais) => [...atuais, { ...trecho, quem }].slice(-60));
        /* Trecho do entrevistador (leitura do roteiro / saudação) não vai para
         * a escuta: o modelo já confunde pergunta com resposta, e mandar a
         * fala de quem conduz piora. Na faixa da chamada tudo é Entrevistado. */
        if (quem === "Entrevistador") return;
        filaTrechos.current.push(texto.trim());
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
        // Ref na hora: `setFonte` é assíncrono e o `comecarEntrevista` pode
        // rodar no mesmo ciclo ainda vendo "nenhuma"/"microfone".
        fonteAtual.current = "chamada";
        setFonte("chamada");
        setErro(null);
      },
      aoPerderChamada: () => {
        // Só solta se a fonte era a chamada: quem estava no microfone continua
        // no microfone, mesmo que a chamada do lado tenha caído. `soltarFonte`
        // preserva a sessão do Whisper — `encerrar()` matava a transcrição.
        if (fonteAtual.current === "chamada") {
          captura.current?.soltarFonte();
          setFonte("nenhuma");
        }
      },
      temVideoPendente: () => videoPendente.current,
      sugestoesPendentes: () => sugestoesRef.current.length,
      irParaPergunta: (perguntaId: string) => irParaRef.current(perguntaId),
      atualizarRespostas: (novas) => {
        setRespostas((atuais) => ({ ...atuais, ...novas }));
        // A revisão rodou: o roteiro aparece para completar o que faltou.
        setRevisada(true);
      },
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
    if (TRANSCRICAO_TEMPORARIAMENTE_DESATIVADA) {
      // Abre o roteiro completo sem microfone, WebSocket ou sessão do Whisper.
      setEscutando(true);
      setFonte("nenhuma");
      return;
    }
    try {
      // Se a faixa da chamada já chegou (`usarFaixaDaChamada`), não abre o
      // microfone da sala por cima — misturaria a voz do atendente na
      // transcrição. Só pede getUserMedia quando ainda não há fonte.
      if (!captura.current?.temAudio) await captura.current?.selecionarAudio();
      await captura.current?.iniciarEntrevista();
      emGravacao.current = null;
      setEscutando(true);
      // Preserva "chamada" se a trilha remota já estava montada.
      if (fonteAtual.current !== "chamada") setFonte("microfone");
      const entrevistaId = captura.current?.entrevistaId ?? "";
      if (entrevistaId) {
        void registrarAtendimentoDocumentacao(entrevistaId, String(respostasRef.current.nome ?? ""))
          .catch(() => undefined);
      }
      // Fila limpa no início: trechos da sessão anterior não contaminam esta.
      filaTrechos.current = [];
    } catch (e) {
      const m = e instanceof Error ? e.message : "Não foi possível abrir o microfone.";
      setErro(/NotAllowedError|denied/i.test(m) ? "Permissão de microfone negada." : m);
    }
  }, []);

  useEffect(() => {
    if (!escutando) return;
    const entrevistaId = captura.current?.entrevistaId ?? "";
    if (!entrevistaId) return;
    const id = window.setInterval(() => {
      void baterAtendimentoDocumentacao(entrevistaId).catch(() => undefined);
    }, 30_000);
    return () => window.clearInterval(id);
  }, [escutando]);

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
    setRespostas((r) => id === "uf" && r.uf !== valor
      ? { ...r, uf: valor, municipio: "" }
      : { ...r, [id]: valor });
  }, []);
  irParaRef.current = irPara;

  /* Publica o estado da escuta para a tela de fora desenhar o painel "A
   * ENTREVISTA ATÉ AQUI" na coluna da chamada. Em ref para o callback poder ser
   * inline no pai (novo a cada render) sem re-disparar este efeito. */
  const publicarEscuta = useRef(onEscuta);
  publicarEscuta.current = onEscuta;
  useEffect(() => {
    if (!publicarEscuta.current) return;
    if (!escutando) {
      publicarEscuta.current(null);
      return;
    }
    publicarEscuta.current({
      transcricao: transcricaoVisivel,
      parcial,
      preenchidas: ouvidas,
      aConferir: sugestoes.length,
      lembretes,
      faltando,
      interpretando: ouvindo,
      captando: escutando && estadoMic !== "sem-audio",
      pausado: estadoMic === "pausado",
      ultimaFala,
      ultimoSom,
      nivelTipico,
      chegada,
      erro: erroEscuta,
      onIrPara: irPara,
    });
  }, [
    escutando, transcricaoVisivel, parcial, ouvidas, sugestoes, lembretes,
    faltando, ouvindo, estadoMic, ultimaFala, ultimoSom, nivelTipico, chegada,
    erroEscuta, irPara,
  ]);
  useEffect(() => () => publicarEscuta.current?.(null), []);

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
        .flatMap((b) =>
          b.perguntas
            .filter((pergunta) => dependenciaAberta(pergunta, respostas))
            .map((pergunta) => ({ pergunta, bloco: b.titulo })),
        ),
    [blocosVisiveis, respostas],
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

  /* O relógio de parede desta tela.
   *
   * Sem ele o "segurar" nunca expiraria sozinho: a barra só recalcularia na
   * próxima resposta, e a pergunta respondida ficaria na tela até o cliente
   * falar de novo — o defeito oposto ao que este código conserta. */
  const [, tique] = useState(0);
  useEffect(() => {
    if (!escutando) return;
    const t = setInterval(() => tique((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, [escutando]);

  /* A pergunta segurada: já respondida, mas ainda recebendo trecho.
   *
   * Uma escolha/sim-não anda quase imediatamente. Relato curto (como "ainda
   * trabalho lá") ganha só 2,5s; narrativa longa ganha 5s para não cortar o
   * cliente. O antigo valor fixo de 8s fazia respostas objetivas parecerem
   * travadas mesmo depois de o texto já estar preenchido. */
  const indiceRespondendo = respondendoAgora === null
    ? -1
    : sequencia.findIndex(({ pergunta }) => pergunta.id === respondendoAgora.id);
  const perguntaRespondendo = indiceRespondendo >= 0 ? sequencia[indiceRespondendo].pergunta : null;
  const valorRespondendo = perguntaRespondendo ? respostas[perguntaRespondendo.id] : undefined;
  const tamanhoRespondendo = Array.isArray(valorRespondendo)
    ? valorRespondendo.join(" ").length
    : String(valorRespondendo ?? "").trim().length;
  const segundosParaAndar = perguntaRespondendo?.tipo !== "relato"
    ? SEGUNDOS_RESPOSTA_OBJETIVA
    : tamanhoRespondendo < 160
      ? SEGUNDOS_RESPOSTA_CURTA
      : SEGUNDOS_RESPOSTA_LONGA;
  const posicaoSegurada =
    respondendoAgora !== null &&
    Date.now() - respondendoAgora.em < segundosParaAndar * 1000 &&
    Date.now() - respondendoAgora.desde < MAXIMO_SEGURANDO_S * 1000
      ? indiceRespondendo
      : -1;

  const posicaoAtual = posicaoSegurada >= 0 ? posicaoSegurada : posicaoNatural;
  const atual = posicaoAtual >= 0 ? sequencia[posicaoAtual] : null;
  atualRef.current = atual?.pergunta.id ?? "";
  /** O cliente está desenvolvendo a resposta desta pergunta agora mesmo. */
  const respondendo = posicaoSegurada >= 0;
  /** A entrevista anda: caiu resposta em ALGUMA pergunta há pouco. */
  const fluindo =
    ultimoPreenchimento !== null &&
    Date.now() - ultimoPreenchimento < SEGUNDOS_FLUINDO * 1000;

/** Troca os marcadores do roteiro pelos nomes de verdade.
 *
 * O roteiro do escritório é escrito com lacunas — "Sr.(a) [Nome], concluímos a
 * nossa entrevista" — e quem lê em voz alta preenchia de cabeça. Duas coisas
 * saíam disso: a pausa de quem lembra o nome no meio da frase, e a leitura
 * literal do colchete, que acontece quando se está lendo rápido com o cliente
 * na frente.
 *
 * A troca é só de exibição. O roteiro guardado continua com os marcadores: ele
 * é o mesmo para todos os atendimentos, e é dele que sai a auditoria de
 * condução (`app/auditoria.py`), que compara o que foi dito com o texto padrão.
 *
 * Marcador sem valor fica como está. Um "Sr.(a) , concluímos" seria pior que o
 * colchete — o colchete quem lê entende e contorna; a vírgula solta ele lê.
 */
function preencherMarcadores(
  texto: string,
  nomeCliente: string,
  nomeAtendente: string,
): string {
  const trocar = (alvo: RegExp, valor: string) =>
    valor.trim() ? (t: string) => t.replace(alvo, valor.trim()) : (t: string) => t;

  // `[Nome da Atendente]` PRIMEIRO: ele contém "Nome", e trocar `[Nome]` antes
  // deixaria "[Fulano da Atendente]" na tela.
  return [
    trocar(/\[\s*nome\s+d[ao]\s+atendente\s*\]/gi, nomeAtendente),
    trocar(/\[\s*nome\s*\]/gi, nomeCliente),
  ].reduce((t, f) => f(t), texto);
}

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
  /* OS CAMPOS DA IDENTIFICAÇÃO, EM UM LUGAR SÓ — e a duplicação já custou caro.
   *
   * Esta lista era escrita duas vezes: aqui, para saber o que falta antes de
   * começar, e lá embaixo, para filtrar o que a tela inicial desenha. Quando o
   * `estado_civil` entrou no roteiro, só a primeira foi atualizada — e a
   * entrevista parou de abrir. O campo era exigido para prosseguir e não era
   * desenhado em lugar nenhum: quem atendia respondia os quatro visíveis e nada
   * acontecia, sem nada na tela explicando o que faltava.
   *
   * Com uma lista só, acrescentar campo é mexer num lugar. A ordem aqui é a
   * ordem em que eles aparecem. */
  /* O que a tela desenha E o que ela exige saem DAQUI — uma lista só.
   *
   * UF e município entram pelo mesmo motivo do nome e do CPF: são o recorte que
   * a jurimetria usa para comparar o caso, e ouvi-los no meio do relato erra com
   * frequência — "Pará" e "Paraná" soam quase igual em fala corrida.
   *
   * O rótulo mora junto do id porque o botão "ir ao campo" precisa dos dois, e
   * `completo` existe pelo CPF, que não basta estar preenchido: precisa ter
   * dígito verificador válido. A ordem aqui é a ordem em que eles aparecem. */
  const CAMPOS_DA_IDENTIFICACAO = useMemo(
    () =>
      [
        { id: "nome", rotulo: "o nome completo" },
        {
          id: "cpf",
          rotulo: "um CPF válido",
          completo: (v: string | string[] | undefined) =>
            conferirCpf(String(v ?? "")).valido === true,
        },
        { id: "estado_civil", rotulo: "o estado civil" },
        { id: "uf", rotulo: "a UF" },
        { id: "municipio", rotulo: "o município" },
      ] as const,
    [],
  );

  const idsDaIdentificacao = useMemo(
    () => new Set<string>(CAMPOS_DA_IDENTIFICACAO.map((c) => c.id)),
    [CAMPOS_DA_IDENTIFICACAO],
  );

  const faltaParaComecar = useMemo(
    () =>
      CAMPOS_DA_IDENTIFICACAO.filter((campo) =>
        "completo" in campo && campo.completo
          ? !campo.completo(respostas[campo.id])
          : !respondida(respostas[campo.id]),
      ).map(({ id, rotulo }) => ({ id, rotulo })),
    [CAMPOS_DA_IDENTIFICACAO, respostas],
  );

  const rotulosPendentes = useMemo(
    () => faltaParaComecar.map((c) => c.rotulo),
    [faltaParaComecar],
  );

  /* Recolhe a identificação sozinho quando os quatro campos ficam válidos, e
   * uma vez só. Volta a abrir (e rearma) se algum deles perde a validade — aí o
   * entrevistador precisa vê-lo para corrigir. */
  useEffect(() => {
    if (faltaParaComecar.length === 0) {
      if (!idRecolheuAuto.current) {
        idRecolheuAuto.current = true;
        setIdExpandida(false);
      }
    } else {
      idRecolheuAuto.current = false;
      setIdExpandida(true);
    }
  }, [faltaParaComecar]);

  /* Só começa a transcrever DEPOIS da identificação (nome/CPF/UF/município).
   *
   * Antes, o auto-start no carregamento do roteiro abria o microfone da sala
   * enquanto o atendente lia a saudação — e essa fala ia para a transcrição
   * rotulada como "Entrevistado". Com a chamada, o cliente ainda nem entrou.
   * Esperar a identificação dá tempo de abrir o Jitsi e receber a faixa remota. */
  useEffect(() => {
    if (!roteiro || inicioAutomatico.current) return;
    if (faltaParaComecar.length > 0) return;
    inicioAutomatico.current = true;
    void comecarEntrevista();
  }, [roteiro, comecarEntrevista, faltaParaComecar.length]);

  /* Os nomes que preenchem os marcadores do roteiro.
   *
   * O do cliente sai do campo que já é obrigatório para iniciar; o de quem
   * conduz, da sessão. Com a autenticação desligada a sessão vem vazia, e aí o
   * marcador fica como está — ver `preencherMarcadores`. */
  const sessao = useSessao();

  /* Memorizado pelos dois nomes: o roteiro é reescrito a cada render, e refazer
   * a substituição em 19 parágrafos a cada tecla digitada seria trabalho à toa. */
  const comNomes = useCallback(
    (texto: string) => preencherMarcadores(texto, String(respostas.nome ?? ""), sessao.nome),
    [respostas.nome, sessao.nome],
  );

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
  // A síntese jurídica passou para o encerramento unificado. Não há mais uma
  // consulta concorrente a cada resposta provisória.

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

  const ufSelecionada = String(respostas.uf ?? "");
  useEffect(() => {
    let cancelado = false;
    if (!ufSelecionada) {
      setMunicipios([]);
      return;
    }
    setCarregandoMunicipios(true);
    listarMunicipios(ufSelecionada)
      .then((lista) => { if (!cancelado) setMunicipios(lista); })
      .catch(() => { if (!cancelado) setMunicipios([]); })
      .finally(() => { if (!cancelado) setCarregandoMunicipios(false); });
    return () => { cancelado = true; };
  }, [ufSelecionada]);

  if (erro && !roteiro)
    return <p className="italic font-normal text-[12px] leading-[1.5] font-titulo text-tinta-3">{erro}</p>;
  if (!roteiro)
    return (
      <p className="italic font-normal text-[12px] leading-[1.5] font-titulo text-tinta-3">
        Carregando o roteiro…
      </p>
    );

  const temMic = estadoMic !== "sem-audio";
  const identificacaoConcluida = faltaParaComecar.length === 0;
  /* DURANTE A CONVERSA A TELA É SÓ O TOPO. O formulário vem depois.
   *
   * Enquanto a escuta corre, o que fica na tela é o que quem conduz usa
   * falando com o cliente: a saudação para ler, os quatro campos da
   * identificação e o painel da escuta. As oitenta e seis perguntas do roteiro
   * NÃO aparecem — elas se preenchem sozinhas atrás da conversa, e enfileiradas
   * na tela só empurravam a saudação e a condução para fora do campo de visão.
   *
   * Ao terminar, o roteiro inteiro aparece de uma vez, já com o que a escuta
   * transpôs: aí conferir é o trabalho, e é a hora de ver todos os campos.
   *
   * "Terminar" é qualquer um dos dois, e os dois contam: encerrar a escuta, ou
   * a revisão da entrevista ter rodado lá de fora — quem clicou em "Revisar"
   * quer completar o que faltou, e o "ir ao campo" precisa achar o campo.
   *
   * A trava do microfone não mudou: a transcrição continua começando só depois
   * de nome, CPF, UF e município (ver o auto-início, acima). */
  const roteiroRevelado = escutaEncerrada || revisada;
  const blocosNaTela = roteiroRevelado
    ? (roteiro?.blocos ?? [])
    : blocosVisiveis
        .map((bloco) => ({
          ...bloco,
          perguntas: bloco.perguntas.filter((p) => idsDaIdentificacao.has(p.id)),
        }))
        .filter((bloco) => bloco.perguntas.length > 0);

  /* Com a identificação concluída e a escuta aberta, o bloco "abertura" sai da
   * lista corrida e passa a viver dentro do cabeçalho recolhível, logo acima
   * dela. Nos outros estados ele é um bloco como os demais. */
  const acordeaoIdentificacao = escutando && identificacaoConcluida;
  const aberturaBloco = acordeaoIdentificacao
    ? blocosNaTela.find((b) => b.id === "abertura") ?? null
    : null;
  const blocosNoCorpo = acordeaoIdentificacao
    ? blocosNaTela.filter((b) => b.id !== "abertura")
    : blocosNaTela;
  const resumoIdentificacao = [
    String(respostas.nome ?? "").trim(),
    formatarCpf(String(respostas.cpf ?? "")),
    [String(respostas.municipio ?? "").trim(), String(respostas.uf ?? "").trim()]
      .filter(Boolean)
      .join("/"),
  ]
    .filter(Boolean)
    .join("  ·  ");

  return (
    <div id="roteiro-da-entrevista" className="max-w-[860px] roteiro-contentor">
      {trocandoRoteiro && (
        <SeletorDeRoteiro
          atualCodigo={roteiro.codigo}
          /* Troca o roteiro da sessão pelo escolhido. As respostas não são
             tocadas: ficam guardadas por id de pergunta e reaparecem se o id
             existir no novo roteiro. */
          aoEscolher={(novo, origem) => {
            setRoteiro(novo);
            setOrigemRoteiro(origem);
          }}
          /* A antiga função do botão continua a um clique: consertar uma
             pergunta para ESTE cliente sem trocar de roteiro. */
          aoEditarAtual={() => {
            setTrocandoRoteiro(false);
            setEditandoRoteiro(true);
          }}
          aoFechar={() => setTrocandoRoteiro(false)}
        />
      )}

      {editandoRoteiro && (
        <EditorRoteiro
          roteiro={roteiro}
          origem={origemRoteiro}
          /* Vale só para esta sessão: nada é gravado, e o próximo atendimento
             volta ao roteiro do catálogo. */
          aoUsar={setRoteiro}
          /* Gravado: o servidor devolve a versão canônica já validada, que é a
             que passa a valer aqui também — assim a tela não fica com um
             rascunho que o backend normalizou de outro jeito. */
          aoSalvar={setRoteiro}
          aoFechar={() => setEditandoRoteiro(false)}
        />
      )}

      {TRANSCRICAO_TEMPORARIAMENTE_DESATIVADA && (
        <div className="mb-4 border-l-4 border-atencao bg-papel-2 px-3 py-[10px] text-[12px] leading-[1.5] font-ui text-tinta">
          <strong>Modo de teste:</strong> transcrição temporariamente desativada. Nenhum áudio é enviado ao serviço de transcrição.
        </div>
      )}
      <div className="flex justify-between items-end gap-4 flex-wrap pb-3 border-b border-borda-forte">
        <div>
          <h2 className="m-0 font-semibold text-[22px] leading-[1.15] font-titulo">{roteiro.nome}</h2>
        </div>
        <div className={T_ACOES}>
          {/* Fica ao lado do título, disponível o atendimento inteiro.
              A pergunta que não serve para este cliente, a que faltou, a opção
              que ninguém listou — tudo isso aparece com o cliente na linha, e
              até aqui a saída era anotar à parte e consertar o código depois.
              Editar não interrompe a entrevista: as respostas são guardadas por
              id de pergunta e continuam intactas atrás do painel. */}
          <button
            type="button"
            className={T_SECUNDARIO}
            onClick={() => setTrocandoRoteiro(true)}
            title="Escolher outro roteiro do catálogo para este atendimento"
          >
            Alterar roteiro
          </button>
          {/* O botão que abre a entrevista inteira. Substitui os 86 ciclos de
              gravar/finalizar: daqui em diante o microfone fica aberto e o
              roteiro se preenche atrás da conversa. */}
          {false && !escutando ? (
            <button
              type="button"
              className={T_BOTAO}
              onClick={comecarEntrevista}
              disabled={gravandoId !== null || faltaParaComecar.length > 0}
              title={
                faltaParaComecar.length > 0
                  ? `Digite ${rotulosPendentes.join(" e ")} antes de abrir o microfone`
                  : ""
              }
            >
              Iniciar transcrição e abrir roteiro
            </button>
          ) : null}

          {/* Com a chamada no ar, o microfone daqui não entra na transcrição —
              ele serve para o entrevistado ouvir o advogado, e quem cuida disso
              é o painel da chamada. Oferecer "ligar microfone" aqui convidaria a
              trocar a voz do cliente pela do entrevistador sem perceber. */}
          {false && fonte !== "chamada" && !escutando && (
            <button
              type="button"
              className={T_SECUNDARIO}
              onClick={ligarMicrofone}
              disabled={gravandoId !== null}
            >
              {temMic ? "Trocar microfone" : "Ligar microfone"}
            </button>
          )}

          <span className="hidden">
            {fonte === "chamada"
              ? "transcrevendo a voz do entrevistado"
              : fonte === "microfone"
                ? "transcrevendo este microfone"
                : "sem áudio"}
          </span>

          <button
            type="button"
            className="hidden"
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

          <span className="hidden">
            {feitas}/{total}
          </span>
        </div>
      </div>

      <div className="hidden">
        <i
          className="block h-full bg-tinta"
          style={{ width: `${total ? (feitas / total) * 100 : 0}%` }}
        />
      </div>

      {/* O vídeo fica aqui em cima porque gravar em vídeo se decide no começo
        * da conversa — e porque ele não é guardado em lugar nenhum, então quem
        * quiser precisa ver a opção antes, não depois. */}
      <VideoDaEntrevista automatico
        onPendente={(pendente) => {
          videoPendente.current = pendente;
        }}
      />

      {erro && <div className={T_ERRO}>{erro}</div>}

      {aviso && (
        <p className={T_AVISO} aria-live="polite">
          {aviso}
        </p>
      )}

      {/* A porta de entrada: sem nome e CPF, o microfone não abre.
        *
        * O aviso diz o que falta e leva até o campo, em vez de deixar um botão
        * cinza sem explicação — que é como o entrevistador descobriria a regra,
        * com o cliente esperando. */}
      {!escutando && faltaParaComecar.length > 0 && (
        <p className={T_AVISO}>
          <strong>Digite {rotulosPendentes.join(" e ")} para começar.</strong> São os
          dados que abrem o atendimento e que o contrato, a procuração e a declaração
          exigem — e os que não se colhem de ouvido, porque número, nome próprio e nome
          de cidade a transcrição erra.{" "}
          <button
            type="button"
            className="border-none bg-transparent p-0 text-tinta-3 font-normal text-[11px] leading-none font-ui underline underline-offset-[3px] cursor-pointer hover:text-tinta"
            onClick={() => irPara(faltaParaComecar[0].id)}
          >
            ir ao campo
          </button>
        </p>
      )}

      {!temMic && !escutando && faltaParaComecar.length === 0 && (
        <p className={T_AVISO}>
          Autorize o acesso ao microfone no navegador. A gravação e a transcrição começam
          automaticamente assim que a permissão for concedida.
        </p>
      )}

      {/* Sem "etapa 1 de 2": o roteiro inteiro já está na tela, e o que a
        * identificação decide é só quando o microfone abre. Quem ainda não
        * preencheu é avisado pelo bloco acima, que diz o que falta e leva ao
        * campo — dizer duas vezes a mesma coisa, uma delas prometendo uma
        * segunda etapa que não existe mais, era pior que não dizer. */}

      {/* O áudio passou a ser GUARDADO, não só transcrito. A saudação do roteiro
        * promete sigilo e não fala em gravação; enquanto ela não falar, quem
        * avisa é o entrevistador — e o lembrete fica onde ele olha antes de
        * abrir o microfone, não escondido num rodapé. */}
      {escutando && (
        <p className={T_AVISO}>
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
      {escutando && roteiro.saudacao?.length > 0 && (
        <section className="border-l-[3px] border-tinta px-4 py-3 mb-5 bg-papel-2">
          <div className="flex items-center justify-between gap-[10px]">
            <span className="text-[10px] font-semibold leading-none font-ui tracking-[0.14em] text-tinta-3">
              LEIA AO CLIENTE
            </span>
            {/* Botão sólido, não link: "já li" é uma ação que muda a tela
              * (recolhe a saudação), e como link discreto passava despercebido. */}
            <button
              type="button"
              className={
                saudacaoLida
                  ? "flex-none inline-flex items-center gap-[6px] border border-borda-forte bg-transparent text-tinta text-[10px] font-semibold leading-none font-ui tracking-[0.08em] uppercase px-3 py-2 rounded-campo cursor-pointer hover:bg-papel-3"
                  : "flex-none inline-flex items-center gap-[6px] border border-acao bg-acao text-papel text-[10px] font-semibold leading-none font-ui tracking-[0.08em] uppercase px-3 py-2 rounded-campo cursor-pointer hover:bg-acao-forte hover:border-acao-forte"
              }
              onClick={() => setSaudacaoLida((v) => !v)}
            >
              {saudacaoLida ? (
                "Mostrar de novo"
              ) : (
                <>
                  <span aria-hidden>✓</span> Já li
                </>
              )}
            </button>
          </div>
          {!saudacaoLida &&
            roteiro.saudacao.map((p, i) => (
              /* Letra grande: este texto é LIDO EM VOZ ALTA, de relance, com o
                 cliente esperando do outro lado. 14px servia para ler no
                 silêncio; quem lê em voz alta precisa achar a linha de volta
                 depois de olhar para a câmera. A medida de 62 caracteres
                 acompanha — linha longa demais faz perder o lugar. */
              <p key={i} className="mt-3 mb-0 font-normal text-[19px] leading-[1.7] font-titulo max-w-[62ch]">
                {comNomes(p)}
              </p>
            ))}
        </section>
      )}

      {escutaEncerrada && (recomendacaoCaso || atualizandoRecomendacao || erroRecomendacao) && (
        <section className={RECOMENDACAO} style={{ borderLeftWidth: "4px", borderLeftColor: "var(--tinta)" }} aria-live="polite">
          <div className={RECOMENDACAO_TOPO}>
            <strong className="text-tinta text-[14px]">Vale abrir este caso?</strong>
            {atualizandoRecomendacao && <span>atualizando com as respostas…</span>}
          </div>
          {recomendacaoCaso && (
            <>
              <div className={`${VEREDITO_BASE} ${VEREDITO_COR[recomendacaoCaso.recomendado] ?? VEREDITO_INDEFINIDO}`}>
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
                  return ref.url ? <a key={indice} className={RESUMO_LINK} href={ref.url} target="_blank" rel="noreferrer">{rotulo}</a> : <span key={indice}>{rotulo}</span>;
                }).reduce<React.ReactNode[]>((todos, item, i) => i ? [...todos, ", ", item] : [item], []);
                return (
                  <div className={COMPARATIVA}>
                    <h4 className={COMPARATIVA_H4}>O que os processos semelhantes indicam</h4>
                    <p>{analise.sintese}</p>
                    {analise.pontos_comuns.length > 0 && (
                      <details open className={COMPARATIVA_DETAILS}><summary className={RESUMO_SUMMARY}>Pontos realmente em comum</summary><ul className={COMPARATIVA_LISTA}>{analise.pontos_comuns.map((item, i) => <li key={i} className={COMPARATIVA_ITEM}><strong>{item.ponto}</strong> — {item.impacto} <small className={COMPARATIVA_SMALL}>Força {item.forca}: {refs(item.precedentes)}</small></li>)}</ul></details>
                    )}
                    {analise.diferencas_decisivas.length > 0 && (
                      <details open className={COMPARATIVA_DETAILS}><summary className={RESUMO_SUMMARY}>O que separou resultados favoráveis e improcedentes</summary><ul className={COMPARATIVA_LISTA}>{analise.diferencas_decisivas.map((item, i) => <li key={i} className={COMPARATIVA_ITEM}><strong>{item.ponto}</strong> — {item.por_que_importa}<small className={COMPARATIVA_SMALL}>Favoráveis: {refs(item.precedentes_favoraveis)} · Contrários: {refs(item.precedentes_contrarios)}</small></li>)}</ul></details>
                    )}
                    {analise.provas_prioritarias.length > 0 && (
                      <details open className={COMPARATIVA_DETAILS}><summary className={RESUMO_SUMMARY}>Provas para buscar agora</summary><ul className={COMPARATIVA_LISTA}>{analise.provas_prioritarias.map((item, i) => <li key={i} className={COMPARATIVA_ITEM}><strong>{item.prova}</strong> — {item.motivo}<small className={COMPARATIVA_SMALL}>{refs(item.precedentes)}</small></li>)}</ul></details>
                    )}
                    {analise.perguntas_criticas.length > 0 && (
                      <details open className={COMPARATIVA_DETAILS}><summary className={RESUMO_SUMMARY}>Perguntas que podem mudar a avaliação</summary><ol className={COMPARATIVA_LISTA}>{analise.perguntas_criticas.map((item) => <li key={item} className={COMPARATIVA_ITEM}>{item}</li>)}</ol></details>
                    )}
                  </div>
                );
              })()}
              {recomendacaoCaso.lacunas_obrigatorias.length > 0 && (
                <details><summary className={RESUMO_SUMMARY}>{recomendacaoCaso.lacunas_obrigatorias.length} pontos obrigatórios ainda faltam</summary><ul className={LISTA_BARE}>{recomendacaoCaso.lacunas_obrigatorias.slice(0, 8).map((item) => <li key={item}>{item}</li>)}</ul></details>
              )}
              {recomendacaoCaso.precedentes.length > 0 && (
                <details><summary className={RESUMO_SUMMARY}>{recomendacaoCaso.precedentes.length} processos semelhantes consultados</summary><ul className={LISTA_BARE}>{recomendacaoCaso.precedentes.slice(0, 8).map((p, i) => <li key={`${p.processo}-${i}`}>{p.url ? <a className={RESUMO_LINK} href={p.url} target="_blank" rel="noreferrer">{p.processo || `Precedente ${i + 1}`}</a> : (p.processo || `Precedente ${i + 1}`)} — {p.resultado || "resultado não classificado"} · {(p.similaridade * 100).toFixed(0)}%</li>)}</ul></details>
              )}
              <small className={RESUMO_SMALL}>{recomendacaoCaso.aviso}</small>
            </>
          )}
          {erroRecomendacao && <p className="text-atencao">{erroRecomendacao} A entrevista continua normalmente.</p>}
        </section>
      )}

      {/* O painel "A ENTREVISTA ATÉ AQUI" não fica mais ao lado do formulário:
        * ele foi para a coluna da direita, embaixo do cartão CHAMADA, e é a tela
        * de fora (`EntrevistaComChamada`) que o desenha a partir do que o efeito
        * de `onEscuta` publica. Aqui sobra só a coluna do roteiro. */}
      <div>
        <div>
          {/* A pergunta da vez, grudada no alto da coluna do roteiro. Vem ANTES
            * das perguntas todas porque é o que se lê ao cliente; o que está
            * embaixo é o formulário que se preenche. Fica DENTRO da coluna, e
            * não por cima do painel: os dois grudam ao rolar, e um passaria por
            * cima do outro. Enquanto a escuta não abriu ela só aponta por onde
            * começar — sem relógio, porque não há entrevista para cobrar ainda. */}
          {false && <Conducao
            pergunta={atual?.pergunta ?? null}
            bloco={atual?.bloco ?? ""}
            posicao={posicaoAtual + 1}
            total={total}
            puladas={puladas.length}
            sugestoes={sugestoes}
            retomadas={roteiro?.retomadas ?? []}
            fechosPorTipo={roteiro?.fechos_por_tipo ?? {}}
            /* Com o cliente respondendo ESTA pergunta, o relógio não corre: a
             * cobrança é para quem não responde, não para quem está no meio da
             * resposta. Falar de OUTRA coisa não conta — o relógio segue, que é
             * a regra do escritório. */
            ativo={escutando && estadoMic !== "pausado" && !respondendo}
            respondendo={respondendo}
            fluindo={fluindo}
            onIrPara={irPara}
            onPular={pular}
            onRetomarPuladas={retomarPuladas}
            onAceitar={aceitarSugestao}
            onDescartar={descartarSugestao}
          />}

          {aberturaBloco && (
            <IdentificacaoRecolhivel
              resumo={resumoIdentificacao}
              aberta={idExpandida}
              onAlternar={() => setIdExpandida((v) => !v)}
            >
              <BlocoRoteiro
                bloco={aberturaBloco}
                compacto
                respostas={respostas}
                perguntaAtual={escutando ? "" : (atual?.pergunta.id ?? "")}
                puladas={puladas}
                aguardando={aguardandoConfirmacao}
                onResponder={responder}
                gravandoId={gravandoId}
                pausado={estadoMic === "pausado"}
                finalizando={finalizando}
                parcial={parcial}
                temMic={temMic}
                escutando={escutando && identificacaoConcluida}
                onGravar={gravar}
                onPausar={pausar}
                onRetomar={retomar}
                onFinalizar={finalizar}
                conferencias={conferencias}
                onConferir={conferir}
                municipios={municipios}
                carregandoMunicipios={carregandoMunicipios}
              />
            </IdentificacaoRecolhivel>
          )}

          {blocosNoCorpo.map((bloco) => (
            <BlocoRoteiro
              key={bloco.id}
              bloco={bloco}
              respostas={respostas}
              perguntaAtual={escutando ? "" : (atual?.pergunta.id ?? "")}
              puladas={puladas}
              aguardando={aguardandoConfirmacao}
              onResponder={responder}
              gravandoId={gravandoId}
              pausado={estadoMic === "pausado"}
              finalizando={finalizando}
              parcial={parcial}
              temMic={temMic}
              escutando={escutando && identificacaoConcluida}
              onGravar={gravar}
              onPausar={pausar}
              onRetomar={retomar}
              onFinalizar={finalizar}
              conferencias={conferencias}
              onConferir={conferir}
              municipios={municipios}
              carregandoMunicipios={carregandoMunicipios}
            />
          ))}

          {false && !escutando && (
            <div className="mt-5 pt-4 border-t border-borda-forte">
              <button
                type="button"
                className={T_BOTAO}
                onClick={comecarEntrevista}
                disabled={gravandoId !== null || faltaParaComecar.length > 0}
                title={
                  faltaParaComecar.length > 0
                    ? `Digite ${rotulosPendentes.join(" e ")} antes de abrir o microfone`
                    : ""
                }
              >
                Iniciar transcrição e gravação
              </button>
            </div>
          )}
        </div>
      </div>

      {/* O encerramento, também para ser lido. Só aparece quando há o que
        * encerrar — no começo da entrevista ele seria ruído. */}
      {roteiro.encerramento?.length > 0 && feitas > 0 && (
        <details className="mt-6 border-t border-borda pt-[14px]">
          <summary className="text-[11px] font-semibold leading-[1.4] font-ui tracking-[0.06em] text-tinta-3 cursor-pointer">
            Encerramento — o que dizer ao final ({roteiro.encerramento.length} parágrafos)
          </summary>
          {roteiro.encerramento.map((p, i) => (
            <p key={i} className="mt-[10px] mb-0 font-normal text-[14px] leading-[1.65] font-titulo max-w-[74ch]">
              {comNomes(p)}
            </p>
          ))}
        </details>
      )}

      {/* O áudio, depois de encerrada a escuta. Antes disso não há arquivo, e um
        * botão que não baixa nada é pior que botão nenhum. */}
      {escutaEncerrada && (
        <AudioDaEntrevista entrevistaId={captura.current?.entrevistaId ?? ""} />
      )}

      {/* O roteiro respondido, abaixo de tudo e RECOLHIDO enquanto a conversa
        * corre — aberto ele disputaria o olho de quem conduz com o cliente.
        *
        * Ao encerrar, abre sozinho: as respostas que a escuta transpôs de cada
        * trecho de fala para o campo certo ficam à vista, e o que ficou em
        * branco ainda dá para colher com o cliente na linha. Depois disso quem
        * manda é o clique de quem está lendo. */}
      {escutando && (
        <RespostasDoRoteiro respostas={respostas} codigo={codigo} aberto={escutaEncerrada} />
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

/* A condicional que o roteiro escreve no enunciado, aplicada de verdade.
 *
 * "Se já entrou com ação: qual o número do processo?" só faz sentido depois de
 * "Já ingressou com ação?" ter sido respondida — e só se a resposta abrir o
 * caminho. Sem o pai respondido a filha fica FECHADA: ler o enunciado antes da
 * resposta anterior confunde o cliente.
 *
 * Função de módulo, e não um `useCallback` no componente de cima, porque as
 * DUAS pontas da tela precisam dela: a sequência (que decide a pergunta da vez)
 * e o render do bloco (que decide o campo visível). Duas cópias divergiriam no
 * primeiro ajuste, e o sintoma seria a tela pedindo uma pergunta que não
 * desenha.
 *
 * Mesma regra do backend (`_dependencia_aberta`, em app/escuta.py). Divergindo,
 * a tela esconde um campo que o painel continua cobrando — que é exatamente o
 * problema que este encadeamento veio resolver. */
function dependenciaAberta(p: Pergunta, respostas: Respostas): boolean {
  if (!p.depende_de) return true;
  const valor = String(respostas[p.depende_de] ?? "").trim().toLowerCase();
  const esperado = p.depende_valor.trim().toLowerCase();
  if (esperado === "nao" || esperado === "não") return valor === "nao" || valor === "não";
  return valor === esperado;
}

/* O bloco de identificação depois de preenchido: um cabeçalho compacto tipo
 * accordion. Recolhido mostra só o resumo (nome · CPF · município/UF); aberto,
 * os quatro campos, editáveis. O resto da página se reorganiza sozinho — o
 * conteúdo abaixo é fluxo normal e sobe para ocupar o espaço liberado. */
function IdentificacaoRecolhivel({
  resumo,
  aberta,
  onAlternar,
  children,
}: {
  resumo: string;
  aberta: boolean;
  onAlternar: () => void;
  children: ReactNode;
}) {
  return (
    <section className="mt-[26px] border border-borda-forte rounded-campo bg-papel-2 overflow-hidden">
      <button
        type="button"
        onClick={onAlternar}
        aria-expanded={aberta}
        className="flex w-full items-center gap-3 border-none bg-transparent px-4 py-3 text-left cursor-pointer hover:bg-papel-3"
      >
        <span className="flex-none text-[11px] font-semibold leading-none font-ui tracking-[0.14em] text-tinta-3">
          IDENTIFICAÇÃO
        </span>
        {!aberta && resumo && (
          <span className="flex-1 min-w-0 truncate font-normal text-[12.5px] leading-[1.4] font-ui text-tinta">
            {resumo}
          </span>
        )}
        <span className="flex-none ml-auto inline-flex items-center gap-[6px] text-[10px] font-semibold uppercase leading-none tracking-[0.1em] text-tinta-3">
          {aberta ? "Recolher" : "Revisar"}
          <span aria-hidden className={`transition-transform ${aberta ? "rotate-180" : ""}`}>
            ▾
          </span>
        </span>
      </button>
      {aberta && <div className="px-4 pb-4 pt-1">{children}</div>}
    </section>
  );
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
  municipios,
  carregandoMunicipios,
  compacto = false,
}: {
  bloco: Bloco;
  respostas: Respostas;
  /** Dentro do cabeçalho recolhível da identificação: sem título nem objetivo
   *  (o cabeçalho já os dá) e sem o espaçamento de bloco solto. */
  compacto?: boolean;
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
  municipios: MunicipioLocalidade[];
  carregandoMunicipios: boolean;
}) {
  return (
    <section className={compacto ? "" : "mt-[26px]"}>
      {!compacto && (
        <span className="text-[11px] font-semibold leading-none font-ui tracking-[0.14em] text-tinta-3">
          {bloco.titulo.toUpperCase()}
        </span>
      )}
      {!compacto && bloco.objetivo && (
        <p className="mt-[5px] mb-0 italic font-normal text-[12px] leading-[1.5] font-titulo text-tinta-3">
          {bloco.objetivo}
        </p>
      )}

      {/* O bloco que NÃO se percorre na entrevista.
        *
        * Ele ficava aqui igual aos outros, e nada na tela dizia que a condução
        * pula estes campos de propósito — quem não conhecia o roteiro começava
        * a datilografar a qualificação com o cliente esperando. */}
      {bloco.delegado_a && (
        <p className="mt-2 border-l-[3px] border-atencao px-[11px] py-2 bg-papel-2 font-normal text-[12px] leading-[1.55] font-ui max-w-[74ch]">
          <strong>Não percorrer nesta entrevista.</strong> Esta etapa é do{" "}
          {bloco.delegado_a}, depois do encerramento.
          {bloco.instrucao && (
            <span className="block mt-[5px] italic font-normal text-[11.5px] leading-[1.5] font-titulo text-tinta-3">
              {bloco.instrucao}
            </span>
          )}
        </p>
      )}

      <ul className={`list-none mb-0 p-0 ${compacto ? "mt-0" : "mt-3 border-t-[3px] border-double border-borda-forte"}`}>
        {bloco.perguntas.filter((p) => dependenciaAberta(p, respostas)).map((p, i) => (
          <li
            key={p.id}
            // A âncora que o painel usa para rolar até aqui.
            id={`pergunta-${p.id}`}
            className={`py-[14px] pr-0 border-b border-borda ${
              respostas[p.id] ? "bg-[color-mix(in_srgb,var(--ok)_5%,transparent)]" : ""
            } ${
              p.id === perguntaAtual
                ? "pl-[10px] [box-shadow:inset_3px_0_0_var(--tinta)]"
                : "pl-0"
            }`}
          >
            <div className="flex gap-[10px] items-baseline">
              <span className="flex-none w-[26px] font-medium text-[11px] leading-[1.4] font-codigo tabular-nums text-tinta-3">
                {String(i + 1).padStart(2, "0")}
              </span>
              <span className="flex-1 font-normal text-[14.5px] leading-[1.45] font-ui">
                {p.texto}
                {p.obrigatoria && <span className="text-critico ml-1">*</span>}
              </span>
              {/* A mesma pergunta que está na barra do topo. Sem esta marca, o
                * entrevistador que rolou a tela precisa reler a barra para
                * saber onde ela caiu no formulário. */}
              {p.id === perguntaAtual && (
                <span className="flex-none self-center text-[9px] font-semibold leading-none font-ui tracking-[0.1em] text-papel bg-tinta px-[6px] py-1">
                  AGORA
                </span>
              )}
              {/* Ouvida, não confirmada. A condução seguiu em frente para não
                * travar a conversa; a marca é o que impede a pergunta de passar
                * por respondida quando ainda depende de um clique. */}
              {aguardando.has(p.id) && (
                <span className="flex-none self-center text-[9px] font-semibold leading-none font-ui tracking-[0.1em] text-atencao border border-atencao px-[5px] py-[3px]">
                  OUVIDO · CONFIRA NO FIM
                </span>
              )}
              {puladas.includes(p.id) && (
                <span className="flex-none self-center text-[9px] font-semibold leading-none font-ui tracking-[0.1em] text-tinta-3 border border-dashed border-borda-forte px-[5px] py-[3px]">
                  DEIXADA PARA DEPOIS
                </span>
              )}
              {p.transcrever && (
                <span className="flex-none self-center text-[9px] font-semibold leading-none font-ui tracking-[0.1em] text-atencao border border-atencao px-[5px] py-[3px]">
                  VOZ
                </span>
              )}
            </div>

            {p.dica && (
              <span className="block mt-1 ml-9 italic font-normal text-[11.5px] leading-[1.5] font-titulo text-tinta-3">
                {p.dica}
              </span>
            )}

            <div className="mt-[10px] ml-9">
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
                municipios={municipios}
                carregandoMunicipios={carregandoMunicipios}
              />

              {/* O que a escuta ouviu, à mostra no próprio campo.
                *
                * Sem isto o entrevistador fala o nome, o campo continua vazio e
                * a conclusão óbvia é "não pegou nada" — foi exatamente o que
                * aconteceu quando a caixa de confirmação saiu do painel. O
                * valor fica visível; confirmar continua sendo no fim. */}
              {aguardando.has(p.id) && (
                <span className="block mt-[6px] font-normal text-[11.5px] leading-[1.5] font-ui text-tinta-3">
                  ouvi{" "}
                  <strong className="font-semibold text-[12.5px] leading-[1.4] font-codigo tabular-nums text-atencao">
                    “{aguardando.get(p.id)}”
                  </strong>{" "}
                  — entra no campo quando você confirmar, no fim do roteiro
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
        className="w-full max-w-[520px] border border-borda-forte bg-papel-2 text-tinta px-[11px] py-[9px] font-normal text-[13px] leading-[1.4] font-ui"
        type="text"
        inputMode="numeric"
        value={valor}
        maxLength={9}
        placeholder="00000-000"
        onChange={(e) => onResponder(pergunta.id, formatarCep(e.target.value))}
      />

      {buscando && (
        <span className="block mt-[5px] font-normal text-[11.5px] leading-[1.4] font-codigo text-tinta-3">
          consultando o endereço…
        </span>
      )}
      {erro && (
        <span className="block mt-[5px] font-normal text-[11.5px] leading-[1.4] font-codigo text-critico">
          {erro}
        </span>
      )}

      {achado && !erro && !buscando && (
        <span className="block mt-[5px] font-normal text-[11.5px] leading-[1.4] font-codigo text-ok">
          {achado.endereco_formatado}
          <em className="ml-2 not-italic font-normal text-[11px] leading-[1.4] font-codigo text-tinta-3">
            via {achado.fonte}
          </em>
          {alvo.current.trim() && alvo.current !== achado.endereco_formatado && (
            <button
              type="button"
              className="block mt-[6px] border border-borda-forte bg-transparent text-tinta text-[10px] font-semibold leading-none font-ui tracking-[0.08em] uppercase px-[10px] py-[7px] cursor-pointer hover:bg-papel-2"
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
  municipios,
  carregandoMunicipios,
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
  municipios: MunicipioLocalidade[];
  carregandoMunicipios: boolean;
}) {
  const texto = typeof valor === "string" ? valor : "";

  if (escutando && ["nome", "cpf", "uf", "municipio"].includes(pergunta.id)) {
    return (
      <div className="w-full max-w-[520px] border border-ok bg-ok-claro text-tinta px-[11px] py-[9px] text-[13px] font-ui">
        {texto || "—"}
      </div>
    );
  }

  // Ao vivo o roteiro é guia de leitura, não formulário. A fala só será
  // interpretada e distribuída entre campos depois do encerramento.
  if (escutando && !CAMPOS_TECNICOS_DIGITADOS.has(pergunta.id)) {
    // As alternativas fazem parte do enunciado. Mesmo sem transformar o
    // roteiro ao vivo em formulário, elas precisam ficar visíveis para leitura.
    if (pergunta.tipo === "documentos" || pergunta.tipo === "escolha" || pergunta.tipo === "lista") {
      const marcados = Array.isArray(valor) ? valor : [texto].filter(Boolean);
      return (
        <ul className="m-0 pl-5 text-[12.5px] leading-[1.65] font-ui text-tinta-3">
          {pergunta.opcoes.map((opcao) => (
            <li key={opcao} className={marcados.includes(opcao) ? "font-semibold text-tinta" : ""}>
              {opcao}
            </li>
          ))}
        </ul>
      );
    }
    return null;
  }

  if (pergunta.id === "municipio") {
    return (
      <select
        className="w-full max-w-[520px] border border-borda-forte bg-papel-2 text-tinta px-[11px] py-[9px] text-[13px] font-ui disabled:opacity-60"
        value={texto}
        disabled={carregandoMunicipios || municipios.length === 0}
        onChange={(e) => onResponder(pergunta.id, e.target.value)}
      >
        <option value="">{carregandoMunicipios ? "Carregando municípios…" : municipios.length ? "Selecione o município" : "Escolha a UF primeiro"}</option>
        {municipios.map((municipio) => <option key={municipio.id} value={municipio.nome}>{municipio.nome}</option>)}
      </select>
    );
  }

  if (pergunta.tipo === "sim_nao") {
    return (
      <div className="flex gap-2 flex-wrap">
        {["sim", "não"].map((o) => (
          <button
            key={o}
            type="button"
            className={classeOpcao(texto === o, o === "sim")}
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
      <div className="flex gap-2 flex-wrap">
        {pergunta.opcoes.map((o) => (
          <button
            key={o}
            type="button"
            className={classeOpcao(texto === o, false)}
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
        className="w-auto min-w-[96px] border border-borda-forte bg-papel-2 text-tinta px-[11px] py-[9px] font-normal text-[13px] leading-[1.4] font-ui [&>option]:bg-papel [&>option]:text-tinta"
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
      <div className="flex flex-col gap-[6px]">
        {pergunta.opcoes.map((o) => (
          <label
            key={o}
            className="flex items-center gap-2 font-normal text-[12.5px] leading-[1.4] font-ui cursor-pointer"
          >
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
          className={`w-full max-w-[520px] border ${
            veredito.valido === false ? "border-critico" : "border-borda-forte"
          } bg-papel-2 text-tinta px-[11px] py-[9px] font-normal text-[13px] leading-[1.4] font-ui`}
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
            className={`block mt-[5px] font-normal text-[11.5px] leading-[1.4] font-codigo ${
              veredito.valido === false ? "text-critico" : veredito.valido ? "text-ok" : "text-tinta-3"
            }`}
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
        className="w-full max-w-[520px] border border-borda-forte bg-papel-2 text-tinta px-[11px] py-[9px] font-normal text-[13px] leading-[1.4] font-ui"
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
        <div className={`${T_ACOES} mb-2`}>
          {!emCurso && (
            <button
              type="button"
              className={T_BOTAO}
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
                className={T_SECUNDARIO}
                onClick={pausado ? onRetomar : onPausar}
                // Depois de finalizar não há o que pausar: a captura já parou.
                // Desabilitar é o que faz o botão parar de mentir.
                disabled={finalizando}
              >
                {pausado ? "Retomar" : "Pausar"}
              </button>
              <button
                type="button"
                className={gravando && !finalizando ? T_BOTAO_GRAVANDO : T_BOTAO}
                onClick={onFinalizar}
                disabled={finalizando}
              >
                {finalizando ? "Transcrevendo…" : "Finalizar resposta"}
              </button>
            </>
          )}

          {pausado && !finalizando && (
            <span className="font-normal text-[11.5px] leading-[1.4] font-ui text-atencao self-center">
              pausado — o que for dito agora não entra na resposta
            </span>
          )}

          {finalizando && (
            <span className="font-normal text-[11.5px] leading-[1.4] font-ui text-atencao self-center">
              transcrevendo a resposta inteira — o texto aparece em instantes
            </span>
          )}
        </div>
      )}

      <textarea
        className="w-full min-h-[88px] border border-borda-forte bg-papel-2 text-tinta px-[11px] py-[10px] font-normal text-[13px] leading-[1.6] font-ui resize-y"
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
