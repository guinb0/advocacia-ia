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

    // O microfone abre ANTES de entrar na sala: se a permissão for negada, o
    // erro sai limpo, sem deixar uma conexão pendurada no servidor.
    const faixas = await api.createLocalTracks({ devices: ["audio"] });
    this.minhaFaixa = faixas.find((f) => f.getType() === "audio") ?? null;
    if (!this.minhaFaixa) throw new Error("Nenhum microfone disponível.");

    // A câmera é pedida depois e em separado: negá-la não pode derrubar a
    // entrevista, que funciona inteira só com voz.
    if (opcoes.camera) {
      try {
        await this.abrirCamera(api);
      } catch {
        this.eventos.onErro?.("Não foi possível abrir a câmera. A chamada segue só com voz.");
      }
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
      // O nome vai antes das faixas: quem já está na sala recebe o "entrou"
      // junto do nome, em vez de ver um "participante" anônimo por um segundo.
      if (this.meuNome) sala.setDisplayName(this.meuNome);
      if (this.minhaFaixa) void sala.addTrack(this.minhaFaixa);
      if (this.minhaCamera) void sala.addTrack(this.minhaCamera);
      this.mudarEstado(sala.getParticipantCount() > 0 ? "conectando" : "aguardando");
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

    sala.on(ev.USER_JOINED, () => this.anunciarParticipantes());
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
    faixa.attach(alto);
    document.body.appendChild(alto);
    // `autoplay` sozinho pode ser barrado pela política do navegador, e um
    // elemento barrado não reproduz — e faixa remota que não reproduz não
    // alimenta o WebAudio (é o silêncio descrito acima). Como a entrevista só
    // chega aqui depois de vários cliques, o gesto de usuário já existe; o
    // `play()` explícito converte esse gesto em reprodução de fato.
    void alto.play?.().catch(() => {});
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
