"use client";

/* O serviço de transcrição roda em processo próprio, separado da API do OCR:
 * os dois modelos disputavam CPU e o mesmo áudio que leva 3s isolado levava
 * 227s dividindo processo com o PaddleOCR. */
const BASE_TRANSCRICAO =
  process.env.NEXT_PUBLIC_TRANSCRICAO_API ?? "http://127.0.0.1:8200";

/* Cliente da transcrição da entrevista.
 *
 *   CaptureSession — a fonte de áudio, aberta UMA vez para a entrevista inteira
 *       └── AnswerSession — uma resposta, entre iniciar e finalizar
 *
 * A entrevista acontece aqui, não numa chamada externa: o sistema é quem grava.
 * A fonte abre uma vez e fica aberta; o que liga e desliga entre perguntas é só
 * o envio. Reabrir a cada pergunta acenderia e apagaria o indicador de
 * microfone do navegador o tempo todo e arriscaria perder o começo da fala,
 * porque o `getUserMedia` leva alguns décimos para entregar a trilha.
 *
 * São duas fontes possíveis, e a diferença importa:
 *
 * - `selecionarAudio()` — o microfone desta máquina, para a entrevista
 *   presencial. Capta as duas vozes na mesma trilha.
 * - `usarTrilha()` — a faixa remota da chamada (`lib/chamadaJitsi.ts`), que traz
 *   SÓ a voz do outro lado. É o que permite transcrever o cliente sem
 *   transcrever o entrevistador, e sem diarização.
 */

export type EstadoCaptura = "sem-audio" | "capturando" | "gravando";

export interface Microfone {
  id: string;
  nome: string;
}

export interface EventosTranscricao {
  /** Texto provisório, reescrito enquanto a pessoa fala. */
  onParcial?: (texto: string) => void;
  onFinal?: (texto: string, duracaoS: number) => void;
  onEstado?: (estado: EstadoCaptura) => void;
  /** Situação passageira que não é erro — hoje, o Whisper carregando. */
  onAviso?: (mensagem: string) => void;
  onErro?: (mensagem: string) => void;
}

const TAXA = 16_000;

export class CapturaEntrevista {
  /** Só quando o microfone é NOSSO — a faixa da chamada é de quem a criou. */
  private stream: MediaStream | null = null;
  private trilha: MediaStreamTrack | null = null;
  private ctx: AudioContext | null = null;
  private no: AudioWorkletNode | null = null;
  private ws: WebSocket | null = null;
  private gravando = false;
  private sessaoAtual: string | null = null;

  constructor(private eventos: EventosTranscricao = {}) {}

  get temAudio(): boolean {
    return this.trilha !== null;
  }

  get estaGravando(): boolean {
    return this.gravando;
  }

  /** Lista os microfones. Só traz nome depois da primeira permissão concedida. */
  static async microfones(): Promise<Microfone[]> {
    const todos = await navigator.mediaDevices.enumerateDevices();
    return todos
      .filter((d) => d.kind === "audioinput")
      .map((d, i) => ({ id: d.deviceId, nome: d.label || `Microfone ${i + 1}` }));
  }

