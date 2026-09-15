"use client";

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
  /** A sala inteira mudou: alguém entrou, saiu, ligou câmera ou trocou de nome. */
  onParticipantes?: (lista: Participante[]) => void;
  onErro?: (mensagem: string) => void;
}

export interface OpcoesEntrada {
  /** Nome exibido aos outros. Sem login: é o que a pessoa digitar. */
  nome?: string;
  /** Entrar já com a câmera ligada. */
  camera?: boolean;
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
  attach(elemento: HTMLMediaElement): void;
  detach(elemento: HTMLMediaElement): void;
  mute(): Promise<void>;
  unmute(): Promise<void>;
  dispose(): Promise<void>;
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

export async function pedirPermissaoMicrofone(): Promise<PermissaoMicrofone> {
  if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) return "indisponivel";
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    stream.getTracks().forEach((faixa) => faixa.stop());
    return "permitido";
  } catch (e) {
    return e instanceof DOMException && /NotAllowed|Security/i.test(e.name) ? "negado" : "indisponivel";
  }
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
  /** Impede duas recuperações de microfone ao mesmo tempo (`ended` + `mute`). */
  private recuperandoAudio = false;
  private travaTela: WakeLockSentinel | null = null;
  private limiteAudio: number | null = null;

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

  /** Abre o microfone (e a câmera, se pedida) e entra na sala. */
  async entrar(sala: string, opcoes: OpcoesEntrada = {}, token?: string): Promise<void> {
    if (this.sala) return;
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
    let faixas: FaixaJitsi[] = [];
    if (querCamera) {
      try {
        faixas = await api.createLocalTracks({ devices: ["audio", "video"] });
      } catch {
        this.eventos.onErro?.("Não foi possível abrir a câmera. A chamada segue só com voz.");
        faixas = [];
      }
    }
    if (!faixas.some((f) => f.getType() === "audio")) {
      // Sem câmera, ou com o pedido conjunto recusado: o microfone sozinho. Se
      // a permissão do microfone for negada, o erro sai limpo daqui, sem deixar
      // conexão pendurada no servidor.
      faixas = await api.createLocalTracks({ devices: ["audio"] });
    }
    this.minhaFaixa = faixas.find((f) => f.getType() === "audio") ?? null;
    if (!this.minhaFaixa) throw new Error("Nenhum microfone disponível.");
    this.vigiarMicrofone();
    document.addEventListener("visibilitychange", this.aoMudarVisibilidade);
    void this.manterTelaAcesa();

    const camera = faixas.find((f) => f.getType() === "video") ?? null;
    if (camera) {
      this.minhaCamera = camera;
      this.videos.set("eu", camera.getTrack());
    }

    await this.conectar(api, salaJitsi, token);
  }

  private async abrirCamera(api: ApiJitsi): Promise<void> {
    const faixas = await api.createLocalTracks({ devices: ["video"] });
    this.minhaCamera = faixas.find((f) => f.getType() === "video") ?? null;
    if (this.minhaCamera) this.videos.set("eu", this.minhaCamera.getTrack());
  }

  /** Liga ou desliga a câmera no meio da chamada. Devolve se ficou ligada. */
  async alternarCamera(): Promise<boolean> {
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
    await this.abrirCamera(this.api);
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

  private conectar(api: ApiJitsi, sala: string, token?: string): Promise<void> {
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

    return new Promise<void>((ok, falhou) => {
      const limite = window.setTimeout(() => {
        this.mudarEstado("encerrada");
        falhou(
          new Error(
            "O servidor de chamadas não respondeu. Confira a internet (troque entre Wi-Fi e 4G) " +
              `e tente de novo. Se continuar, atualize o Google Chrome (${descreverNavegador()}).`,
          ),
        );
      }, LIMITE_SERVIDOR_MS);
      conexao.addEventListener(eventos.CONNECTION_ESTABLISHED, () => {
        window.clearTimeout(limite);
        this.entrarNaSala(api, sala);
        ok();
      });
      conexao.addEventListener(eventos.CONNECTION_FAILED, () => {
        window.clearTimeout(limite);
        this.mudarEstado("encerrada");
        falhou(new Error("Não foi possível falar com o servidor de chamadas."));
      });
      conexao.addEventListener(eventos.CONNECTION_DISCONNECTED, () => {
        if (this.desligando) return;
        this.mudarEstado("encerrada");
        this.eventos.onErro?.("A conexão com o servidor de chamadas caiu.");
      });
      conexao.connect();
    });
  }

  private entrarNaSala(api: ApiJitsi, nome: string): void {
    const ev = api.events.conference;
    const sala = this.conexao!.initJitsiConference(nome, {
      // P2P ligado: com dois participantes o áudio vai direto entre os
      // navegadores e o bridge só entra quando o caminho direto falha.
      p2p: { enabled: true },
    });
    this.sala = sala;

    sala.on(ev.CONFERENCE_JOINED, () => {
      // O nome vai antes das faixas: quem já está na sala recebe o "entrou"
      // junto do nome, em vez de ver um "participante" anônimo por um segundo.
      if (this.meuNome) sala.setDisplayName(this.meuNome);
      // Publicação de áudio é confirmada: em alguns navegadores a sala entra
      // antes de o dispositivo terminar de ficar disponível. Antes uma falha
      // aqui era silenciosa e a chamada parecia normal, mas sem voz de saída.
      void this.publicarMicrofone(sala);
      if (this.minhaCamera) void sala.addTrack(this.minhaCamera);
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

    sala.on(ev.USER_LEFT, (...args: unknown[]) => {
      this.videos.delete(String(args[0]));
      this.telas.delete(String(args[0]));
      if (sala.getParticipantCount() === 0) this.mudarEstado("aguardando");
      this.anunciarParticipantes();
    });

    sala.on(ev.CONFERENCE_FAILED, (...args: unknown[]) => {
      this.mudarEstado("encerrada");
      this.eventos.onErro?.(`A sala recusou a entrada (${String(args[0])}).`);
    });

    sala.join();
  }

  private async publicarMicrofone(sala: ConferenciaJitsi): Promise<boolean> {
    const faixa = this.minhaFaixa;
    if (!faixa) return false;
    faixa.getTrack().enabled = true;
    try {
      await sala.addTrack(faixa);
      return true;
    } catch {
      await new Promise<void>((ok) => window.setTimeout(ok, 500));
    }
    try {
      faixa.getTrack().enabled = true;
      await sala.addTrack(faixa);
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

  /** Reabre e republica o microfone sem derrubar vídeo ou sala. */
  async reativarAudio(): Promise<boolean> {
    if (!this.api || !this.sala) return false;
    const anterior = this.minhaFaixa;
    if (anterior) {
      await this.sala.removeTrack(anterior).catch(() => {});
      await anterior.dispose().catch(() => {});
    }
    const faixas = await this.api.createLocalTracks({ devices: ["audio"] });
    this.minhaFaixa = faixas.find((f) => f.getType() === "audio") ?? null;
    if (!this.minhaFaixa) throw new Error("Nenhum microfone disponível.");
    this.mudoAtual = false;
    this.vigiarMicrofone();
    return this.publicarMicrofone(this.sala);
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

    /* No Safari/iOS a faixa pode chegar depois do toque “Entrar”, fora da
     * janela de autoplay. Qualquer próximo toque do atendente libera todas as
     * saídas pendentes; não depende de trocar microfone nem de reconectar. */
    const destravar = () => {
      for (const audio of this.remotas.values()) void audio.play().catch(() => {});
      document.removeEventListener("pointerdown", destravar, true);
      document.removeEventListener("keydown", destravar, true);
    };
    document.addEventListener("pointerdown", destravar, true);
    document.addEventListener("keydown", destravar, true);

    if (this.limiteAudio !== null) {
      window.clearTimeout(this.limiteAudio);
      this.limiteAudio = null;
    }
    this.mudarEstado("falando");
    this.eventos.onFaixaRemota?.(faixa.getTrack());
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
    if (this.remotas.size === 0 && !this.desligando) this.mudarEstado("aguardando");
  }

  /** Corta o próprio microfone sem sair da chamada. Devolve o estado novo. */
  alternarMudo(): boolean {
    if (!this.minhaFaixa) return false;
    this.mudoAtual = !this.mudoAtual;
    void (this.mudoAtual ? this.minhaFaixa.mute() : this.minhaFaixa.unmute());
    return this.mudoAtual;
  }

  desligar(): void {
    this.desligando = true;
    document.removeEventListener("visibilitychange", this.aoMudarVisibilidade);
    if (this.limiteAudio !== null) {
      window.clearTimeout(this.limiteAudio);
      this.limiteAudio = null;
    }
    void this.travaTela?.release().catch(() => {});
    this.travaTela = null;

    for (const faixa of [...this.remotas.keys()]) this.soltarFaixa(faixa);

    void this.minhaFaixa?.dispose().catch(() => {});
    this.minhaFaixa = null;
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
