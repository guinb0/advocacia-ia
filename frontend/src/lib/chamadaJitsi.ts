"use client";

import { criarEfeitoFundo, preCarregarFundoVirtual } from "./fundoVirtual";

const FUNDO_ADVOGADO = "/fundo-chamada.jpg";

/* A chamada sobre o Jitsi, usando a lib-jitsi-meet.
 *
 * POR QUE A BIBLIOTECA E NÃO O IFRAME
 *
 * O jeito fácil de embutir o Jitsi é a IFrame API — meia dúzia de linhas e sai
 * a tela do Meet inteira. Ela não serve aqui, e o motivo é concreto: a ponte
 * entre o iframe e a página é `postMessage`, que só carrega dado serializável.
 * `MediaStreamTrack` não atravessa. Conferido no fonte do repositório
 * (`modules/API/external/external_api.js`): não há uma única menção a
 * `MediaStream`, `getTrack` ou `srcObject`.
 *
 * Sem a faixa de áudio do outro lado, a transcrição do entrevistado morre — que
 * é justamente o que esta ferramenta faz de mais útil. A `lib-jitsi-meet` entrega
 * os objetos de faixa (`track.getTrack()`), então o Whisper continua ouvindo o
 * cliente, e a interface continua sendo a nossa.
 *
 * O QUE GANHAMOS TROCANDO O NOSSO WEBRTC POR ESTE
 *
 * A implementação caseira era ponto a ponto e sem TURN: em NAT simétrico (parte
 * do 4G e de redes corporativas) a chamada simplesmente não fechava. O Jitsi tem
 * o videobridge no meio, então o áudio sempre encontra caminho, além de trazer
 * reconexão, controle de banda e sala com mais de duas pessoas.
 *
 * A BIBLIOTECA VEM DO PRÓPRIO SERVIDOR
 *
 * `<script src="{jitsi}/libs/lib-jitsi-meet.min.js">`, e não pacote npm: assim
 * cliente e servidor estão sempre na mesma versão. O protocolo entre eles muda
 * entre releases, e uma dependência congelada no `package.json` quebraria em
 * silêncio no dia em que o contêiner fosse atualizado.
 */

const BASE_JITSI = process.env.NEXT_PUBLIC_JITSI_URL ?? "http://localhost:8081";

/** Quanto se espera antes de tratar um microfone mudo como microfone perdido.
 *  Trazer a aba de volta costuma devolver o áudio em menos de um segundo. */
const ESPERA_MUDO_MS = 3_000;

/** Quanto se espera, depois que a rede volta, antes de republicar o microfone.
 *  O ICE precisa terminar de renegociar: republicar no meio da renegociação
 *  entrega a faixa a um transporte que ainda vai ser trocado. */
const ESPERA_TRANSPORTE_MS = 1_500;

/** Janela mínima entre duas republicações. Uma troca de rede dispara
 *  `CONNECTION_INTERRUPTED` e `CONNECTION_RESTORED` várias vezes seguidas, e
 *  recriar a faixa a cada uma cortaria a voz em vez de devolvê-la. */
const ESPERA_REPUBLICAR_MS = 8_000;

/* QUALIDADE DE VÍDEO — o que se pede, e por que não se pede o máximo.
 *
 * Até aqui não havia número nenhum: `createLocalTracks` ia sem `resolution`, e
 * a lib assumia o padrão dela; a escada de fallback começava em "qualquer
 * coisa" e descia a 240p ao primeiro tropeço, sem nunca voltar a subir. O
 * resultado é o que o escritório vê: rosto chapado, ilegível na hora de ler a
 * expressão de quem responde.
 *
 * 720p a 30 fps é o TETO pedido, não o valor fixo. Quem decide o que realmente
 * sobe é o simulcast do Jitsi, quadro a quadro, conforme a banda medida — por
 * isso o `min` fica em 180p: numa rede ruim a chamada DEGRADA em vez de travar,
 * que é exatamente o pedido. Fixar 720p sem mínimo é o que produz a chamada
 * que congela em vez de ficar feia.
 *
 * `ALTURA_RECEPCAO` é a outra metade, e a mais esquecida: sem pedir nada, a
 * lib entrega ao <video> a camada mais baixa do simulcast (180p). Não adianta o
 * outro lado ENVIAR 720p se este lado nunca pede mais que 180p — era o caso. */
const ALTURA_VIDEO = 720;
const ALTURA_MINIMA = 180;
const FPS_VIDEO = 30;
const ALTURA_RECEPCAO = 720;

/** Espera antes da primeira reconexão; dobra a cada tentativa. */
const ESPERA_RECONEXAO_MS = 3_000;
/** Quantas vezes a chamada tenta voltar sozinha antes de se dar por encerrada. */
const MAX_RECONEXOES = 5;

/** Tolerância entre perder a faixa remota e declarar que não há mais voz.
 *
 *  Cobre a troca de microfone do outro lado (remove uma faixa, publica outra),
 *  que é rápida. Curto de propósito: quem de fato saiu já foi anunciado por
 *  `USER_LEFT`, então esperar aqui não atrasa nada que importe. */
const ESPERA_TROCA_REMOTA_MS = 2_500;

/** As restrições de câmera pedidas ao navegador. `ideal`, e nunca `exact`:
 *  `exact` faz a webcam que não tem o modo exato falhar por inteiro, e a
 *  chamada cai para "sem câmera" em vez de abrir na resolução possível. */
const VIDEO_PEDIDO = {
  height: { ideal: ALTURA_VIDEO, min: ALTURA_MINIMA, max: ALTURA_VIDEO },
  frameRate: { ideal: FPS_VIDEO, max: FPS_VIDEO },
} as const;

export type PapelChamada = "advogado" | "cliente";

export type EstadoChamada =
  /** Sem chamada. */
  | "fora"
  /** Na sala, esperando o outro lado aparecer. */
  | "aguardando"
  /** Conectando ao servidor ou entrando na sala. */
  | "conectando"
  /** Áudio fluindo. */
  | "falando"
  /** Caiu ou o outro desligou. */
  | "encerrada";

/** Quem está na sala, para desenhar os retratos. */
export interface Participante {
  id: string;
  nome: string;
  /** `null` enquanto a câmera estiver desligada — aí vale a inicial do nome. */
  video: MediaStreamTrack | null;
  /** O vídeo é uma tela compartilhada, não um rosto. Muda como se mostra:
   *  recortar uma tela corta justamente o documento que se quis mostrar. */
  tela: boolean;
  /** Este é o retrato de quem está usando a tela. */
  souEu: boolean;
}

export interface EventosChamada {
  onEstado?: (estado: EstadoChamada) => void;
  /** A voz do outro lado. No advogado, é o que alimenta o Whisper. */
  onFaixaRemota?: (trilha: MediaStreamTrack) => void;
  /** A NOSSA voz, para a tela medir se está mesmo saindo som. Vem de novo a
   *  cada troca de faixa (recuperação, "Reativar áudio"), e `null` ao desligar —
   *  senão a barra continuaria medindo uma faixa morta e acusaria silêncio. */
  onFaixaLocal?: (trilha: MediaStreamTrack | null) => void;
  /** A sala inteira mudou: alguém entrou, saiu, ligou câmera ou trocou de nome. */
  onParticipantes?: (lista: Participante[]) => void;
  onErro?: (mensagem: string) => void;
}

export interface OpcoesEntrada {
  /** Nome exibido aos outros. Sem login: é o que a pessoa digitar. */
  nome?: string;
  /** Entrar já com a câmera ligada. */
  camera?: boolean;
  /** O microfone aprovado no teste da tela anterior. Sem isto a chamada abriria
   *  com o padrão do sistema — que é, com frequência, justamente o que não
   *  funciona (o do monitor, o fone desconectado). */
  microfoneId?: string;
  /** Tentar ligação direta entre os navegadores antes de usar o videobridge.
   *  Quem decide é o servidor (`CHAMADA_P2P`); o padrão é `false`. Ver o
   *  comentário em `entrarNaSala`. */
  p2p?: boolean;
}

/* A lib-jitsi-meet não publica tipos. Em vez de arrastar um pacote de tipos da
 * comunidade — que descreve outra versão e mente com confiança —, declara-se
 * aqui só o que este arquivo usa. O que não está descrito, não é usado. */
interface FaixaJitsi {
  isLocal(): boolean;
  getType(): "audio" | "video";
  /** "camera" ou "desktop". A lib só o define em faixa de vídeo. */
  getVideoType?(): string | undefined;
  getTrack(): MediaStreamTrack;
  getParticipantId?(): string;
  /** A lib só a expõe em algumas versões; usada para saber se o outro lado se
   *  calou de propósito, e não para decidir nada crítico. */
  isMuted?(): boolean;
  attach(elemento: HTMLMediaElement): void;
  detach(elemento: HTMLMediaElement): void;
  mute(): Promise<void>;
  unmute(): Promise<void>;
  dispose(): Promise<void>;
  setEffect?(efeito: unknown): Promise<void>;
}

interface ParticipanteJitsi {
  getId(): string;
  getDisplayName(): string | undefined;
}

interface ConferenciaJitsi {
  on(evento: string, ouvinte: (...args: unknown[]) => void): void;
  addTrack(faixa: FaixaJitsi): Promise<void>;
  removeTrack(faixa: FaixaJitsi): Promise<void>;
  setDisplayName(nome: string): void;
  getParticipants(): ParticipanteJitsi[];
  join(senha?: string): void;
  leave(): Promise<void>;
  getParticipantCount(): number;
  /* Os dois são OPCIONAIS porque a lib vem do servidor, que é atualizado por
   * fora deste repositório: em versões antigas eles não existem, e chamá-los
   * sem conferir derrubaria a entrada na sala inteira — por qualidade de
   * imagem, que é o menor dos problemas quando ninguém consegue entrar. */
  setReceiverVideoConstraints?(restricoes: Record<string, unknown>): void;
  setSenderVideoConstraint?(altura: number): Promise<void> | void;
}

interface ConexaoJitsi {
  addEventListener(evento: string, ouvinte: (...args: unknown[]) => void): void;
  connect(): void;
  disconnect(): Promise<void>;
  initJitsiConference(sala: string, opcoes: Record<string, unknown>): ConferenciaJitsi;
}

