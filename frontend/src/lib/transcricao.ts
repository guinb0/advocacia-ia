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

/** O áudio da entrevista, depois de fechado e convertido. */
export interface Gravacao {
  entrevista_id: string;
  /** O MP4 está no disco e pode ser baixado. */
  pronto: boolean;
  /** Há áudio guardado — mesmo que a conversão ainda não tenha rodado. */
  existe: boolean;
  /** Segundos de FALA, não de relógio: pausa e intervalo não entram. */
  duracao_s: number;
  bytes: number;
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
  /** Quantos segundos de áudio chegam por segundo de relógio, medido no
   *  servidor. 1,0 é tempo real; abaixo disso a fala está se perdendo no
   *  caminho, ANTES do reconhecimento — e quem olha a tela precisa saber que o
   *  buraco no texto não é o modelo errando, é áudio que nunca chegou. */
  onChegada?: (fator: number) => void;
  onFinal?: (texto: string, duracaoS: number) => void;
  onEstado?: (estado: EstadoCaptura) => void;
  /** Situação passageira que não é erro — hoje, o Whisper carregando. */
  onAviso?: (mensagem: string) => void;
  onErro?: (mensagem: string) => void;
}

/* -------------------------------------------------- áudio da entrevista
 *
 * Funções de módulo, e não métodos da captura, porque quem baixa o áudio já não
 * está mais gravando: a tela seguinte à entrevista tem o `entrevistaId` e não
 * tem (nem deve ter) o microfone aberto. */

/** Um id por entrevista. Vazio no servidor, onde não há `crypto` nem gravação. */
function novoIdEntrevista(): string {
  return typeof crypto !== "undefined" ? crypto.randomUUID() : "";
}

/* ------------------------------------------------- transcrição bruta
 *
 * A conversa como o Whisper a ouviu, na ordem, sem passar pelo roteiro.
 *
 * Ela tem DOIS destinos e um formato só, de propósito: o .txt que o atendente
 * baixa e o texto que vai para o caso (`PUT /api/casos/{id}/entrevista-ao-vivo`)
 * são o mesmo texto. Se divergissem, o secretário auditaria uma versão e o
 * atendente teria em mãos outra — e a divergência só apareceria numa discussão
 * sobre o que foi dito, que é o pior momento possível para descobri-la. */

/** Um trecho reconhecido: quando foi dito e o que se ouviu. */
export interface TrechoTranscrito {
  quando: number;
  texto: string;
}

/** "14:07:32" — a hora de parede, que é como se procura um trecho no áudio. */
function relogio(quando: number): string {
  return new Date(quando).toLocaleTimeString("pt-BR");
}

/** O texto completo da transcrição bruta, com cabeçalho que diz o que ela é.
 *
 * O cabeçalho não é enfeite: sem ele, quem abre o arquivo seis meses depois lê
 * erros de reconhecimento como se fossem o que o cliente disse. E o mesmo aviso
 * precisa alcançar o secretário, que lê este texto pela tela da supervisão.
 */
export function montarTranscricaoBruta(trechos: TrechoTranscrito[]): string {
  const cabecalho = [
    "TRANSCRIÇÃO BRUTA DA ENTREVISTA",
    `Gerada em ${new Date().toLocaleString("pt-BR")}`,
    `${trechos.length} trecho(s) reconhecido(s)`,
    "",
    "Esta é a fala como saiu da transcrição automática, na ordem, sem",
    "passar pelo roteiro. O que está nos campos da entrevista é o que",
    "o sistema interpretou; isto é o que foi dito.",
    "",
    "-".repeat(62),
    "",
  ].join("\n");
  return cabecalho + trechos.map((t) => `[${relogio(t.quando)}] ${t.texto}`).join("\n");
}

/** Onde baixar ou tocar o áudio já convertido. */
export function urlDoAudio(entrevistaId: string): string {
  return `${BASE_TRANSCRICAO}/entrevista/${entrevistaId}/audio`;
}

/** Se há áudio desta entrevista e se o MP4 já está pronto. */
export async function consultarGravacao(entrevistaId: string): Promise<Gravacao | null> {
  const resposta = await fetch(`${BASE_TRANSCRICAO}/entrevista/${entrevistaId}/gravacao`);
  if (!resposta.ok) return null;
  return (await resposta.json()) as Gravacao;
}

/** Fecha a gravação e converte para MP4. `null` quando não houve áudio.
 *
 * Demora o tempo da conversão — ~25s numa entrevista de 40 minutos, medido —
 * então quem chama precisa mostrar que está preparando. Chamar duas vezes é
 * seguro: o servidor devolve o arquivo pronto em vez de reconverter. */