  /** Pede o microfone. Chamado UMA vez por entrevista. */
  async selecionarAudio(dispositivoId?: string): Promise<void> {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        deviceId: dispositivoId ? { exact: dispositivoId } : undefined,
        // Todo o processamento fica desligado de propósito.
        //
        // `echoCancellation` é o mais importante: se a entrevista for por
        // telefone no viva-voz, ele trataria a voz do cliente saindo do
        // alto-falante como eco e a removeria — sobraria só o entrevistador.
        // `noiseSuppression` e `autoGainControl` deformam a fala e pioram a
        // transcrição; o Whisper lida melhor com o áudio cru.
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false,
      },
    });

    const trilhas = stream.getAudioTracks();
    if (trilhas.length === 0) {
      stream.getTracks().forEach((t) => t.stop());
      throw new Error("Nenhum microfone disponível.");
    }

    this.stream = stream;
    await this.montar(trilhas[0]);
  }

  /** Transcreve uma trilha aberta por outro dono — a faixa remota da chamada.
   *
   * Trocar de fonte no meio da entrevista é legítimo: começou presencial, o
   * cliente pediu para continuar por chamada. Por isso desmonta a anterior
   * antes, mas sem encerrar a conexão de transcrição, que continua a mesma. */
  async usarTrilha(trilha: MediaStreamTrack): Promise<void> {
    this.desmontar();
    await this.montar(trilha);
  }

  /** Liga a fonte ao worklet que fatia o PCM e o manda para o servidor. */
  private async montar(trilha: MediaStreamTrack): Promise<void> {
    // Microfone desconectado, ou chamada que caiu no meio da entrevista.
    trilha.addEventListener("ended", () => this.encerrar());
    this.trilha = trilha;

    const ctx = new AudioContext({ sampleRate: TAXA });
    await ctx.audioWorklet.addModule("/worklet-pcm.js");
    const origem = ctx.createMediaStreamSource(new MediaStream([trilha]));
    const no = new AudioWorkletNode(ctx, "encaminhador-pcm");

    no.port.onmessage = (e: MessageEvent<Float32Array>) => {
      // O worklet entrega sempre; o filtro de gravação é aqui, e é o que
      // mantém a captura aberta sem transmitir nada entre perguntas.
      if (!this.gravando || this.ws?.readyState !== WebSocket.OPEN) return;
      this.ws.send(e.data.buffer as ArrayBuffer);
    };

    origem.connect(no);
    // Sem destino o worklet não é agendado no Chrome. Ganho zero: devolver o
    // microfone ao alto-falante criaria microfonia na sala.
    const mudo = ctx.createGain();
    mudo.gain.value = 0;
    no.connect(mudo).connect(ctx.destination);

    this.ctx = ctx;
    this.no = no;
    this.eventos.onEstado?.("capturando");
  }

  private async conectar(): Promise<WebSocket> {
    if (this.ws?.readyState === WebSocket.OPEN) return this.ws;

    const url = `${BASE_TRANSCRICAO}/ws/transcricao`.replace(/^http/, "ws");
    const ws = new WebSocket(url);
    ws.binaryType = "arraybuffer";

    ws.onmessage = (e) => {
      const m = JSON.parse(e.data as string);
      if (m.type === "partial") {
        // Parcial que chega depois do "finalizar" é texto velho: o modelo
        // ainda estava rodando quando a resposta fechou. Mostrá-lo faria a
        // transcrição voltar atrás na tela.
        if (this.gravando) this.eventos.onParcial?.(m.text);
      } else if (m.type === "final") this.eventos.onFinal?.(m.text, m.duracao_s ?? 0);
      else if (m.type === "aquecendo") {
        this.eventos.onAviso?.(
          "Preparando o reconhecimento de voz — o texto começa a aparecer em instantes.",
        );
      } else if (m.type === "error") this.eventos.onErro?.(m.detail ?? "Erro na transcrição.");
    };
    ws.onerror = () => this.eventos.onErro?.("Conexão de transcrição caiu.");

    await new Promise<void>((ok, falhou) => {
      ws.onopen = () => ok();
      setTimeout(() => falhou(new Error("O servidor de transcrição não respondeu.")), 10_000);
    });

    this.ws = ws;
    return ws;
  }

  /** Começa a transcrever a resposta desta pergunta. */
  async iniciarResposta(perguntaId: string): Promise<void> {
    if (!this.trilha) throw new Error("Ligue o microfone antes de iniciar.");
    const ws = await this.conectar();
    this.sessaoAtual = crypto.randomUUID();
    ws.send(
      JSON.stringify({ type: "start", sessionId: this.sessaoAtual, questionId: perguntaId }),
    );
    this.gravando = true;
    this.eventos.onEstado?.("gravando");
  }

  /** Encerra a resposta. O microfone continua aberto para a próxima pergunta. */
  finalizarResposta(): void {
    if (!this.gravando) return;
    this.gravando = false; // para o envio ANTES de avisar o servidor
    this.ws?.send(JSON.stringify({ type: "stop", sessionId: this.sessaoAtual }));
    this.sessaoAtual = null;
    this.eventos.onEstado?.("capturando");
  }

  /** Fim da entrevista: solta a captura e a conexão. */
  encerrar(): void {
    this.gravando = false;
    this.sessaoAtual = null;
    this.ws?.close();
    this.ws = null;
    this.desmontar();
    this.eventos.onEstado?.("sem-audio");
  }

  /** Desfaz a cadeia de áudio. Só desliga a trilha se o microfone for nosso: a
   * faixa da chamada pertence à `ChamadaJitsi`, e pará-la aqui emudeceria a
   * conversa inteira — não só a transcrição. */
  private desmontar(): void {
    this.no?.disconnect();
    this.no = null;
    void this.ctx?.close();
    this.ctx = null;
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    this.trilha = null;
  }
}