interface ApiJitsi {
  init(opcoes: Record<string, unknown>): void;
  setLogLevel(nivel: unknown): void;
  logLevels: Record<string, unknown>;
  events: {
    connection: Record<string, string>;
    conference: Record<string, string>;
  };
  errors: Record<string, Record<string, string>>;
  JitsiConnection: new (
    appId: string | null,
    token: string | null,
    opcoes: Record<string, unknown>,
  ) => ConexaoJitsi;
  createLocalTracks(opcoes: Record<string, unknown>): Promise<FaixaJitsi[]>;
  isWebRtcSupported?(): boolean;
  util?: { browser?: { isSupported?(): boolean; getName?(): string; getVersion?(): string } };
}

const LIMITE_SERVIDOR_MS = 25_000;
const LIMITE_AUDIO_MS = 25_000;

function descreverNavegador(): string {
  if (typeof navigator === "undefined") return "navegador desconhecido";
  const chrome = navigator.userAgent.match(/Chrome\/(\d+)/);
  return chrome ? `Chrome ${chrome[1]}` : "este navegador";
}

declare global {
  interface Window {
    JitsiMeetJS?: ApiJitsi;
  }
}

let carregando: Promise<ApiJitsi> | null = null;

/** Baixa a lib do servidor Jitsi uma única vez por aba. */
function carregarJitsi(): Promise<ApiJitsi> {
  if (window.JitsiMeetJS) return Promise.resolve(window.JitsiMeetJS);
  if (carregando) return carregando;

  carregando = new Promise<ApiJitsi>((ok, falhou) => {
    const script = document.createElement("script");
    script.src = `${BASE_JITSI}/libs/lib-jitsi-meet.min.js`;
    script.async = true;
    script.onload = () => {
      const api = window.JitsiMeetJS;
      if (!api) {
        falhou(new Error("A biblioteca do Jitsi carregou sem se registrar."));
        return;
      }
      // `disableAudioLevels` desliga o medidor de volume, que roda um timer por
      // participante e não serve para nada aqui — quem mede áudio é o Whisper.
      api.init({ disableAudioLevels: true });
      api.setLogLevel(api.logLevels.ERROR);
      ok(api);
    };
    script.onerror = () => {
      carregando = null;
      // Sem comando de terminal: quem lê isto é quem está tentando abrir a
      // chamada com o cliente esperando, não quem administra o servidor. O
      // comando de subir o Jitsi está no docs/CHAMADA.md, que é onde o suporte
      // procura. Aqui o que importa é dizer que dá para seguir sem a chamada.
      falhou(
        new Error(
          `Servidor de chamadas fora do ar (${BASE_JITSI}). ` +
            "Avise o suporte técnico. A entrevista pode seguir pelo microfone " +
            "da máquina, com o cliente no viva-voz.",
        ),
      );
    };
    document.head.appendChild(script);
  });

  return carregando;
}

export type PermissaoMicrofone = "permitido" | "negado" | "indisponivel";

export async function consultarPermissaoMicrofone(): Promise<PermissaoMicrofone | "perguntar"> {
  if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) return "indisponivel";
  try {
    const status = await navigator.permissions?.query({ name: "microphone" as PermissionName });
    if (status?.state === "granted") return "permitido";
    if (status?.state === "denied") return "negado";
  } catch {
    return "perguntar";
  }
  return "perguntar";
}

/* `pedirPermissaoMicrofone` existia aqui e foi removida em 16/09/2026.
 *
 * Ela pedia o microfone só para conferir a PERMISSÃO e soltava a faixa em
 * seguida — era o que sustentava o "✓ Microfone ligado" que ficava verde com o
 * cliente mudo. Quem faz esse trabalho agora é o próprio `AtivarMicrofone`, que
 * segura a faixa o tempo do teste para MEDIR o som antes de aprovar, e por isso
 * não podia soltá-la aqui dentro. */

function ehCelular(): boolean {
  return typeof navigator !== "undefined" && /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent);
}

async function abrirVideoComFallback(api: ApiJitsi): Promise<FaixaJitsi[]> {
  let ultimo: unknown = null;
  /* A escada começa no que se quer e desce só o necessário. Antes ela começava
   * em `{}` — "o que vier" — e a webcam que negociasse mal já entregava 240p
   * para o resto da entrevista, sem nada na tela dizendo por quê. */
  for (const opcoes of [
    { resolution: ALTURA_VIDEO, constraints: { video: VIDEO_PEDIDO } },
    { resolution: 480 },
    { resolution: 240, constraints: { video: true } },
  ]) {
    try {
      const faixas = await api.createLocalTracks({ devices: ["video"], ...opcoes });
      if (faixas.some((f) => f.getType() === "video")) return faixas;
    } catch (e) {
      ultimo = e;
      if (/permission|NotAllowed|Security|not_found|NotFound/i.test(textoDoErro(e))) break;
    }
  }
  throw ultimo ?? new Error("Nenhuma câmera encontrada.");
}

function textoDoErro(e: unknown): string {
  if (!e || typeof e !== "object") return String(e ?? "");
  const erro = e as { name?: string; message?: string; gum?: { error?: { name?: string; message?: string } } };
  return [erro.name, erro.message, erro.gum?.error?.name, erro.gum?.error?.message].filter(Boolean).join(" ");
}

export function explicarErroCamera(e: unknown): string {
  const texto = textoDoErro(e);
  if (/permission|NotAllowed|Security|denied/i.test(texto)) {
    return "A câmera foi bloqueada. Clique no cadeado ao lado do endereço do site, permita a Câmera e recarregue a página. No Windows, confira também Configurações > Privacidade > Câmera.";
  }
  if (/not_found|NotFound|DevicesNotFound/i.test(texto)) {
    return "Nenhuma câmera foi encontrada. Em notebooks (como Acer), a câmera pode estar desligada pela tecla de atalho (Fn + tecla com ícone de câmera) ou por uma tampinha física.";
  }
  if (/NotReadable|TrackStart|Could not start|general|in use/i.test(texto)) {
    return "A câmera está sendo usada por outro programa (Teams, Zoom, WhatsApp, outra aba) ou foi desligada pela tecla de atalho do notebook. Feche o outro programa e clique em Câmera de novo.";
  }
  if (/constraint|Overconstrained/i.test(texto)) {
    return "A câmera deste computador não aceitou a configuração de vídeo. Clique em Câmera de novo.";
  }
  if (/timeout/i.test(texto)) {
    return "A câmera demorou demais para responder. Feche outros programas que usam a câmera e tente de novo.";
  }
  return `Não foi possível abrir a câmera${texto ? ` (${texto})` : ""}.`;
}

export class ChamadaJitsi {
  private api: ApiJitsi | null = null;
  private conexao: ConexaoJitsi | null = null;
  private sala: ConferenciaJitsi | null = null;
  private minhaFaixa: FaixaJitsi | null = null;
  private minhaCamera: FaixaJitsi | null = null;
  private minhaTela: FaixaJitsi | null = null;
  /** A câmera estava ligada quando a tela entrou? Decide se ela volta no fim. */
  private cameraAntesDaTela = false;
  private remotas = new Map<FaixaJitsi, HTMLAudioElement>();
  /** Vídeo de cada participante, por id. Áudio não entra aqui: ele é ouvido. */
  private videos = new Map<string, MediaStreamTrack>();
  /** Quem está mostrando a tela, por id de participante. */
  private telas = new Set<string>();
  private meuNome = "";
  private estadoAtual: EstadoChamada = "fora";
  private desligando = false;
  private mudoAtual = false;
  /** O microfone escolhido na entrada, para as recuperações reabrirem O MESMO —
   *  reabrir no padrão do sistema devolveria o dispositivo que já falhou. */
  private microfoneEscolhido: string | undefined;
  /** Retrato da última lista de microfones, para saber o que entrou ou saiu
   *  quando o `devicechange` avisa que ela mudou. */
  private dispositivosConhecidos: string[] = [];
  /** Tentar ligação direta antes do bridge. Decidido pelo servidor a cada
   *  entrada, para poder ser revertido sem rebuild do frontend. */
  private p2pLigado = false;
  /** Impede duas recuperações de microfone ao mesmo tempo (`ended` + `mute`). */
  private recuperandoAudio = false;
  /** Uma entrada por vez. Ver o comentário em `entrar`. */
  private entrando = false;
  /** Uma troca de vídeo por vez (câmera ou tela).
   *
   *  O Jitsi aceita UMA faixa de vídeo por participante, e ligar câmera ou tela
   *  leva vários `await` — pedir o dispositivo, aplicar o fundo, publicar. Dois
   *  cliques dentro dessa janela (o toque duplo do cliente no celular é o caso
   *  comum) abriam duas capturas: a segunda morria em "Cannot add second video
   *  track", com a câmera do aparelho acesa e o botão dizendo o contrário. */
  private mexendoVideo = false;
  /** O que é preciso para RECONECTAR sozinho: a lib, a sala e o token. Guardados
   *  porque quem descobre a queda é um ouvinte, longe de quem chamou `entrar`. */
  private religar: { api: ApiJitsi; sala: string; token?: string } | null = null;
  private tentativasReconexao = 0;
  private temporizadorReconexao: number | null = null;
  /** O ouvinte global que libera as saídas de áudio no primeiro toque. Um só
   *  por chamada, e removido no desligamento — ver `garantirDestrave`. */
  private destravarAudio: (() => void) | null = null;
  private travaTela: WakeLockSentinel | null = null;
  private limiteAudio: number | null = null;
  /** Espera antes de declarar que não há mais voz do outro lado. Ver `soltarFaixa`. */
  private esperaSemRemota: number | null = null;

  private vigiarAudioRemoto(): void {
    if (this.limiteAudio !== null) window.clearTimeout(this.limiteAudio);
    this.limiteAudio = window.setTimeout(() => {
      this.limiteAudio = null;
      if (this.desligando || this.remotas.size > 0) return;
      this.eventos.onErro?.(
        "Você entrou na sala, mas o áudio da outra pessoa não chegou. Saia da chamada e entre de novo; " +
          `se continuar, troque entre Wi-Fi e 4G ou atualize o Google Chrome (${descreverNavegador()}).`,
      );
    }, LIMITE_AUDIO_MS);
  }
  private aoMudarVisibilidade = () => void this.retomarAoVoltar();
  private aoTrocarDispositivos = () => void this.conferirDispositivos();
  private aoVoltarRede = () => void this.restabelecerAudio("a internet voltou");
  /** Quando foi a última republicação, para não recriar a faixa em rajada. */
  private ultimoRestabelecimento = 0;

