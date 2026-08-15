/**
 * Encaminha o áudio capturado como PCM Float32 mono a 16 kHz.
 *
 * Roda na thread de áudio, então não pode alocar nem bloquear: o navegador
 * entrega 128 amostras por chamada e um atraso aqui vira estalo no som. Por
 * isso o acúmulo usa um buffer fixo e só posta quando enche.
 *
 * POR QUE A REAMOSTRAGEM ACONTECE AQUI, E NÃO NO AudioContext
 *
 * Antes o AudioContext era criado a 16 kHz e o que saía daqui já vinha nessa
 * taxa. Funcionava para o microfone — o `getUserMedia` capta direto na taxa do
 * contexto —, mas a faixa REMOTA da chamada chegava MUDA: o Chrome entrega o
 * áudio do WebRTC fixo em 48 kHz e, num contexto forçado a 16 kHz, o
 * `MediaStreamAudioSourceNode` de uma faixa remota devolve silêncio. O VAD do
 * Whisper então descartava a resposta inteira, sem erro nenhum.
 *
 * Agora o contexto roda na taxa nativa (tipicamente 48 kHz) e a conversão para
 * 16 kHz é feita aqui, por interpolação linear. Assim a fonte pode vir em
 * qualquer taxa — microfone local ou faixa da chamada — que o que sai é sempre
 * 16 kHz, que é o que o Whisper espera. A taxa de entrada chega em
 * `processorOptions.taxaEntrada`.
 *
 * Interpolação linear é aproximação, e para redução de taxa introduz um pouco
 * de aliasing. Para VOZ indo a 16 kHz isso é inaudível e não muda o que o
 * Whisper transcreve — e o que importava era deixar de sair silêncio.
 */

const TAXA_SAIDA = 16000;

class EncaminhadorPCM extends AudioWorkletProcessor {
  constructor(opcoes) {
    super();

    // `sampleRate` é um global da AudioWorklet; a opção explícita vem do lado
    // principal e ganha, para o teste poder fixá-la sem um AudioContext real.
    const taxaEntrada =
      (opcoes && opcoes.processorOptions && opcoes.processorOptions.taxaEntrada) ||
      (typeof sampleRate === "number" ? sampleRate : TAXA_SAIDA);

    // Amostras de entrada por amostra de saída. 3,0 quando a entrada é 48 kHz.
    this.passo = taxaEntrada / TAXA_SAIDA;
    // Posição de leitura fracionária no fluxo de entrada. Atravessa os blocos:
    // fica negativa entre um bloco e o seguinte, e aí lê a última amostra do
    // bloco anterior — por isso `anterior`.
    this.pos = 0;
    this.anterior = 0;

    // 4096 amostras a 16 kHz = 256 ms por mensagem. Menor que isso inunda a
    // porta de mensagens; maior atrasa o primeiro parcial sem ganho.
    this.tamanho = 4096;
    this.buffer = new Float32Array(this.tamanho);
    this.escritos = 0;
  }

  process(entradas) {
    const canal = entradas[0] && entradas[0][0];
    if (!canal) return true; // sem entrada ainda: mantém o nó vivo

    const n = canal.length;
    let pos = this.pos;

    // Amostra a saída nas posições pos, pos+passo, pos+2·passo… interpolando
    // linearmente entre as duas amostras de entrada vizinhas. Para quando a
    // próxima posição cairia no bloco seguinte, que ainda não chegou.
    while (true) {
      const i = Math.floor(pos);
      if (i + 1 >= n) break;
      const a = i < 0 ? this.anterior : canal[i];
      const b = canal[i + 1];
      this.buffer[this.escritos++] = a + (b - a) * (pos - i);
      if (this.escritos === this.tamanho) {
        // Cópia porque o buffer é reaproveitado no próximo ciclo.
        this.port.postMessage(this.buffer.slice(0));
        this.escritos = 0;
      }
      pos += this.passo;
    }

    // Carrega a fase para o próximo bloco: `pos - n` fica negativo, e a última
    // amostra deste bloco vira a vizinha à esquerda da primeira do próximo.
    this.pos = pos - n;
    this.anterior = canal[n - 1];
    return true;
  }
}

registerProcessor("encaminhador-pcm", EncaminhadorPCM);
