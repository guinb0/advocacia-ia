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

export interface EventosChamada {
  onEstado?: (estado: EstadoChamada) => void;
  /** A voz do outro lado. No advogado, é o que alimenta o Whisper. */
  onFaixaRemota?: (trilha: MediaStreamTrack) => void;
  onErro?: (mensagem: string) => void;
}

/* A lib-jitsi-meet não publica tipos. Em vez de arrastar um pacote de tipos da
 * comunidade — que descreve outra versão e mente com confiança —, declara-se
 * aqui só o que este arquivo usa. O que não está descrito, não é usado. */
interface FaixaJitsi {
  isLocal(): boolean;
  getType(): "audio" | "video";
  getTrack(): MediaStreamTrack;
  getParticipantId?(): string;
  attach(elemento: HTMLMediaElement): void;
  detach(elemento: HTMLMediaElement): void;
  mute(): Promise<void>;
  unmute(): Promise<void>;
  dispose(): Promise<void>;
}

interface ConferenciaJitsi {
  on(evento: string, ouvinte: (...args: unknown[]) => void): void;
  addTrack(faixa: FaixaJitsi): Promise<void>;
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
      falhou(
        new Error(
          `Servidor de chamadas fora do ar (${BASE_JITSI}). ` +
            "Suba o stack do Jitsi: docker compose up -d em docker-jitsi-meet.",
        ),
      );
    };
    document.head.appendChild(script);
  });

  return carregando;
}

export class ChamadaJitsi {
  private api: ApiJitsi | null = null;
  private conexao: ConexaoJitsi | null = null;
  private sala: ConferenciaJitsi | null = null;
  private minhaFaixa: FaixaJitsi | null = null;
  private remotas = new Map<FaixaJitsi, HTMLAudioElement>();
  private estadoAtual: EstadoChamada = "fora";
  private desligando = false;
  private mudoAtual = false;

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

  /** Abre o microfone e entra na sala. */
  async entrar(sala: string): Promise<void> {
    if (this.sala) return;
    this.desligando = false;
    this.mudarEstado("conectando");

    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error(
        "O navegador só libera o microfone em conexão segura (https) ou em localhost.",
      );
    }

    const api = await carregarJitsi();
    this.api = api;

    // O microfone abre ANTES de entrar na sala: se a permissão for negada, o
    // erro sai limpo, sem deixar uma conexão pendurada no servidor.
    const faixas = await api.createLocalTracks({ devices: ["audio"] });
    this.minhaFaixa = faixas.find((f) => f.getType() === "audio") ?? null;
    if (!this.minhaFaixa) throw new Error("Nenhum microfone disponível.");

    await this.conectar(api, sala);
  }

  private conectar(api: ApiJitsi, sala: string): Promise<void> {
    const eventos = api.events.connection;
    const conexao = new api.JitsiConnection(null, null, {
      hosts: { domain: "meet.jitsi", muc: "muc.meet.jitsi" },
      // O `room` na query é o que permite ao Prosody escolher o shard certo
      // quando há mais de um; num servidor só, é inofensivo e recomendado.
      serviceUrl: `${BASE_JITSI.replace(/^http/, "ws")}/xmpp-websocket?room=${encodeURIComponent(sala)}`,
    });
    this.conexao = conexao;

    return new Promise<void>((ok, falhou) => {
      conexao.addEventListener(eventos.CONNECTION_ESTABLISHED, () => {
        this.entrarNaSala(api, sala);
        ok();
      });
      conexao.addEventListener(eventos.CONNECTION_FAILED, () => {
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
      if (this.minhaFaixa) void sala.addTrack(this.minhaFaixa);
      this.mudarEstado(sala.getParticipantCount() > 0 ? "conectando" : "aguardando");
    });

    sala.on(ev.TRACK_ADDED, (...args: unknown[]) => {
      const faixa = args[0] as FaixaJitsi;
      if (faixa.isLocal() || faixa.getType() !== "audio") return;
      this.receberFaixa(faixa);
    });

    sala.on(ev.TRACK_REMOVED, (...args: unknown[]) => {
      this.soltarFaixa(args[0] as FaixaJitsi);
    });

    sala.on(ev.USER_LEFT, () => {
      if (sala.getParticipantCount() === 0) this.mudarEstado("aguardando");
    });

    sala.on(ev.CONFERENCE_FAILED, (...args: unknown[]) => {
      this.mudarEstado("encerrada");
      this.eventos.onErro?.(`A sala recusou a entrada (${String(args[0])}).`);
    });

    sala.join();
  }

  private receberFaixa(faixa: FaixaJitsi): void {
    /* O <audio> não serve só para o advogado ouvir o cliente: no Chrome, uma
     * faixa remota que não está ligada a um elemento de mídia não alimenta o
     * WebAudio — `createMediaStreamSource` devolve silêncio e a transcrição
     * sairia vazia, sem erro nenhum. O `attach` da lib faz esse trabalho. */
    const alto = document.createElement("audio");
    alto.autoplay = true;
    faixa.attach(alto);
    document.body.appendChild(alto);
    this.remotas.set(faixa, alto);

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

    for (const faixa of [...this.remotas.keys()]) this.soltarFaixa(faixa);

    void this.minhaFaixa?.dispose().catch(() => {});
    this.minhaFaixa = null;

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
