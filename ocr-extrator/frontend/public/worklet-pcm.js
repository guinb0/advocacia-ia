/**
 * Encaminha o áudio capturado como PCM Float32 mono.
 *
 * Roda na thread de áudio, então não pode alocar nem bloquear: o navegador
 * entrega 128 amostras por chamada e um atraso aqui vira estalo no som. Por
 * isso o acúmulo usa um buffer fixo e só posta quando enche.
 *
 * O AudioContext é criado a 16 kHz no lado do cliente, então o que sai daqui
 * já está na taxa que o Whisper espera — não há reamostragem no servidor.
 */
class EncaminhadorPCM extends AudioWorkletProcessor {
  constructor() {
    super();
    // 4096 amostras a 16 kHz = 256 ms por mensagem. Menor que isso inunda a
    // porta de mensagens; maior atrasa o primeiro parcial sem ganho.
    this.tamanho = 4096;
    this.buffer = new Float32Array(this.tamanho);
    this.escritos = 0;
  }

  process(entradas) {
    const canal = entradas[0]?.[0];
    if (!canal) return true; // sem entrada ainda: mantém o nó vivo

    for (let i = 0; i < canal.length; i++) {
      this.buffer[this.escritos++] = canal[i];
      if (this.escritos === this.tamanho) {
        // Cópia porque o buffer é reaproveitado no próximo ciclo.
        this.port.postMessage(this.buffer.slice(0));
        this.escritos = 0;
      }
    }
    return true;
  }
}

registerProcessor("encaminhador-pcm", EncaminhadorPCM);