  constructor(
    private papel: PapelChamada,
    private eventos: EventosChamada = {},
  ) {}

  get estado(): EstadoChamada {
    return this.estadoAtual;
  }

  get mudo(): boolean {
    return this.mudoAtual;
  }

  get temCamera(): boolean {
    return this.minhaCamera !== null;
  }

  get compartilhandoTela(): boolean {
    return this.minhaTela !== null;
  }

  /** O navegador sabe capturar tela?
   *
   * Falso no Safari do iPhone e na maior parte dos navegadores de celular, que
   * não implementam `getDisplayMedia`. O cliente entra pelo telefone — oferecer
   * um botão que abre um erro de permissão no meio da entrevista é pior que não
   * ter botão. Quem não pode compartilhar não vê a opção. */
  static telaDisponivel(): boolean {
    return typeof navigator !== "undefined" && Boolean(navigator.mediaDevices?.getDisplayMedia);
  }

  /* Abre o microfone (e a câmera, se pedida) e entra na sala.
   *
   * A GUARDA ERA TARDIA DEMAIS — E ESTA É A CORRIDA DA INICIALIZAÇÃO.
   *
   * `if (this.sala) return` só protege depois que a sala existe, e ela só nasce
   * no fim de `conectar`, vários `await` adiante (carregar a lib, abrir o
   * microfone, falar com o servidor: segundos, no celular). Duas entradas
   * disparadas nessa janela — o duplo toque do cliente no botão, o React
   * remontando em StrictMode, a tela que reabre a chamada ao trocar de rota —
   * passavam as duas pela guarda e abriam DUAS capturas e DUAS conferências. No
   * celular a segunda captura mata a faixa da primeira (ver o comentário
   * abaixo), e o resultado é entrar na sala mudo, do jeito mais difícil de
   * diagnosticar: tudo na tela diz que deu certo.
   *
   * A trava é levantada ANTES do primeiro `await` e solta no `finally`, para
   * uma entrada que falhou não bloquear a próxima tentativa — que é justamente
   * o que o cliente faz quando o primeiro toque não funciona. */
  async entrar(sala: string, opcoes: OpcoesEntrada = {}, token?: string): Promise<void> {
    /* `this.sala` é null DURANTE uma reconexão — e essa é a janela perigosa.
     *
     * Entre a queda e a religação a sala não existe e `entrando` é falso, então
     * a guarda deixava passar: um toque em "Entrar" nesses segundos (e é
     * exatamente aí que a pessoa toca, porque a tela diz "conectando") abria uma
     * segunda entrada completa, com captura nova, enquanto a primeira ainda ia
     * voltar sozinha. Duas conferências, o mesmo microfone.
     *
     * A guarda é o TEMPORIZADOR, e não `religar`: `religar` fica preenchido
     * desde a primeira tentativa de conexão e não é limpo quando ela FALHA —
     * usá-lo aqui trancaria o botão "Entrar" para sempre justamente depois de
     * uma entrada malsucedida, que é quando a pessoa mais precisa tentar de
     * novo. O temporizador existe só enquanto há religação de fato agendada. */
    if (this.sala || this.entrando || this.temporizadorReconexao !== null) return;
    this.entrando = true;
    try {
      await this.entrarInterno(sala, opcoes, token);
    } finally {
      this.entrando = false;
    }
  }

  private async entrarInterno(sala: string, opcoes: OpcoesEntrada = {}, token?: string): Promise<void> {
    // Tokens do portal usam base64url e podem conter maiúsculas. O Prosody/Jitsi
    // transforma o nome da MUC em minúsculas e rejeita a conferência quando o
    // cliente envia o original misturado ("Invalid conference name"). As duas
    // pontas passam por esta classe, portanto convergem para a mesma sala. O
    // WebSocket de sinalização continua usando o token original, separadamente.
    const salaJitsi = sala.trim().toLowerCase();
    if (!salaJitsi) throw new Error("Identificador da sala vazio.");
    this.desligando = false;
    this.meuNome = (opcoes.nome ?? "").trim();
    this.mudarEstado("conectando");

    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error(
        "O navegador só libera o microfone em conexão segura (https) ou em localhost.",
      );
    }

    const api = await carregarJitsi();
    this.api = api;
    const semWebRtc = api.isWebRtcSupported ? !api.isWebRtcSupported() : false;
    const naoSuportado = api.util?.browser?.isSupported ? !api.util.browser.isSupported() : false;
    if (semWebRtc || naoSuportado) {
      this.mudarEstado("encerrada");
      throw new Error(
        `A chamada não funciona no ${descreverNavegador()}, que está desatualizado. ` +
          "Atualize o Google Chrome pela Play Store e abra o link de novo.",
      );
    }

    /* Microfone e câmera num pedido SÓ, e não em dois.
     *
     * O CELULAR MUDO: ERA DAQUI
     *
     * Antes eram duas capturas: `createLocalTracks(["audio"])` e, logo depois,
     * `createLocalTracks(["video"])`. No desktop isso é inofensivo. No celular
     * não é: o iOS mantém UMA sessão de captura por página, e abrir a segunda
     * ENCERRA as faixas da primeira — a faixa de áudio morre calada, sem erro
     * nenhum. O Chrome Android faz o parecido ao trocar a configuração do
     * dispositivo no meio. O cliente entrava, aparecia em vídeo, e o
     * entrevistador não ouvia nada; sem câmera, a mesma chamada funcionava. Era
     * o "às vezes" do sintoma.
     *
     * Pedindo os dois juntos existe uma captura só, e a faixa de áudio não é
     * derrubada por ninguém. A câmera continua sem poder derrubar a entrevista:
     * se o pedido conjunto falhar (permissão de câmera negada, aparelho sem
     * câmera), cai para áudio puro, que é o que a entrevista realmente exige.
     */
    const querCamera = Boolean(opcoes.camera);
    this.microfoneEscolhido = opcoes.microfoneId;
    this.p2pLigado = opcoes.p2p ?? false;
    const comMicrofone = opcoes.microfoneId ? { micDeviceId: opcoes.microfoneId } : {};
    let faixas: FaixaJitsi[] = [];
    let erroCamera: unknown = null;
    if (querCamera) {
      try {
        faixas = await api.createLocalTracks({
          devices: ["audio", "video"],
          ...comMicrofone,
          resolution: ALTURA_VIDEO,
          constraints: { video: VIDEO_PEDIDO },
        });
      } catch (e) {
        erroCamera = e;
        faixas = [];
      }
    }
    if (!faixas.some((f) => f.getType() === "audio")) {
      // Sem câmera, ou com o pedido conjunto recusado: o microfone sozinho. Se
      // a permissão do microfone for negada, o erro sai limpo daqui, sem deixar
      // conexão pendurada no servidor.
      faixas = await api.createLocalTracks({ devices: ["audio"], ...comMicrofone });
      if (erroCamera && !ehCelular()) {
        try {
          faixas = [...faixas, ...(await abrirVideoComFallback(api))];
          erroCamera = null;
        } catch (e) {
          erroCamera = e;
        }
      }
      if (erroCamera) this.eventos.onErro?.(`${explicarErroCamera(erroCamera)} A chamada segue só com voz.`);
    }
    this.minhaFaixa = faixas.find((f) => f.getType() === "audio") ?? null;
    if (!this.minhaFaixa) throw new Error("Nenhum microfone disponível.");
    this.vigiarMicrofone();
    this.eventos.onFaixaLocal?.(this.minhaFaixa.getTrack());
    document.addEventListener("visibilitychange", this.aoMudarVisibilidade);
    // O retrato inicial da lista; a partir daqui, toda mudança é comparada com
    // ele para decidir se a chamada troca de microfone sozinha.
    void this.conferirDispositivos();
    navigator.mediaDevices?.addEventListener?.("devicechange", this.aoTrocarDispositivos);
    /* `online` é a rede de segurança do caso Wi-Fi↔4G. O Jitsi costuma emitir
     * `CONNECTION_RESTORED`, mas nem sempre — e quando não emite, o único aviso
     * de que a rede voltou é este evento do navegador. */
    window.addEventListener("online", this.aoVoltarRede);
    void this.manterTelaAcesa();

    const camera = faixas.find((f) => f.getType() === "video") ?? null;
    if (camera) {
      await this.aplicarFundo(camera);
      this.minhaCamera = camera;
      this.videos.set("eu", camera.getTrack());
    }

