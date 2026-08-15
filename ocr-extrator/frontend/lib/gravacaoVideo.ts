"use client";

/* Vídeo da entrevista — gravado no navegador e NUNCA enviado ao servidor.
 *
 * A diferença para o áudio é deliberada e é a razão de este arquivo existir
 * separado de `transcricao.ts`:
 *
 *   áudio  o servidor grava, do mesmo PCM que transcreve, e o arquivo fica em
 *          `dados/entrevistas/`. Some se ninguém apagar.
 *   vídeo  fica só nesta aba, em memória do navegador, e existe enquanto a tela
 *          estiver aberta. Quem não baixar, perde.
 *
 * Não é limitação: é o combinado. Vídeo de atendimento é o dado mais pesado e
 * mais sensível que este sistema toca — hora de rosto, sala e documento na mão.
 * Não guardá-lo no disco do escritório é uma decisão de retenção, não um passo
 * que ficou faltando. Por isso aqui não há upload, nem rota, nem pasta.
 *
 * DUAS FONTES, PORQUE SÃO DUAS ENTREVISTAS DIFERENTES
 *
 *   câmera  a entrevista presencial: a câmera desta máquina e o microfone.
 *   tela    a entrevista por chamada: a janela do Jitsi, com o rosto do cliente
 *           — e o microfone daqui MISTURADO, senão a gravação teria só a voz de
 *           quem está do outro lado e nenhuma das perguntas.
 *
 * FORMATO
 *
 * MP4 quando o navegador souber gravar em MP4 (Chrome recente sabe), WebM
 * quando não souber. A extensão do arquivo segue o que foi realmente gravado —
 * um .mp4 que por dentro é WebM não abre no player de quem recebe.
 */

export type FonteVideo = "camera" | "tela";
export type EstadoVideo = "parado" | "gravando" | "pronto";

export interface VideoGravado {
  /** Object URL — vale só nesta aba, e some com ela. */
  url: string;
  nome: string;
  bytes: number;
  duracaoS: number;
  /** O contêiner que o navegador realmente produziu. */
  tipo: string;
}

export interface EventosVideo {
  onEstado?: (estado: EstadoVideo) => void;
  onPronto?: (video: VideoGravado) => void;
  onErro?: (mensagem: string) => void;
}

/* Ordem de preferência. O primeiro que o navegador aceitar é o usado.
 *
 * MP4 primeiro porque é o que abre em qualquer lugar sem instalar nada — que é
 * o critério certo para um arquivo que vai por e-mail ou WhatsApp ao escritório.
 * WebM/VP9 é o que o Chrome sempre soube gravar, e é a rede de segurança. */
const FORMATOS = [
  'video/mp4;codecs="avc1.42E01E,mp4a.40.2"',
  "video/mp4",
  'video/webm;codecs="vp9,opus"',
  "video/webm",
];

/* 1,2 Mbps de vídeo é o bastante para duas pessoas conversando em 720p, e são
 * ~9 MB por minuto. Acima disso a aba passa a carregar centenas de MB de blob
 * para ganhar nitidez que uma entrevista não usa. */
const BITS_VIDEO = 1_200_000;
const BITS_AUDIO = 96_000;

/* Fatias de 5s. O MediaRecorder entrega o gravado a cada fatia, e o navegador
 * manda blob grande para o disco em vez de segurá-lo na memória da aba — é o
 * que deixa uma entrevista de uma hora caber sem derrubar a página. */
const FATIA_MS = 5_000;

function melhorFormato(): string | null {
  if (typeof MediaRecorder === "undefined") return null;
  return FORMATOS.find((f) => MediaRecorder.isTypeSupported(f)) ?? null;
}

/** `.mp4` ou `.webm`, conforme o que o navegador gravou de verdade. */
function extensaoDe(tipo: string): string {
  return tipo.includes("mp4") ? "mp4" : "webm";
}

function nomeDoArquivo(tipo: string): string {
  const agora = new Date();
  const d2 = (n: number) => String(n).padStart(2, "0");
  const quando =
    `${d2(agora.getDate())}-${d2(agora.getMonth() + 1)}-${agora.getFullYear()} ` +
    `${d2(agora.getHours())}h${d2(agora.getMinutes())}`;
  return `Entrevista ${quando}.${extensaoDe(tipo)}`;
}

/** O navegador tem como gravar vídeo? (Safari antigo e http:// não têm.) */
export function podeGravarVideo(): boolean {
  return (
    typeof MediaRecorder !== "undefined" &&
    typeof navigator !== "undefined" &&
    Boolean(navigator.mediaDevices) &&
    melhorFormato() !== null
  );
}

export class GravacaoVideo {
  private gravador: MediaRecorder | null = null;
  private pedacos: Blob[] = [];
  /** Tudo que esta gravação abriu — e que só ela pode fechar. */
  private trilhas: MediaStreamTrack[] = [];
  private ctx: AudioContext | null = null;
  private inicio = 0;
  private estadoAtual: EstadoVideo = "parado";
  private pronto: VideoGravado | null = null;
  /** Gravado e ainda não baixado: é o que se perde ao sair da tela. */
  private pendente = false;

  constructor(private eventos: EventosVideo = {}) {}

  get estado(): EstadoVideo {
    return this.estadoAtual;
  }

  get temPendente(): boolean {
    return this.pendente;
  }

  /** Segundos gravados até agora — para o cronômetro da tela. */
  get decorridoS(): number {
    return this.inicio ? (Date.now() - this.inicio) / 1000 : 0;
  }

  private mudar(estado: EstadoVideo): void {
    this.estadoAtual = estado;
    this.eventos.onEstado?.(estado);
  }

