"use client";

/* Quanto som está REALMENTE passando por uma faixa de áudio.
 *
 * POR QUE ISTO PRECISOU EXISTIR
 *
 * Até aqui o sistema sabia dizer que o microfone tinha PERMISSÃO e que uma
 * faixa remota tinha CHEGADO. Nenhuma das duas coisas é a pergunta que importa
 * numa entrevista, que é: está entrando voz? As duas podem estar verdadeiras
 * com o cliente mudo — fone Bluetooth pareado no aparelho errado, entrada
 * trocada no sistema, microfone tomado por outro app. O cliente via um ✓ verde
 * e ninguém o ouvia; foi o que aconteceu na chamada de 15/09/2026.
 *
 * DOIS CUIDADOS QUE JÁ CUSTARAM CARO NESTE REPOSITÓRIO
 *
 * 1. O `AudioContext` roda na taxa NATIVA, sem `sampleRate` forçado. Forçar
 *    16 kHz num contexto que recebe faixa de WebRTC a 48 kHz faz o
 *    `MediaStreamAudioSourceNode` devolver silêncio — foi o defeito que manteve
 *    a transcrição da chamada desligada por semanas (ver `CONTEXTO.md` e
 *    `worklet-pcm.js`). Aqui só se mede volume, então a taxa é indiferente:
 *    usar a nativa é de graça e não repete o erro.
 *
 * 2. Faixa REMOTA só alimenta o WebAudio depois de ligada a um elemento de
 *    mídia. Quem faz isso é `ChamadaJitsi.receberFaixa`, que dá `attach` num
 *    `<audio>` — por isso medir a faixa do outro lado funciona. Medir uma faixa
 *    remota solta devolveria zero para sempre, o que aqui seria pior que não
 *    medir: a tela acusaria silêncio com o cliente falando.
 */

/** Acima disto é voz, e não ruído de fundo. Medido no RMS normalizado. */
export const LIMIAR_VOZ = 0.025;

/** De quanto em quanto tempo se lê o nível. 100 ms é imperceptível ao olho e
 *  não acorda a CPU do celular a cada quadro como um `requestAnimationFrame`. */
const INTERVALO_MS = 100;

export interface Medidor {
  parar(): void;
}

/** Mede o volume de `trilha` e chama `aoNivel` com um número de 0 a 1.
 *
 * Devolve o cancelamento. Chamar `parar()` solta o `AudioContext` — sem isso,
 * cada troca de microfone deixaria um contexto vivo, e o navegador limita
 * quantos existem por página. */
export function medirNivel(
  trilha: MediaStreamTrack,
  aoNivel: (nivel: number) => void,
): Medidor {
  let parado = false;
  let ctx: AudioContext | null = null;
  let timer: number | null = null;

  const encerrar = () => {
    if (parado) return;
    parado = true;
    if (timer !== null) window.clearInterval(timer);
    timer = null;
    void ctx?.close().catch(() => {});
    ctx = null;
  };

  try {
    ctx = new AudioContext();
    /* O contexto nasce suspenso quando a página ainda não recebeu gesto do
     * usuário. Aqui sempre houve clique antes (testar o microfone, entrar na
     * chamada), então o `resume` costuma passar; se não passar, o nível fica em
     * zero e quem chama decide o que dizer. */
    void ctx.resume().catch(() => {});

    const fonte = ctx.createMediaStreamSource(new MediaStream([trilha]));
    const analisador = ctx.createAnalyser();
    analisador.fftSize = 1024;
    // Sem suavização própria: a leitura é a cada 100 ms e o pico curto de uma
    // sílaba é justamente o que precisa aparecer na barra.
    analisador.smoothingTimeConstant = 0;
    fonte.connect(analisador);

    const amostras = new Uint8Array(analisador.fftSize);

    timer = window.setInterval(() => {
      if (parado) return;
      analisador.getByteTimeDomainData(amostras);
      /* RMS, e não pico: o pico dispara com qualquer estalo e deixaria a barra
       * cheia o tempo todo. O `- 128` centra a onda, que chega de 0 a 255. */
      let soma = 0;
      for (const amostra of amostras) {
        const desvio = (amostra - 128) / 128;
        soma += desvio * desvio;
      }
      aoNivel(Math.min(1, Math.sqrt(soma / amostras.length) * 2.2));
    }, INTERVALO_MS);
  } catch {
    /* Navegador sem WebAudio, ou contexto recusado. Medir volume é apoio: a
     * chamada funciona sem a barra, e derrubar a tela por causa dela seria
     * trocar um problema pequeno por um grande. */
    encerrar();
  }

  return { parar: encerrar };
}