    await this.conectar(api, salaJitsi, token);
  }

  private async aplicarFundo(camera: FaixaJitsi): Promise<void> {
    if (this.papel !== "advogado" || !camera.setEffect) return;
    try {
      await camera.setEffect(criarEfeitoFundo(FUNDO_ADVOGADO, (m) => this.eventos.onErro?.(m)));
    } catch {
      this.eventos.onErro?.("Não foi possível aplicar o fundo virtual. A câmera aparece sem o fundo.");
    }
  }

  private async abrirCamera(api: ApiJitsi): Promise<void> {
    if (this.papel === "advogado") preCarregarFundoVirtual(FUNDO_ADVOGADO);
    const faixas = await abrirVideoComFallback(api);
    this.minhaCamera = faixas.find((f) => f.getType() === "video") ?? null;
    if (this.minhaCamera) await this.aplicarFundo(this.minhaCamera);
    if (this.minhaCamera) this.videos.set("eu", this.minhaCamera.getTrack());
  }

  /** Liga ou desliga a câmera no meio da chamada. Devolve se ficou ligada. */
  async alternarCamera(): Promise<boolean> {
    // Clique repetido durante a troca não vira segunda captura: devolve o que
    // está valendo agora, e a troca em curso segue para o seu fim.
    if (this.mexendoVideo) return this.minhaCamera !== null;
    this.mexendoVideo = true;
    try {
      return await this.alternarCameraInterno();
    } finally {
      this.mexendoVideo = false;
    }
  }

  private async alternarCameraInterno(): Promise<boolean> {
    if (!this.api) return false;

    /* Ligar a câmera durante o compartilhamento encerra o compartilhamento:
     * é uma faixa de vídeo por participante. `pararTela` já devolve a câmera
     * quando ela estava ligada antes, então aqui só resta o caso de acender. */
    if (this.minhaTela) {
      const voltaSozinha = this.cameraAntesDaTela;
      await this.pararTela();
      if (voltaSozinha) return this.minhaCamera !== null;
    }

    if (this.minhaCamera) {
      const faixa = this.minhaCamera;
      this.minhaCamera = null;
      this.videos.delete("eu");
      // Solta o dispositivo, e não só para de enviar: com a câmera apenas
      // silenciada, a luz do notebook fica acesa e ninguém confia nisso.
      await this.sala?.removeTrack(faixa).catch(() => {});
      await faixa.dispose().catch(() => {});
      this.anunciarParticipantes();
      return false;
    }

    /* Aqui a captura de vídeo é inevitavelmente separada — a chamada já está de
     * pé —, então no celular ela ainda pode derrubar o microfone (ver o comentário
     * em `entrar`). Quem conserta é `vigiarMicrofone`: a faixa morta dispara
     * `ended` e volta republicada, sem o usuário precisar desligar a conversa. */
    try {
      await this.abrirCamera(this.api);
    } catch (e) {
      this.eventos.onErro?.(explicarErroCamera(e));
      return false;
    }
    if (this.minhaCamera && this.sala) await this.sala.addTrack(this.minhaCamera);
    this.anunciarParticipantes();
    return this.minhaCamera !== null;
  }

  /* Mostra ou para de mostrar a tela. Devolve se ficou compartilhando.
   *
   * A TELA ENTRA NO LUGAR DA CÂMERA, NÃO AO LADO
   *
   * O Jitsi aceita uma faixa de vídeo por participante: um segundo `addTrack`
   * de vídeo é recusado ("Cannot add second video track"). Então a câmera sai
   * enquanto a tela está no ar e volta sozinha quando ela para — que é também
   * o que o advogado espera, porque foi ele quem tinha a câmera ligada antes.
   *
   * QUEM PARA O COMPARTILHAMENTO NÃO É SÓ O NOSSO BOTÃO
   *
   * O navegador desenha a própria barra "Parar de compartilhar", e é nela que
   * a maioria clica. Sem ouvir o `ended` da faixa, o nosso botão continuaria
   * dizendo "Parar de mostrar" com nada sendo mostrado, e a câmera não
   * voltaria. Por isso o encerramento passa pelo mesmo caminho nos dois casos.
   */
  async alternarTela(): Promise<boolean> {
    // Mesma trava da câmera, e pelo mesmo motivo: as duas disputam a única
    // faixa de vídeo do participante, então a trava tem de ser a mesma.
    if (this.mexendoVideo) return this.minhaTela !== null;
    this.mexendoVideo = true;
    try {
      return await this.alternarTelaInterno();
    } finally {
      this.mexendoVideo = false;
    }
  }

  private async alternarTelaInterno(): Promise<boolean> {
    if (!this.api) return false;
    if (this.minhaTela) {
      await this.pararTela();
      return false;
    }

    let faixa: FaixaJitsi | undefined;
    try {
      const faixas = await this.api.createLocalTracks({ devices: ["desktop"] });
      faixa = faixas.find((f) => f.getType() === "video");
    } catch {
      /* Cancelar o seletor de janela do navegador cai aqui e NÃO é erro: a
       * pessoa desistiu. Avisar "falhou" a faria procurar problema onde não
       * há. Só a falta de faixa depois de escolher merece aviso. */
      return false;
    }
    if (!faixa) {
      this.eventos.onErro?.("O navegador não devolveu a tela para compartilhar.");
      return false;
    }

    this.cameraAntesDaTela = this.minhaCamera !== null;
    if (this.minhaCamera) {
      const camera = this.minhaCamera;
      this.minhaCamera = null;
      await this.sala?.removeTrack(camera).catch(() => {});
      await camera.dispose().catch(() => {});
    }

    this.minhaTela = faixa;
    this.videos.set("eu", faixa.getTrack());
    // A barra do próprio navegador. `once`: a faixa termina uma vez só.
    faixa.getTrack().addEventListener("ended", () => void this.pararTela(), { once: true });

    if (this.sala) {
      try {
        await this.sala.addTrack(faixa);
      } catch {
        await this.pararTela();
        this.eventos.onErro?.("Não foi possível enviar a tela para a chamada.");
        return false;
      }
    }
    this.anunciarParticipantes();
    return true;
  }

  private async pararTela(): Promise<void> {
    const faixa = this.minhaTela;
    if (!faixa) return;
    this.minhaTela = null;
    this.videos.delete("eu");
    await this.sala?.removeTrack(faixa).catch(() => {});
    await faixa.dispose().catch(() => {});

    // A câmera volta ao estado anterior — mas não durante o desligamento, que
    // já está soltando tudo e reabriria o dispositivo para fechá-lo em seguida.
    if (this.cameraAntesDaTela && this.api && !this.desligando) {
      try {
        await this.abrirCamera(this.api);
        if (this.minhaCamera && this.sala) await this.sala.addTrack(this.minhaCamera);
      } catch {
        this.eventos.onErro?.("A tela parou, mas a câmera não voltou. Ligue-a de novo.");
      }
    }
    this.cameraAntesDaTela = false;
    this.anunciarParticipantes();
  }

  /* `religando` muda o que uma falha SIGNIFICA para a tela.
   *
   * Na primeira entrada, não conseguir falar com o servidor é o fim: quem
   * clicou precisa saber que não entrou. Numa religação automática é só mais
   * uma tentativa que não vingou — a próxima já está agendada, e marcar
   * "encerrada" no meio faz `ativa` virar falso por um instante, o que
   * desmonta o painel flutuante e pisca a chamada inteira na tela de quem está
   * esperando pacientemente, como a própria mensagem mandou. */
  private conectar(api: ApiJitsi, sala: string, token?: string, religando = false): Promise<void> {
    const eventos = api.events.connection;
    const conexao = new api.JitsiConnection(
      "level33-chamadas",
      /* `||` e não `??`: sem `AUTH_TYPE=jwt` no Jitsi o backend devolve token
       * VAZIO, e string vazia não é `null` — o `??` a deixaria passar, e a lib
       * tentaria autenticar com um JWT em branco em vez de entrar como anônimo. */
      token || null,
      {
        hosts: { domain: "meet.jitsi", muc: "muc.meet.jitsi" },
        // O `room` na query é o que permite ao Prosody escolher o shard certo
        // quando há mais de um; num servidor só, é inofensivo e recomendado.
        serviceUrl: `${BASE_JITSI.replace(/^http/, "ws")}/xmpp-websocket?room=${encodeURIComponent(sala)}`,
      },
    );
    this.conexao = conexao;
    // O que a reconexão automática vai precisar, guardado no único ponto em que
    // as três peças estão à mão ao mesmo tempo.
    this.religar = { api, sala, token };

    return new Promise<void>((ok, falhou) => {
      /* A TENTATIVA QUE ESTOUROU O PRAZO PRECISA MORRER DE VERDADE.
       *
       * Antes o timeout apenas REJEITAVA a promessa e ia embora: a conexão
       * continuava viva, tentando. Quando ela se estabelecia tarde — e num
       * celular em rede ruim isso passa dos 25 segundos com frequência —, o
       * `CONNECTION_ESTABLISHED` chegava e entrava na sala assim mesmo, depois
       * de quem chamou já ter tratado a entrada como falha e, quase sempre,
       * tocado em "Entrar" de novo. O resultado eram DUAS conferências vivas na
       * mesma aba, disputando a mesma faixa de microfone: a sala mostrava a
       * pessoa duas vezes e o áudio ia por uma das duas, na sorte.
       *
       * Com a reconexão automática isso deixou de ser raro, porque cada
       * religação abre uma tentativa nova. A bandeira fecha a porta: a tentativa
       * descartada não entra em sala nenhuma, e a conexão pendente é desfeita. */
      let descartada = false;
      const limite = window.setTimeout(() => {
        descartada = true;
        void conexao.disconnect().catch(() => {});
        if (!religando) this.mudarEstado("encerrada");
        falhou(
          new Error(
            "O servidor de chamadas não respondeu. Confira a internet (troque entre Wi-Fi e 4G) " +
              `e tente de novo. Se continuar, atualize o Google Chrome (${descreverNavegador()}).`,
          ),
        );
      }, LIMITE_SERVIDOR_MS);
      conexao.addEventListener(eventos.CONNECTION_ESTABLISHED, () => {
        if (descartada) return;
        window.clearTimeout(limite);
        /* O orçamento de tentativas é por QUEDA, não por chamada: uma conexão
         * que se restabeleceu prova que o caminho existe. Sem zerar aqui, uma
         * entrevista longa com três oscilações espaçadas esgotaria o limite e
         * a quarta queda — horas depois — seria tratada como definitiva. */
        this.tentativasReconexao = 0;
        this.entrarNaSala(api, sala);
        ok();
      });
      conexao.addEventListener(eventos.CONNECTION_FAILED, () => {
        window.clearTimeout(limite);
        // Numa religação o estado fica em "conectando": quem agendou a próxima
        // tentativa é o `catch` de `agendarReconexao`, e é ele que decide
        // quando a chamada está mesmo encerrada (ver `MAX_RECONEXOES`).
        if (!religando) this.mudarEstado("encerrada");
        falhou(new Error("Não foi possível falar com o servidor de chamadas."));
      });
      conexao.addEventListener(eventos.CONNECTION_DISCONNECTED, () => {
        if (this.desligando) return;
        /* A QUEDA DO SERVIDOR NÃO É MAIS O FIM DA CHAMADA.
         *
         * Antes isto marcava "encerrada" e pronto: o Wi-Fi que oscila por dez
         * segundos, o celular que troca de torre, o contêiner do Jitsi que
         * reinicia — todos derrubavam a entrevista em definitivo, e a única
         * saída era o cliente (no celular, no meio de um dia ruim) descobrir
         * sozinho que precisava abrir o link de novo. A faixa de microfone
         * continua viva aqui dentro, então reconectar é barato e recupera a
         * conversa sem pedir nada a ninguém. */
        this.agendarReconexao();
      });
      conexao.connect();
    });
  }

  /* Volta para a sala sozinho depois de uma queda, com espera crescente.
   *
   * A espera cresce (3s, 6s, 12s…) porque as duas causas comuns pedem tempos
   * diferentes: a oscilação de rede volta em segundos, e o servidor que
   * reiniciou leva a primeira meia dúzia. Tentar de meio em meio segundo não
   * apressa nenhuma das duas e ainda martela o servidor que está subindo.
   *
   * Depois de `MAX_RECONEXOES` a chamada é dada por encerrada de verdade: uma
   * pílula "reconectando…" que nunca converge é pior que o aviso honesto de que
   * é preciso abrir o link de novo. */
  private agendarReconexao(): void {
    const religar = this.religar;
    if (this.desligando || !religar || this.temporizadorReconexao !== null) return;

    if (this.tentativasReconexao >= MAX_RECONEXOES) {
      this.eventos.onErro?.(
        "A conexão com o servidor de chamadas caiu e não voltou. Abra o link da chamada de novo.",
      );
      /* DESISTIR TAMBÉM É SOLTAR O MICROFONE.
       *
       * Antes isto só mudava o rótulo para "encerrada" e ia embora: a captura
       * continuava aberta, com a luz do aparelho acesa, gravando uma sala que
       * não existe mais. Numa conversa de escritório de advocacia é o defeito
       * mais grave dos três (privacidade, bateria e confiança), e o mais fácil
       * de não notar — a tela já dizia "encerrada", então ninguém procura.
       *
       * `desligar` solta faixas, ouvintes, wake lock e temporizadores; o estado
       * volta a "encerrada" logo depois porque "fora" apagaria da tela o aviso
       * que explica o que aconteceu. A mensagem já saiu acima, antes de soltar,
       * para não depender de nada que o desligamento limpa. */
      this.desligar();
      this.mudarEstado("encerrada");
      return;
    }

    const espera = ESPERA_RECONEXAO_MS * 2 ** this.tentativasReconexao;
    this.tentativasReconexao += 1;
    this.mudarEstado("conectando");
    this.eventos.onErro?.("A chamada caiu e está voltando sozinha. Continue nesta tela.");

    this.temporizadorReconexao = window.setTimeout(() => {
      this.temporizadorReconexao = null;
      if (this.desligando) return;

      // A conferência e a conexão velhas não servem mais: soltá-las antes evita
      // dois transportes disputando a mesma faixa de microfone.
      const anterior = this.conexao;
      this.sala = null;
      this.conexao = null;
      /* O QUE A CONFERÊNCIA MORTA DEIXA PARA TRÁS.
       *
       * `TRACK_REMOVED` não dispara para uma conferência que caiu — ela não se
       * despede. Sem soltar à mão, os `<audio>` do outro lado ficam pendurados
       * no documento e no mapa `remotas`, e os retratos guardam ids de
       * participante que não existem mais na sala nova.
       *
       * Não é só vazamento: `vigiarAudioRemoto` decide se avisa "o áudio da
       * outra pessoa não chegou" olhando `remotas.size > 0`. Com os elementos
       * mortos ali dentro, ele conclui que o áudio chegou — e cala justamente
       * na reconexão, que é quando o áudio mais falha. */
      this.soltarRemotas();
      void anterior?.disconnect().catch(() => {});

      void this.conectar(religar.api, religar.sala, religar.token, true).catch(() => {
        // Falhou de novo: a próxima espera já sai dobrada.
        this.agendarReconexao();
      });
    }, espera);
  }

  private entrarNaSala(api: ApiJitsi, nome: string): void {
    const ev = api.events.conference;
    const sala = this.conexao!.initJitsiConference(nome, {
      /* P2P DESLIGADO — e isto é decisão de confiabilidade, não de desempenho.
       *
       * Com P2P ligado (como estava até 16/09/2026), uma sala de duas pessoas
       * tenta ligar os dois navegadores DIRETAMENTE. É mais barato e tem menos
       * latência, e funciona bem entre dois Wi-Fi domésticos. Só que o cliente
       * entra pelo celular, e no 4G de operadora o NAT é simétrico: o caminho
       * direto não fecha. Existe fallback de P2P para o bridge, mas é
       * justamente ele que falha calado — a sala abre, os retratos aparecem, o
       * cronômetro anda e ninguém ouve ninguém. Foi o sintoma de 15/09/2026.
       *
       * Pelo bridge, o celular não precisa alcançar o outro navegador: ele manda
       * UDP para um IP PÚBLICO conhecido (o JVB), que é tráfego de saída comum e
       * atravessa NAT de operadora sem drama. Trocamos banda do servidor —
       * numa chamada de duas pessoas, desprezível — por áudio que chega.
       *
       * Isto NÃO substitui o TURN, que continua pendente: rede corporativa que
       * bloqueia UDP em porta alta ainda precisa do relay em 443/TCP (ver
       * `deploy/jitsi/coturn.env.exemplo`). Resolve o caso do 4G, que é o
       * comum; não resolve o caso do UDP bloqueado, que é o raro.
       *
       * O VALOR VEM DO SERVIDOR, E ISSO É O INTERRUPTOR DE EMERGÊNCIA
       *
       * Desligar o P2P aposta tudo no videobridge: se ele estiver inalcançável
       * (`JVB_ADVERTISE_IPS` errado, UDP 10000 fechada no firewall), não sobra
       * caminho nenhum e TODA chamada emudece — inclusive as que hoje funcionam.
       * Em 16/09/2026 não foi possível confirmar de fora que a UDP 10000
       * responde. Por isso o valor não é constante nem `NEXT_PUBLIC_`: ele
       * chega na resposta da sala, e religar o P2P é mexer em `CHAMADA_P2P` e
       * reiniciar a API — segundos, não um pipeline de build. */
      p2p: { enabled: this.p2pLigado },
    });
    this.sala = sala;

    sala.on(ev.CONFERENCE_JOINED, () => {
      // O nome vai antes das faixas: quem já está na sala recebe o "entrou"
      // junto do nome, em vez de ver um "participante" anônimo por um segundo.
      if (this.meuNome) sala.setDisplayName(this.meuNome);
      this.pedirQualidade(sala);
      /* Publicação de áudio é confirmada: em alguns navegadores a sala entra
       * antes de o dispositivo terminar de ficar disponível. Antes uma falha
       * aqui era silenciosa e a chamada parecia normal, mas sem voz de saída.
       *
       * NA RECONEXÃO, PUBLICAR A MESMA FAIXA NÃO BASTA.
       *
       * `this.minhaFaixa` continua sendo o objeto que já foi anexado à
       * conferência ANTERIOR, e a lib recusa reaproveitá-lo numa conferência
       * nova. Sem o resgate abaixo, a religação automática terminava com a
       * pessoa dentro da sala e muda — com uma mensagem mandando apertar
       * "Reativar áudio" à mão, o que anula o sentido de reconectar sozinho.
       * `reativarAudio` recria a faixa do zero e republica, que é o que o
       * "sair e entrar" fazia. */
      void this.publicarMicrofone(sala).then((publicado) => {
        if (publicado || this.desligando || this.mudoAtual) return;
        return this.reativarAudio().then(
          () => undefined,
          () => undefined,
        );
      });
      // A câmera ia sem `catch`: falhar aqui virava rejeição solta no console e
      // uma chamada sem imagem que ninguém sabia explicar.
      if (this.minhaCamera) {
        void sala.addTrack(this.minhaCamera).catch(() => {
          this.eventos.onErro?.("A câmera não voltou depois da reconexão. Ligue-a de novo.");
        });
      }
      this.mudarEstado(sala.getParticipantCount() > 0 ? "conectando" : "aguardando");
      if (sala.getParticipantCount() > 0) this.vigiarAudioRemoto();
      this.anunciarParticipantes();
    });

    sala.on(ev.TRACK_ADDED, (...args: unknown[]) => {
      const faixa = args[0] as FaixaJitsi;
      if (faixa.isLocal()) return;

      if (faixa.getType() === "video") {
        const de = faixa.getParticipantId?.();
        if (de) {
          this.videos.set(de, faixa.getTrack());
          // `videoType` é o que separa rosto de tela. Sem isto a tela do outro
          // lado chegaria recortada como se fosse um retrato.
          if (faixa.getVideoType?.() === "desktop") this.telas.add(de);
          else this.telas.delete(de);
          this.anunciarParticipantes();
        }
        return;
      }
      this.receberFaixa(faixa);
    });

    sala.on(ev.TRACK_REMOVED, (...args: unknown[]) => {
      const faixa = args[0] as FaixaJitsi;
      if (faixa.getType() === "video") {
        const de = faixa.getParticipantId?.();
        if (de) {
          this.videos.delete(de);
          this.telas.delete(de);
          this.anunciarParticipantes();
        }
        return;
      }
      this.soltarFaixa(faixa);
    });

    sala.on(ev.USER_JOINED, () => {
      if (this.remotas.size === 0) this.vigiarAudioRemoto();
      this.anunciarParticipantes();
    });
    sala.on(ev.DISPLAY_NAME_CHANGED, () => this.anunciarParticipantes());

    /* A CÂMERA DO OUTRO LADO LIGA E DESLIGA, E A TELA PRECISA SABER.
     *
     * `TRACK_ADDED`/`TRACK_REMOVED` não cobrem isto: quando o cliente desliga a
     * câmera pelo botão dele, a faixa continua publicada e apenas fica MUTED —
     * nenhum dos dois eventos dispara. O retrato seguia mostrando o último
     * quadro recebido, congelado, e o advogado ficava esperando a imagem
     * "voltar" de uma câmera que já estava desligada. Tratando o mute, o
     * retrato cai para a inicial do nome, que é a verdade. */
    if (ev.TRACK_MUTE_CHANGED) {
      sala.on(ev.TRACK_MUTE_CHANGED, (...args: unknown[]) => {
        const faixa = args[0] as FaixaJitsi;
        if (faixa.isLocal() || faixa.getType() !== "video") return;
        const de = faixa.getParticipantId?.();
        if (!de) return;
        if (faixa.isMuted?.()) {
          this.videos.delete(de);
          this.telas.delete(de);
        } else {
          this.videos.set(de, faixa.getTrack());
          if (faixa.getVideoType?.() === "desktop") this.telas.add(de);
        }
        this.anunciarParticipantes();
      });
    }

    /* "ENTROU NA SALA MAS NINGUÉM OUVE" TEM UM EVENTO PRÓPRIO, E ELE ERA IGNORADO.
     *
     * Quando a mídia do outro lado não encontra caminho, a sinalização continua
     * de pé: o retrato aparece, o nome aparece, o cronômetro anda. O único
     * aviso é este evento mudando o status para `interrupted`. Sem ouvi-lo, o
     * sintoma ficava exatamente como descrito no CHAMADA.md — "parece que deu
     * certo" — e os dois lados ficavam falando sozinhos até alguém desistir.
     *
     * Aqui não se tenta consertar: o remédio (trocar de rede, TURN) está fora
     * do alcance do navegador. O que se faz é DIZER, que é o que falta. */
    if (ev.PARTICIPANT_CONN_STATUS_CHANGED) {
      sala.on(ev.PARTICIPANT_CONN_STATUS_CHANGED, (...args: unknown[]) => {
        if (this.desligando) return;
        const situacao = String(args[1] ?? "");
        if (situacao === "interrupted" || situacao === "inactive") {
          this.eventos.onErro?.(
            "A conexão da outra pessoa está instável e o áudio dela pode não estar chegando. " +
              "Peça para ela trocar entre Wi-Fi e 4G se o silêncio continuar.",
          );
        }
      });
    }

    sala.on(ev.USER_LEFT, (...args: unknown[]) => {
      this.videos.delete(String(args[0]));
      this.telas.delete(String(args[0]));
      if (sala.getParticipantCount() === 0) this.mudarEstado("aguardando");
      this.anunciarParticipantes();
    });

    sala.on(ev.CONFERENCE_FAILED, (...args: unknown[]) => {
      /* A SALA RECUSOU — E O BOTÃO "ENTRAR" PRECISA VOLTAR A FUNCIONAR.
       *
       * `this.sala` é preenchido logo acima, ANTES do `join()`, porque os
       * ouvintes precisam do objeto. Quando a entrada falha, essa atribuição
       * fica para trás apontando para uma conferência que nunca entrou — e
       * `entrar()` começa com `if (this.sala) return`. O efeito era o pior tipo
       * de defeito: a tela dizia "chamada encerrada", a pessoa tocava em Entrar
       * e NADA acontecia, sem erro novo, sem log, para sempre. O único jeito de
       * sair era desligar (botão que, nesse estado, ninguém procura).
       *
       * Soltar a referência aqui devolve a segunda tentativa, que numa recusa
       * transitória (o Prosody ainda subindo, token que acabou de vencer) é
       * justamente a que funciona. */
      if (this.sala === sala) this.sala = null;
      this.mudarEstado("encerrada");
      this.eventos.onErro?.(
        `A sala recusou a entrada (${String(args[0])}). Toque em entrar de novo; se repetir, avise o suporte.`,
      );
    });

    /* TROCAR DE REDE NO MEIO DA CHAMADA — Wi-Fi↔4G, o caso do corredor.
     *
     * O cliente sai de casa, o celular larga o Wi-Fi e entra no 4G. A faixa de
     * áudio NÃO morre nisso: ela continua `live`, o dispositivo é o mesmo.
     * Então nada do que já existe aqui acorda — `ended` e `mute` não disparam
     * (a faixa está viva) e `devicechange` também não (o microfone não mudou).
     * O que morre é o TRANSPORTE: o ICE perde o caminho e renegocia noutro
     * endereço. A sinalização volta, os retratos continuam, e a voz de saída
     * fica presa no transporte velho. Só sair e entrar resolvia, porque é isso
     * que recria e republica a faixa.
     *
     * Republicar é a mesma coisa que sair e entrar faz com o microfone, sem
     * derrubar a sala. `restabelecerAudio` espera o ICE assentar antes, e tem
     * janela mínima: a troca de rede dispara estes eventos em rajada.
     *
     * Os três são opcionais (`ev.X &&`) porque o nome do evento pertence à
     * versão da lib que o SERVIDOR entrega, e ela é atualizada por fora deste
     * repositório. Assinar um evento inexistente quebraria a entrada na sala. */
    if (ev.CONNECTION_INTERRUPTED) {
      sala.on(ev.CONNECTION_INTERRUPTED, () => {
        if (this.desligando) return;
        this.eventos.onErro?.("A conexão oscilou. Continue na tela — estamos religando o áudio.");
      });
    }
    if (ev.CONNECTION_RESTORED) {
      sala.on(ev.CONNECTION_RESTORED, () => void this.restabelecerAudio("a rede mudou"));
    }
    /* Celular que dormiu e acordou cai no mesmo buraco: o transporte morreu
     * enquanto a tela estava apagada. */
    if (ev.SUSPEND_DETECTED) {
      sala.on(ev.SUSPEND_DETECTED, () => void this.restabelecerAudio("o aparelho voltou do repouso"));
    }
    /* `iceFailed` é o caso em que o transporte morreu e NÃO se restabeleceu
     * sozinho — a troca de rede que não fecha caminho novo. `CONNECTION_RESTORED`
     * nunca chega aqui, justamente porque nada foi restaurado, então sem esta
     * linha o áudio ficaria mudo esperando um evento que não vem. */
    if (ev.ICE_FAILED) {
      sala.on(ev.ICE_FAILED, () => void this.restabelecerAudio("a rota de áudio caiu"));
    }

    sala.join();
  }

  /* Pede a qualidade de imagem dos DOIS lados do fluxo.
   *
   * Enviar em 720p não basta: o que chega a este navegador é a camada que ELE
   * pede, e sem pedido a lib assume a mais baixa do simulcast (180p). Era por
   * isso que os dois lados apareciam borrados mesmo com câmera boa e banda
   * sobrando — cada um mandava bem e recebia mal.
   *
   * Tudo aqui é opcional e engolido em caso de erro: qualidade de imagem não
   * pode derrubar uma chamada que já está de pé. Pior nítido do que mudo. */
  private pedirQualidade(sala: ConferenciaJitsi): void {
    try {
      sala.setReceiverVideoConstraints?.({
        // `lastN: -1` = receber todo mundo. Numa sala de dois, restringir não
        // economiza nada e ainda apaga o retrato de quem entrar em terceiro.
        lastN: -1,
        defaultConstraints: { maxHeight: ALTURA_RECEPCAO },
      });
    } catch {
      /* versão da lib sem constraint de recepção: segue no padrão dela */
    }
    try {
      void sala.setSenderVideoConstraint?.(ALTURA_VIDEO);
    } catch {
      /* idem, do lado do envio */
    }
  }

  private async publicarMicrofone(sala: ConferenciaJitsi): Promise<boolean> {
    const faixa = this.minhaFaixa;
    if (!faixa) return false;
    /* QUEM PEDIU SILÊNCIO CONTINUA EM SILÊNCIO — INCLUSIVE DEPOIS DE UMA QUEDA.
     *
     * Isto aqui abria o microfone sem perguntar (`enabled = true`), e até existir
     * reconexão automática era quase inofensivo: só rodava na entrada, quando
     * ninguém tinha pedido mudo ainda. Com a religação sozinha virou outra coisa
     * — a pessoa desliga o microfone para falar com alguém do lado, a conexão
     * oscila, a chamada volta por conta própria e ela é publicada FALANDO, sem
     * ter tocado em nada e sem nada na tela dizendo isso. Numa entrevista de
     * advocacia, onde o cliente desliga o microfone justamente para o que não
     * quer que seja ouvido, é o pior defeito possível.
     *
     * O `mute()` depois do `addTrack` não é redundante com o `enabled`: o
     * primeiro é o estado que o Jitsi anuncia aos outros participantes (é dele
     * que sai o ícone de mudo do outro lado), o segundo é a faixa local parar de
     * entregar amostras. Sem os dois, ou vaza som, ou o outro lado vê alguém
     * "falando" mudo. */
    const aberto = !this.mudoAtual;
    faixa.getTrack().enabled = aberto;
    try {
      await sala.addTrack(faixa);
      if (!aberto) await faixa.mute().catch(() => {});
      return true;
    } catch {
      await new Promise<void>((ok) => window.setTimeout(ok, 500));
    }
    try {
      faixa.getTrack().enabled = aberto;
      await sala.addTrack(faixa);
      if (!aberto) await faixa.mute().catch(() => {});
      return true;
    } catch {
      this.eventos.onErro?.("O microfone não foi publicado na chamada. Use “Reativar áudio” sem desligar a conversa.");
      return false;
    }
  }

  /* O microfone pode MORRER no meio da chamada, e no celular isso é rotina.
   *
   * Bloqueio de tela, troca de app, uma ligação telefônica entrando, o fone de
   * ouvido saindo do pareamento: o sistema tira o microfone da página. A faixa
   * dispara `ended` (morreu) ou `mute` (parou de entregar áudio) e o Jitsi
   * continua publicando uma faixa que não carrega som nenhum — a chamada segue
   * com cara de normal, o cronômetro andando, e o entrevistador sem ouvir mais
   * nada. Era o outro caminho para o mesmo sintoma, e o único remédio era o
   * botão "Reativar áudio", que só existe se alguém desconfiar de usá-lo.
   *
   * `ended` é definitivo, então recupera na hora. `mute` costuma ser passageiro
   * (volta com `unmute` ao trazer a aba de volta), por isso a espera antes de
   * recriar a faixa — recriar a cada ida e volta de aba seria pior que o mal.
   */
  private vigiarMicrofone(): void {
    const faixa = this.minhaFaixa;
    if (!faixa) return;
    const nativa = faixa.getTrack();

    nativa.addEventListener(
      "ended",
      () => void this.recuperarMicrofone(nativa),
      { once: true },
    );
    nativa.addEventListener("mute", () => {
      window.setTimeout(() => {
        if (nativa.muted) void this.recuperarMicrofone(nativa);
      }, ESPERA_MUDO_MS);
    });
  }

  private async recuperarMicrofone(nativa: MediaStreamTrack): Promise<void> {
    // Só a faixa VIGENTE interessa: um evento atrasado da faixa antiga não pode
    // derrubar a que acabou de entrar no lugar dela.
    if (this.desligando || !this.sala || this.recuperandoAudio) return;
    if (document.visibilityState !== "visible") return;
    if (this.minhaFaixa?.getTrack() !== nativa) return;
    // Mudo por escolha do usuário não é defeito. Ressuscitar a faixa aqui
    // devolveria a voz de quem pediu para não ser ouvido.
    if (this.mudoAtual) return;

    this.recuperandoAudio = true;
    try {
      const ok = await this.reativarAudio();
      if (ok) {
        this.eventos.onErro?.(
          "O microfone caiu e foi reaberto sozinho. Confira se o outro lado voltou a ouvir você.",
        );
      }
    } catch {
      this.eventos.onErro?.(
        "O microfone foi tomado por outro aplicativo e não voltou. Use “Reativar áudio” para tentar de novo.",
      );
    } finally {
      this.recuperandoAudio = false;
    }
  }

  /* Republica o microfone depois de uma troca de rede ou de um despertar.
   *
   * Não basta conferir se a faixa está viva: nesse cenário ela ESTÁ viva, e
   * mesmo assim não chega ao bridge — o problema é o transporte, não a captura.
   * Por isso aqui se recria e republica sem perguntar, que é o equivalente a
   * "sair e entrar" aplicado só ao áudio.
   *
   * Mudo por escolha não é tocado: devolveria a voz de quem pediu silêncio. */
  private async restabelecerAudio(motivo: string): Promise<void> {
    if (this.desligando || !this.sala || this.recuperandoAudio || this.mudoAtual) return;

    const agora = Date.now();
    if (agora - this.ultimoRestabelecimento < ESPERA_REPUBLICAR_MS) return;
    this.ultimoRestabelecimento = agora;

    this.recuperandoAudio = true;
    try {
      await new Promise<void>((ok) => window.setTimeout(ok, ESPERA_TRANSPORTE_MS));
      // A espera abre uma janela: desligar, mutar ou sair da sala no meio dela
      // são todos possíveis, e republicar depois disso seria errado.
      if (this.desligando || !this.sala || this.mudoAtual) return;
      if (await this.reativarAudio()) {
        this.eventos.onErro?.(
          `A conexão mudou (${motivo}) e o seu microfone foi religado sozinho. ` +
            "Fale e confira se a barra “Sua voz” se mexe.",
        );
      }
    } catch {
      this.eventos.onErro?.(
        "A conexão mudou e o microfone não voltou sozinho. Toque em “Reativar áudio”.",
      );
    } finally {
      this.recuperandoAudio = false;
    }
  }

  private async manterTelaAcesa(): Promise<void> {
    if (this.desligando || this.travaTela || document.visibilityState !== "visible") return;
    if (!("wakeLock" in navigator)) return;
    try {
      const trava = await navigator.wakeLock.request("screen");
      if (this.desligando) {
        void trava.release().catch(() => {});
        return;
      }
      this.travaTela = trava;
      trava.addEventListener("release", () => {
        if (this.travaTela === trava) this.travaTela = null;
      }, { once: true });
    } catch {
      this.travaTela = null;
    }
  }

  private async retomarAoVoltar(): Promise<void> {
    if (document.visibilityState !== "visible" || this.desligando || !this.sala) return;
    void this.manterTelaAcesa();
    for (const audio of this.remotas.values()) void audio.play().catch(() => {});
    const nativa = this.minhaFaixa?.getTrack();
    if (!nativa) {
      if (!this.mudoAtual) await this.recuperarMicrofoneAusente();
      return;
    }
    if (nativa.readyState === "ended") {
      await this.recuperarMicrofone(nativa);
      return;
    }
    if (nativa.muted) {
      window.setTimeout(() => {
        if (nativa.muted || nativa.readyState === "ended") void this.recuperarMicrofone(nativa);
      }, ESPERA_MUDO_MS);
    }
  }

  private async recuperarMicrofoneAusente(): Promise<void> {
    if (this.recuperandoAudio) return;
    this.recuperandoAudio = true;
    try {
      await this.reativarAudio();
    } catch {
      this.eventos.onErro?.(
        "O microfone não voltou depois que a tela apagou. Use “Reativar áudio” para tentar de novo.",
      );
    } finally {
      this.recuperandoAudio = false;
    }
  }

  /* Abre uma faixa de áudio, caindo para o padrão se o dispositivo pedido sumiu.
   *
   * Insistir no `micDeviceId` escolhido seria o pior dos mundos justamente no
   * caso mais comum de troca: o fone que se desconectou É o dispositivo pedido,
   * e `createLocalTracks` nele falha. A chamada ficaria sem voz por fidelidade a
   * um aparelho que não existe mais. O padrão do sistema é o substituto que o
   * próprio navegador já elegeu. */
  private async abrirAudio(microfoneId: string | undefined): Promise<FaixaJitsi[]> {
    if (!this.api) throw new Error("Chamada não iniciada.");
    if (microfoneId) {
      try {
        return await this.api.createLocalTracks({ devices: ["audio"], micDeviceId: microfoneId });
      } catch {
        /* cai para o padrão, abaixo */
      }
    }
    return this.api.createLocalTracks({ devices: ["audio"] });
  }

  /** Reabre e republica o microfone sem derrubar vídeo ou sala.
   *
   *  `microfoneId` troca de dispositivo; omitido, reabre o que está em uso. */
  async reativarAudio(microfoneId?: string): Promise<boolean> {
    if (!this.api || !this.sala) return false;
    const anterior = this.minhaFaixa;
    if (anterior) {
      await this.sala.removeTrack(anterior).catch(() => {});
      await anterior.dispose().catch(() => {});
    }
    const faixas = await this.abrirAudio(microfoneId ?? this.microfoneEscolhido);
    this.minhaFaixa = faixas.find((f) => f.getType() === "audio") ?? null;
    if (!this.minhaFaixa) throw new Error("Nenhum microfone disponível.");
    /* O que passa a valer é o que está NO AR, e não o que foi pedido: se o
     * pedido falhou e caímos no padrão, uma recuperação futura precisa reabrir
     * este, senão toda troca seguinte tentaria de novo o aparelho que sumiu. */
    this.microfoneEscolhido =
      this.minhaFaixa.getTrack().getSettings().deviceId ?? microfoneId ?? this.microfoneEscolhido;
    this.mudoAtual = false;
    this.vigiarMicrofone();
    this.eventos.onFaixaLocal?.(this.minhaFaixa.getTrack());
    return this.publicarMicrofone(this.sala);
  }

  /* O cliente TROCA de microfone no meio da chamada, e isso não é acidente.
   *
   * Ele começa no microfone do celular, o atendimento se alonga e ele conecta o
   * fone Bluetooth; ou o fone estava conectado e a bateria acaba. Até aqui nada
   * disso era percebido: `vigiarMicrofone` só acorda quando a faixa MORRE
   * (`ended`/`mute`), e conectar um fone novo não mata a faixa antiga — o
   * microfone do aparelho continua vivo e publicando. A chamada seguia no
   * dispositivo velho, e o único remédio era desligar e entrar de novo.
   *
   * `devicechange` é o evento que faltava. Ele avisa que a LISTA mudou, não o
   * que mudou nela, então a comparação com o retrato anterior é que diz se um
   * aparelho entrou (passa a usá-lo: conectar um fone é um pedido explícito) ou
   * se o que estava em uso saiu (reabre no substituto).
   *
   * Mudo por escolha não é tocado: reabrir a faixa devolveria a voz de quem
   * pediu para não ser ouvido. */
  private async conferirDispositivos(): Promise<void> {
    if (this.desligando) return;

    let entradas: MediaDeviceInfo[];
    try {
      entradas = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === "audioinput");
    } catch {
      return;
    }

    const ids = entradas.map((d) => d.deviceId);
    const antes = this.dispositivosConhecidos;
    this.dispositivosConhecidos = ids;
    // Primeiro retrato: só registra. Sem isto, a lista inteira pareceria "nova"
    // e a chamada trocaria de microfone no instante em que entrasse na sala.
    //
    // O retrato é gravado ANTES das guardas abaixo de propósito: a primeira
    // chamada vem de `entrar`, com a sala ainda por conectar. Guardando por
    // `!this.sala` antes de gravar, o retrato ficaria vazio e a primeira troca
    // de microfone da conversa seria engolida como se fosse a inicial.
    if (antes.length === 0) return;

    // Daqui para baixo é reação, e ela exige sala de pé. Mudo por escolha não é
    // tocado: reabrir devolveria a voz de quem pediu para não ser ouvido.
    if (!this.sala || this.recuperandoAudio || this.mudoAtual) return;

    const emUso = this.minhaFaixa?.getTrack().getSettings().deviceId;
    const sumiu = Boolean(emUso) && !ids.includes(emUso as string);
    /* `default` e `communications` não são aparelhos: são apelidos do sistema
     * para "o que estiver valendo". Eles aparecem e somem da lista sozinhos, e
     * tratá-los como novidade trocaria o microfone sem que nada tivesse mudado. */
    const novo = ids.find((id) => !antes.includes(id) && id !== "default" && id !== "communications");

    if (!sumiu && !novo) return;

    this.recuperandoAudio = true;
    try {
      const trocou = await this.reativarAudio(novo);
      if (trocou) {
        this.eventos.onErro?.(
          sumiu
            ? "O microfone em uso foi desconectado e a chamada passou para outro. Fale e confira se a barra “Sua voz” se mexe."
            : "Um microfone novo foi conectado e a chamada passou a usá-lo. Fale e confira se a barra “Sua voz” se mexe.",
        );
      }
    } catch {
      this.eventos.onErro?.(
        "O microfone mudou e a chamada não conseguiu abrir o novo. Use “Reativar áudio” para tentar de novo.",
      );
    } finally {
      this.recuperandoAudio = false;
    }
  }

  /** Monta a lista de retratos: eu primeiro, depois quem chegou. */
  private anunciarParticipantes(): void {
    if (!this.eventos.onParticipantes) return;

    const lista: Participante[] = [
      {
        id: "eu",
        nome: this.meuNome || "Você",
        video: this.videos.get("eu") ?? null,
        tela: this.minhaTela !== null,
        souEu: true,
      },
    ];

    for (const p of this.sala?.getParticipants() ?? []) {
      const id = p.getId();
      lista.push({
        id,
        // Sem nome digitado, "Convidado" — melhor que o id aleatório do XMPP,
        // que não diz nada a ninguém.
        nome: (p.getDisplayName() || "").trim() || "Convidado",
        video: this.videos.get(id) ?? null,
        tela: this.telas.has(id),
        souEu: false,
      });
    }

    this.eventos.onParticipantes(lista);
  }

  private receberFaixa(faixa: FaixaJitsi): void {
    /* O <audio> não serve só para o advogado ouvir o cliente: no Chrome, uma
     * faixa remota que não está ligada a um elemento de mídia não alimenta o
     * WebAudio — `createMediaStreamSource` devolve silêncio e a transcrição
     * sairia vazia, sem erro nenhum. O `attach` da lib faz esse trabalho. */
    const alto = document.createElement("audio");
    alto.autoplay = true;
    alto.setAttribute("playsinline", "");
    alto.muted = false;
    alto.volume = 1;
    /* `track.attach()` funciona na maior parte dos desktops, mas há WebViews e
     * Safari móvel em que ele só prepara internamente a faixa e não associa a
     * saída de áudio. Ao atribuir também o MediaStream nativo, o navegador tem
     * uma rota direta e explícita para o alto-falante/fone do entrevistador.
     * Isso vale igualmente quando o participante troca para microfone USB ou
     * Bluetooth: o Jitsi substitui a faixa remota e este método é chamado outra
     * vez para a nova trilha. */
    faixa.attach(alto);
    const trilha = faixa.getTrack();
    alto.srcObject = new MediaStream([trilha]);
    document.body.appendChild(alto);
    // `autoplay` sozinho pode ser barrado pela política do navegador, e um
    // elemento barrado não reproduz — e faixa remota que não reproduz não
    // alimenta o WebAudio (é o silêncio descrito acima). Como a entrevista só
    // chega aqui depois de vários cliques, o gesto de usuário já existe; o
    // `play()` explícito converte esse gesto em reprodução de fato.
    const tocar = () => void alto.play().catch(() => {
      /* Em iPhone/iPad a primeira tentativa pode cair antes de o WebRTC marcar
       * a faixa como utilizável. Os eventos abaixo tentam de novo quando ela
       * efetivamente fica pronta, sem exibir um erro falso para a entrevista. */
    });
    tocar();
    alto.addEventListener("loadedmetadata", tocar, { once: true });
    alto.addEventListener("canplay", tocar, { once: true });
    // Em celular a faixa costuma chegar "muted" durante a negociação e só
    // liberar amostras depois. Retomar aqui evita ficar preso no silêncio de
    // uma tentativa de play feita cedo demais.
    trilha.addEventListener("unmute", tocar);
    this.remotas.set(faixa, alto);

    this.garantirDestrave();

    if (this.limiteAudio !== null) {
      window.clearTimeout(this.limiteAudio);
      this.limiteAudio = null;
    }
    // A voz voltou dentro da janela de tolerância: era troca de dispositivo, e
    // não saída. O "aguardando" agendado em `soltarFaixa` não chega a valer.
    if (this.esperaSemRemota !== null) {
      window.clearTimeout(this.esperaSemRemota);
      this.esperaSemRemota = null;
    }
    this.mudarEstado("falando");
    this.eventos.onFaixaRemota?.(faixa.getTrack());
  }

  /* No Safari/iOS a faixa pode chegar depois do toque “Entrar”, fora da janela
   * de autoplay. Qualquer próximo toque libera todas as saídas pendentes.
   *
   * UM ouvinte por chamada, e não um por faixa. Antes cada faixa remota
   * registrava o seu par de ouvintes globais, e eles só se removiam ao
   * DISPARAR: numa chamada que reconecta, ou em que o outro lado troca de
   * microfone algumas vezes, sobravam ouvintes de faixas já descartadas
   * pendurados no documento, cada um varrendo o mapa inteiro a cada toque da
   * tela. Agora o registro é idempotente e o desligamento leva o ouvinte
   * embora, mesmo que ele nunca tenha disparado. */
  private garantirDestrave(): void {
    if (this.destravarAudio) return;
    const destravar = () => {
      for (const audio of this.remotas.values()) void audio.play().catch(() => {});
      this.removerDestrave();
    };
    this.destravarAudio = destravar;
    document.addEventListener("pointerdown", destravar, true);
    document.addEventListener("keydown", destravar, true);
  }

  private removerDestrave(): void {
    const destravar = this.destravarAudio;
    if (!destravar) return;
    this.destravarAudio = null;
    document.removeEventListener("pointerdown", destravar, true);
    document.removeEventListener("keydown", destravar, true);
  }

  /** Solta TODAS as saídas de áudio remotas e esquece os retratos dos outros.
   *
   *  Usado na reconexão, onde a conferência antiga morre sem emitir
   *  `TRACK_REMOVED`. Não mexe em `"eu"`: a minha câmera atravessa a queda viva,
   *  e apagá-la faria o meu próprio retrato piscar a cada oscilação de rede. */
  private soltarRemotas(): void {
    for (const faixa of [...this.remotas.keys()]) this.soltarFaixa(faixa);
    for (const id of [...this.videos.keys()]) if (id !== "eu") this.videos.delete(id);
    this.telas.clear();
    /* O vigia do áudio remoto pertencia à sala que caiu.
     *
     * Ele dispara uma mensagem que manda "sair da chamada e entrar de novo" —
     * conselho correto quando a sala está de pé e o áudio não veio, e péssimo
     * no meio de uma religação automática, onde a orientação é o contrário:
     * ficar na tela e esperar. Quem entrar na sala nova o rearma. */
    if (this.limiteAudio !== null) {
      window.clearTimeout(this.limiteAudio);
      this.limiteAudio = null;
    }
    /* `soltarFaixa` marca "aguardando" ao esvaziar o mapa — o que é correto
     * quando o outro lado SAIU, e errado aqui: não é que ninguém esteja na
     * sala, é que a sala caiu e está voltando. Sem esta linha a tela diz
     * "esperando o outro lado" no meio da reconexão, e quem lê isso desliga. */
    this.mudarEstado("conectando");
    this.anunciarParticipantes();
  }

  private soltarFaixa(faixa: FaixaJitsi): void {
    const alto = this.remotas.get(faixa);
    if (!alto) return;
    try {
      faixa.detach(alto);
    } catch {
      /* a faixa já pode ter sido descartada pela lib */
    }
    alto.srcObject = null;
    alto.remove();
    this.remotas.delete(faixa);

    /* PERDER A FAIXA NÃO É O MESMO QUE PERDER A PESSOA.
     *
     * Quando o outro lado troca de microfone — conecta o fone Bluetooth, a
     * bateria dele acaba, o celular passa para o viva-voz —, a lib remove a
     * faixa antiga e publica a nova. São dois eventos separados, com um
     * intervalo curto entre eles, e neste meio o mapa fica vazio. Declarar
     * "aguardando" na hora fazia a tela anunciar "esperando o cliente" com o
     * cliente falando do outro lado, e piscar de volta para "em chamada" um
     * segundo depois. Numa entrevista isso faz o advogado interromper a pessoa
     * para perguntar se ela ainda está aí.
     *
     * Quem sai de verdade é anunciado por `USER_LEFT`, que marca "aguardando"
     * na hora e sem espera nenhuma — este caminho aqui trata só o silêncio, e
     * silêncio merece o benefício da dúvida. */
    if (this.esperaSemRemota !== null) window.clearTimeout(this.esperaSemRemota);
    this.esperaSemRemota = window.setTimeout(() => {
      this.esperaSemRemota = null;
      if (this.remotas.size === 0 && !this.desligando) this.mudarEstado("aguardando");
    }, ESPERA_TROCA_REMOTA_MS);
  }

  /* Corta o próprio microfone sem sair da chamada. Devolve o estado NOVO.
   *
   * ESTADO DE MUDO INCONSISTENTE: ERA DAQUI.
   *
   * A versão anterior marcava `mudoAtual` e disparava `mute()`/`unmute()` com
   * `void` — sem esperar e sem conferir. Quando a promessa falhava (e ela falha
   * de verdade: faixa em republicação, dispositivo tomado por outro app, sala
   * renegociando), o botão já dizia "mudo" com o microfone ABERTO, ou o
   * contrário — alguém convencido de estar sendo ouvido e falando para ninguém.
   * Numa entrevista, o segundo caso é o que custa a conversa inteira.
   *
   * Agora o estado só muda depois de a operação confirmar, e volta atrás se ela
   * falhar. A tela passa a refletir o microfone, e não a intenção do clique. */
  async alternarMudo(): Promise<boolean> {
    if (!this.minhaFaixa) return this.mudoAtual;
    const alvo = !this.mudoAtual;
    try {
      await (alvo ? this.minhaFaixa.mute() : this.minhaFaixa.unmute());
      this.mudoAtual = alvo;
    } catch {
      this.eventos.onErro?.(
        alvo
          ? "Não foi possível desligar o microfone. Ele continua aberto — fale só o que puder ser ouvido."
          : "Não foi possível religar o microfone. Toque em “Reativar áudio”.",
      );
    }
    return this.mudoAtual;
  }

  desligar(): void {
    this.desligando = true;
    document.removeEventListener("visibilitychange", this.aoMudarVisibilidade);
    navigator.mediaDevices?.removeEventListener?.("devicechange", this.aoTrocarDispositivos);
    window.removeEventListener("online", this.aoVoltarRede);
    this.dispositivosConhecidos = [];
    this.ultimoRestabelecimento = 0;
    this.entrando = false;
    this.removerDestrave();
    // A reconexão pendente precisa morrer aqui: sem isto, desligar durante uma
    // queda faria a chamada RESSUSCITAR alguns segundos depois, com microfone
    // aberto, contra a vontade de quem acabou de desligar.
    this.religar = null;
    this.tentativasReconexao = 0;
    if (this.temporizadorReconexao !== null) {
      window.clearTimeout(this.temporizadorReconexao);
      this.temporizadorReconexao = null;
    }
    if (this.limiteAudio !== null) {
      window.clearTimeout(this.limiteAudio);
      this.limiteAudio = null;
    }
    if (this.esperaSemRemota !== null) {
      window.clearTimeout(this.esperaSemRemota);
      this.esperaSemRemota = null;
    }
    void this.travaTela?.release().catch(() => {});
    this.travaTela = null;

    for (const faixa of [...this.remotas.keys()]) this.soltarFaixa(faixa);

    void this.minhaFaixa?.dispose().catch(() => {});
    this.minhaFaixa = null;
    this.eventos.onFaixaLocal?.(null);
    void this.minhaCamera?.dispose().catch(() => {});
    this.minhaCamera = null;
    void this.minhaTela?.dispose().catch(() => {});
    this.minhaTela = null;
    this.cameraAntesDaTela = false;
    this.videos.clear();
    this.telas.clear();
    this.eventos.onParticipantes?.([]);

    void this.sala?.leave().catch(() => {});
    this.sala = null;

    void this.conexao?.disconnect().catch(() => {});
    this.conexao = null;

    this.mudoAtual = false;
    this.mudarEstado("fora");
  }

  private mudarEstado(novo: EstadoChamada): void {
    if (novo === this.estadoAtual) return;
    this.estadoAtual = novo;
    this.eventos.onEstado?.(novo);
  }
}
