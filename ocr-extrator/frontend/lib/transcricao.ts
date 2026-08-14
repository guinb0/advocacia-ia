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

export type EstadoCaptura = "sem-audio" | "capturando" | "gravando" | "pausado";

export interface Microfone {
  id: string;
  nome: string;
}

export interface EventosTranscricao {
  /** Texto provisório, reescrito enquanto a pessoa fala. */
  onParcial?: (texto: string) => void;
  /** Um trecho que PAROU de mudar. É o que alimenta o preenchimento do
   *  roteiro: o parcial ainda se reescreve, o trecho não. */
  onTrecho?: (texto: string) => void;
  /** Volume do que está entrando (RMS, 0 a 1), umas duas vezes por segundo.
   *
   *  Existe por um motivo específico: microfone mudo é indistinguível de
   *  conversa em silêncio olhando só a transcrição — nos dois casos não aparece
   *  texto. Já custou uma entrevista inteira gravada como nada. */
  onNivel?: (rms: number) => void;
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
  /* Pausa: a sessão continua aberta no servidor, só o áudio para de subir.
   *
   * Não existe "pause" no protocolo porque não precisa existir — o servidor
   * acumula o PCM que chega e transcreve o acumulado no `stop`. Deixar de
   * mandar bytes é, para ele, um trecho de silêncio que nunca aconteceu. Quem
   * fala durante a pausa não entra na resposta, que é o ponto: a pausa serve
   * para o advogado conversar sem que aquilo vire transcrição. */
  private pausado = false;
  private sessaoAtual: string | null = null;
  /** Contador para medir o nível a cada dois blocos, não a cada um. */
  private blocosDesdeNivel = 0;

  constructor(private eventos: EventosTranscricao = {}) {}

  get temAudio(): boolean {
    return this.trilha !== null;
  }

  get estaGravando(): boolean {
    return this.gravando;
  }

  get estaPausado(): boolean {
    return this.gravando && this.pausado;
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
      /* O nível é medido ANTES do filtro de gravação, e de propósito: quem
       * acabou de ligar o microfone precisa ver se ele capta som antes de
       * começar a entrevista, não depois de perder vinte minutos de conversa.
       *
       * O worklet entrega 4096 amostras (256ms); medir uma a cada duas dá
       * ~2 leituras por segundo, o bastante para um indicador e barato o
       * suficiente para não disputar a thread com o envio. */
      this.blocosDesdeNivel += 1;
      if (this.eventos.onNivel && this.blocosDesdeNivel >= 2) {
        this.blocosDesdeNivel = 0;
        let soma = 0;
        for (let i = 0; i < e.data.length; i++) soma += e.data[i] * e.data[i];
        this.eventos.onNivel(Math.sqrt(soma / e.data.length));
      }

      // O filtro de gravação é aqui, e é o que mantém a captura aberta sem
      // transmitir nada entre perguntas — e o que faz a pausa funcionar sem
      // mexer no protocolo.
      if (!this.gravando || this.pausado || this.ws?.readyState !== WebSocket.OPEN) return;
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
      } else if (m.type === "trecho") {
        if (this.gravando) this.eventos.onTrecho?.(m.text);
      } else if (m.type === "final") this.eventos.onFinal?.(m.text, m.duracao_s ?? 0);
      else if (m.type === "aquecendo") {
        this.eventos.onAviso?.(
          "Preparando o reconhecimento de voz — o texto começa a aparecer em instantes.",
        );
      } else if (m.type === "error") this.eventos.onErro?.(m.detail ?? "Erro na transcrição.");
    };
    ws.onerror = () => this.eventos.onErro?.("Conexão de transcrição caiu.");

    /* Fechamento LIMPO também precisa avisar.
     *
     * `onerror` não dispara quando o servidor encerra de forma ordenada — o que
     * acontece toda vez que o serviço de transcrição reinicia com a página
     * aberta. Sem este aviso, a resposta em curso ficava presa: a tela seguia
     * mostrando "Pausar"/"Finalizar" esperando um texto final que nunca viria,
     * e clicar nos botões não fazia nada. */
    ws.onclose = () => {
      const gravava = this.gravando;
      this.gravando = false;
      this.pausado = false;
      this.sessaoAtual = null;
      this.ws = null;
      if (gravava) {
        this.eventos.onErro?.(
          "A conexão de transcrição caiu no meio da resposta. O trecho não gravado " +
            "se perdeu — grave de novo ou digite.",
        );
      }
    };

    await new Promise<void>((ok, falhou) => {
      ws.onopen = () => ok();
      setTimeout(() => falhou(new Error("O servidor de transcrição não respondeu.")), 10_000);
    });

    this.ws = ws;
    return ws;
  }

  /** Abre a escuta da entrevista INTEIRA, do "podemos começar?" ao fim.
   *
   * Uma sessão só, que não fecha entre perguntas. É o que substitui os 86
   * ciclos de gravar/finalizar: o texto sai por `onTrecho` conforme a conversa
   * anda, e quem decide a qual pergunta ele pertence é o servidor, não o
   * entrevistador apertando um botão antes de cada uma.
   *
   * O `finalizarResposta` continua servindo para fechar — e é ele que devolve
   * a transcrição do áudio inteiro, com o melhor contexto.
   */
  async iniciarEntrevista(): Promise<void> {
    return this.iniciarResposta("entrevista");
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
    this.pausado = false;
    this.eventos.onEstado?.("gravando");
  }

  /** Segura o envio sem fechar a resposta.
   *
   * Para quando o entrevistador precisa falar sem entrar na transcrição —
   * explicar um termo, atender o telefone, ler a análise na tela. O que for dito
   * enquanto pausado não existe para o Whisper. */
  pausar(): void {
    if (!this.gravando || this.pausado) return;
    this.pausado = true;
    this.eventos.onEstado?.("pausado");
  }

  retomar(): void {
    if (!this.gravando || !this.pausado) return;
    this.pausado = false;
    this.eventos.onEstado?.("gravando");
  }

  /** Encerra a resposta. O microfone continua aberto para a próxima pergunta. */
  finalizarResposta(): void {
    if (!this.gravando) return;
    this.gravando = false; // para o envio ANTES de avisar o servidor
    this.pausado = false;
    const sessao = this.sessaoAtual;
    this.sessaoAtual = null;
    this.eventos.onEstado?.("capturando");

    /* `send` em socket fechado LEVANTA exceção, e essa exceção subia até o
     * onClick do botão. A tela já tinha entrado em "Transcrevendo…" e ficava
     * lá para sempre, porque o `final` nunca chegaria de um socket morto.
     * Avisar é o que devolve a pergunta ao usuário. */
    if (this.ws?.readyState !== WebSocket.OPEN) {
      this.eventos.onErro?.(
        "A conexão de transcrição não estava aberta. A resposta não foi transcrita — " +
          "grave de novo ou digite.",
      );
      return;
    }
    try {
      this.ws.send(JSON.stringify({ type: "stop", sessionId: sessao }));
    } catch {
      this.eventos.onErro?.("Não foi possível fechar a resposta. Grave de novo ou digite.");
    }
  }

  /** Fim da entrevista: solta a captura e a conexão. */
  encerrar(): void {
    this.gravando = false;
    this.pausado = false;
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