  async iniciar(fonte: FonteVideo): Promise<void> {
    if (this.estadoAtual === "gravando") return;

    const formato = melhorFormato();
    if (!formato) throw new Error("Este navegador não grava vídeo.");

    // Gravação anterior ainda na tela: quem inicia outra já decidiu que aquela
    // não interessa mais. O aviso de "não baixou" é dado ANTES, pela tela.
    this.descartar();

    const midia =
      fonte === "camera" ? await this.daCamera() : await this.daTelaComMicrofone();
    this.trilhas = midia.getTracks();

    // A pessoa clicou em "parar de compartilhar" na barra do navegador, ou a
    // câmera foi desconectada. Sem isto o gravador seguiria gravando quadro
    // congelado até alguém reparar.
    for (const trilha of this.trilhas) {
      trilha.addEventListener("ended", () => this.parar());
    }

    const gravador = new MediaRecorder(midia, {
      mimeType: formato,
      videoBitsPerSecond: BITS_VIDEO,
      audioBitsPerSecond: BITS_AUDIO,
    });
    this.pedacos = [];
    gravador.ondataavailable = (e) => {
      if (e.data.size > 0) this.pedacos.push(e.data);
    };
    gravador.onstop = () => this.montar(formato);
    gravador.onerror = () => {
      this.eventos.onErro?.("A gravação de vídeo falhou e foi interrompida.");
      this.parar();
    };

    this.gravador = gravador;
    this.inicio = Date.now();
    gravador.start(FATIA_MS);
    this.mudar("gravando");
  }

  private async daCamera(): Promise<MediaStream> {
    // Microfone próprio, e não o da transcrição: aquele é da `CapturaEntrevista`
    // e pará-lo aqui emudeceria a entrevista inteira. Abrir o mesmo dispositivo
    // duas vezes é coisa que o navegador resolve.
    return navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 24 } },
      audio: true,
    });
  }

  private async daTelaComMicrofone(): Promise<MediaStream> {
    const tela = await navigator.mediaDevices.getDisplayMedia({
      video: { frameRate: { ideal: 24 } },
      // Áudio da aba: é por onde sai a voz de quem está na chamada. O navegador
      // só entrega se a pessoa marcar a caixa ao escolher a janela.
      audio: true,
    });

    let microfone: MediaStream | null = null;
    try {
      microfone = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      // Sem microfone a gravação ainda vale — fica com a voz do outro lado, que
      // é a que interessa. Impedir a gravação por causa disto seria pior.
      microfone = null;
    }

    const audios = [...tela.getAudioTracks(), ...(microfone?.getAudioTracks() ?? [])];
    if (audios.length < 2) {
      // Uma fonte só: não há o que misturar, e um grafo de áudio a mais seria
      // uma peça a mais para quebrar.
      for (const trilha of microfone?.getAudioTracks() ?? []) tela.addTrack(trilha);
      return tela;
    }

    // Duas fontes viram uma trilha só: MediaRecorder grava UMA faixa de áudio,
    // e sem a mistura a segunda seria simplesmente ignorada.
    const ctx = new AudioContext();
    const destino = ctx.createMediaStreamDestination();
    for (const trilha of audios) {
      ctx.createMediaStreamSource(new MediaStream([trilha])).connect(destino);
    }
    this.ctx = ctx;

    const misturada = new MediaStream([
      tela.getVideoTracks()[0],
      destino.stream.getAudioTracks()[0],
    ]);
    // As originais continuam abertas alimentando a mistura; quem as fecha é o
    // `soltar`, e por isso elas precisam estar na lista.
    this.trilhas = [...audios, ...tela.getVideoTracks()];
    return misturada;
  }

  /** Fecha a gravação. O arquivo aparece pelo `onPronto`. */
  parar(): void {
    if (this.gravador && this.gravador.state !== "inactive") {
      this.gravador.stop(); // o `onstop` monta o arquivo e solta as trilhas
      return;
    }
    this.soltar();
  }

  private montar(formato: string): void {
    const duracaoS = this.decorridoS;
    this.soltar();

    const blob = new Blob(this.pedacos, { type: formato });
    this.pedacos = [];
    if (blob.size === 0) {
      this.mudar("parado");
      this.eventos.onErro?.("A gravação de vídeo saiu vazia.");
      return;
    }

    this.pronto = {
      url: URL.createObjectURL(blob),
      nome: nomeDoArquivo(formato),
      bytes: blob.size,
      duracaoS,
      tipo: formato,
    };
    this.pendente = true;
    this.mudar("pronto");
    this.eventos.onPronto?.(this.pronto);
  }

  /** Fecha câmera, tela e microfone desta gravação — e só desta. */
  private soltar(): void {
    for (const trilha of this.trilhas) trilha.stop();
    this.trilhas = [];
    void this.ctx?.close();
    this.ctx = null;
    this.gravador = null;
    this.inicio = 0;
  }

  /** O arquivo foi baixado: sair da tela deixa de ser perda. */
  marcarBaixado(): void {
    this.pendente = false;
  }

  /** Esquece o vídeo e devolve a memória ao navegador. */
  descartar(): void {
    if (this.pronto) URL.revokeObjectURL(this.pronto.url);
    this.pronto = null;
    this.pendente = false;
    this.pedacos = [];
    if (this.estadoAtual === "pronto") this.mudar("parado");
  }

  /** Fim de tudo: para o que estiver gravando e larga o que estiver guardado. */
  encerrar(): void {
    if (this.gravador && this.gravador.state !== "inactive") {
      // Sem o `onstop`: ninguém vai receber o arquivo, a tela está indo embora.
      this.gravador.onstop = null;
      this.gravador.stop();
    }
    this.soltar();
    this.descartar();
    this.mudar("parado");
  }
}