export async function encerrarGravacao(entrevistaId: string): Promise<Gravacao | null> {
  const resposta = await fetch(`${BASE_TRANSCRICAO}/entrevista/${entrevistaId}/encerrar`, {
    method: "POST",
  });
  // 404 é a entrevista que não gravou nada — microfone nunca aberto. Não é erro
  // para mostrar ao entrevistador.
  if (resposta.status === 404) return null;
  if (!resposta.ok) throw new Error("Não foi possível fechar a gravação do áudio.");
  return (await resposta.json()) as Gravacao;
}

export class CapturaEntrevista {
  /* O áudio é gravado no servidor, do mesmo fluxo que alimenta o Whisper — o
   * arquivo é exatamente o que foi transcrito. Este id costura tudo num arquivo
   * só: a escuta contínua, cada resposta gravada à parte e os complementos são
   * sessões diferentes da MESMA entrevista. Ver `app/gravacao.py`. */
  private idEntrevista: string = novoIdEntrevista();
  /** A gravação deste id já foi fechada e convertida. */
  private gravacaoEncerrada = false;

  get entrevistaId(): string {
    return this.idEntrevista;
  }

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

    /* Taxa NATIVA de propósito, e não 16 kHz forçado.
     *
     * A faixa remota da chamada chega do WebRTC fixa em 48 kHz; num contexto
     * forçado a 16 kHz, o `MediaStreamAudioSourceNode` dela devolve SILÊNCIO no
     * Chrome — e era por isso que transcrever a voz do entrevistado pela chamada
     * saía vazio. O microfone escondia o defeito porque o `getUserMedia` capta
     * já na taxa do contexto. Agora o contexto roda no que o hardware der e a
     * conversão para 16 kHz é do worklet, que vale para qualquer fonte. */
    const ctx = new AudioContext();
    await ctx.audioWorklet.addModule("/worklet-pcm.js");
    const origem = ctx.createMediaStreamSource(new MediaStream([trilha]));
    const no = new AudioWorkletNode(ctx, "encaminhador-pcm", {
      processorOptions: { taxaEntrada: ctx.sampleRate },
    });

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
      } else if (m.type === "diagnostico") {
        // Chega mesmo quando nada foi reconhecido — é o único caminho pelo qual
        // a tela descobre que o áudio está se perdendo antes do modelo.
        if (typeof m.chegada === "number") this.eventos.onChegada?.(m.chegada);
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

    /* Gravar depois de encerrar é OUTRA entrevista, com outro arquivo.
     *
     * Reaproveitar o id faria a conversão seguinte passar por cima do .mp4 que
     * acabou de ser gerado — o áudio da primeira parte sumiria sem aviso. Quem
     * encerrou por engano e voltou a gravar fica com dois arquivos, que é o
     * resultado ruim aceitável; um arquivo sobrescrito não é. */
    if (this.gravacaoEncerrada) {
      this.idEntrevista = novoIdEntrevista();
      this.gravacaoEncerrada = false;
    }

    const ws = await this.conectar();
    this.sessaoAtual = crypto.randomUUID();
    ws.send(
      JSON.stringify({
        type: "start",
        sessionId: this.sessaoAtual,
        questionId: perguntaId,
        entrevistaId: this.idEntrevista,
      }),
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

  /** Espera o navegador entregar o áudio que ainda está na fila do socket.
   *
   * Quem vai encerrar a gravação chama isto ANTES: o encerramento vai por HTTP,
   * e uma requisição nova pode chegar ao servidor antes dos últimos blocos que
   * o WebSocket ainda não despachou — o arquivo fecharia sem os segundos finais
   * da fala. `bufferedAmount` zerado é o navegador dizendo que entregou tudo ao
   * sistema.
   *
   * O teto de 2s é para não prender a tela num socket entupido: perder o
   * finalzinho é melhor que não entregar áudio nenhum. */
  async aguardarEnvio(limiteMs = 2_000): Promise<void> {
    const ate = Date.now() + limiteMs;
    while (
      this.ws?.readyState === WebSocket.OPEN &&
      this.ws.bufferedAmount > 0 &&
      Date.now() < ate
    ) {
      await new Promise((ok) => setTimeout(ok, 50));
    }
  }

  /** Fecha a gravação desta entrevista, esperando o que ainda está na fila.
   *
   * O `finalizarResposta` deve vir ANTES: o último trecho de fala só entra na
   * gravação depois que o navegador para de mandar bytes. */
  async encerrarGravacao(): Promise<Gravacao | null> {
    if (!this.idEntrevista) return null;
    await this.aguardarEnvio();
    const fechada = await encerrarGravacao(this.idEntrevista);
    // Marca mesmo quando não havia áudio: o que este id pode ter no disco está
    // fechado, e o que vier depois é entrevista nova.
    this.gravacaoEncerrada = true;
    return fechada;
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
