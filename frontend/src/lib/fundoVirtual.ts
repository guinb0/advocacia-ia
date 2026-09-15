import type { ImageSegmenter } from "@mediapipe/tasks-vision";

const LARGURA = 640;
const FPS = 15;

let segmentador: Promise<ImageSegmenter> | null = null;

function carregarSegmentador(): Promise<ImageSegmenter> {
  if (!segmentador) {
    segmentador = (async () => {
      const { FilesetResolver, ImageSegmenter } = await import("@mediapipe/tasks-vision");
      const arquivos = await FilesetResolver.forVisionTasks("/mediapipe/wasm");
      const criar = (delegate: "GPU" | "CPU") =>
        ImageSegmenter.createFromOptions(arquivos, {
          baseOptions: { modelAssetPath: "/mediapipe/selfie_segmenter.tflite", delegate },
          runningMode: "VIDEO",
          outputCategoryMask: false,
          outputConfidenceMasks: true,
        });
      return criar("GPU").catch(() => criar("CPU"));
    })().catch((erro) => {
      segmentador = null;
      throw erro;
    });
  }
  return segmentador;
}

function carregarImagem(url: string): Promise<HTMLImageElement> {
  return new Promise((ok, falhou) => {
    const imagem = new Image();
    imagem.onload = () => ok(imagem);
    imagem.onerror = () => falhou(new Error("A imagem de fundo não carregou."));
    imagem.src = url;
  });
}

function relogio(intervaloMs: number, tique: () => void): () => void {
  const url = URL.createObjectURL(
    new Blob([`const t=setInterval(()=>postMessage(0),${intervaloMs});onmessage=()=>clearInterval(t);`], {
      type: "text/javascript",
    }),
  );
  const worker = new Worker(url);
  worker.onmessage = tique;
  return () => {
    worker.postMessage(0);
    worker.terminate();
    URL.revokeObjectURL(url);
  };
}

export function preCarregarFundoVirtual(urlImagem: string): void {
  void carregarSegmentador().catch(() => undefined);
  void carregarImagem(urlImagem).catch(() => undefined);
}

export function criarEfeitoFundo(urlImagem: string, aoFalhar?: (mensagem: string) => void) {
  let parar: (() => void) | null = null;
  let video: HTMLVideoElement | null = null;

  return {
    isEnabled: (faixa?: { getType?: () => string }) => faixa?.getType?.() !== "audio",

    startEffect(stream: MediaStream): MediaStream {
      const saida = document.createElement("canvas");
      saida.width = LARGURA;
      saida.height = Math.round((LARGURA * 9) / 16);
      const ctx = saida.getContext("2d");
      const mascara = document.createElement("canvas");
      const ctxMascara = mascara.getContext("2d", { willReadFrequently: true });
      const origem = document.createElement("video");
      origem.muted = true;
      origem.playsInline = true;
      origem.srcObject = stream;
      void origem.play().catch(() => undefined);
      video = origem;

      let fundo: HTMLImageElement | null = null;
      let seg: ImageSegmenter | null = null;
      let semSegmentacao = false;
      let inverter: boolean | null = null;
      let dimensionado = false;

      void carregarImagem(urlImagem).then((imagem) => (fundo = imagem)).catch(() => undefined);
      void carregarSegmentador()
        .then((s) => (seg = s))
        .catch(() => {
          semSegmentacao = true;
          aoFalhar?.("Não foi possível aplicar o fundo virtual neste computador. A câmera aparece sem o fundo.");
        });

      const desenharFundo = () => {
        if (!ctx) return;
        if (fundo) {
          const escala = Math.max(saida.width / fundo.width, saida.height / fundo.height);
          const w = fundo.width * escala;
          const h = fundo.height * escala;
          ctx.drawImage(fundo, (saida.width - w) / 2, (saida.height - h) / 2, w, h);
        } else {
          ctx.fillStyle = "#1b140f";
          ctx.fillRect(0, 0, saida.width, saida.height);
        }
      };

      parar = relogio(1000 / FPS, () => {
        if (!ctx || !ctxMascara) return;
        if (origem.readyState < 2 || !origem.videoWidth) {
          ctx.globalCompositeOperation = "source-over";
          desenharFundo();
          return;
        }
        if (!dimensionado) {
          saida.height = Math.round((LARGURA * origem.videoHeight) / origem.videoWidth);
          dimensionado = true;
        }
        if (semSegmentacao) {
          ctx.globalCompositeOperation = "source-over";
          ctx.drawImage(origem, 0, 0, saida.width, saida.height);
          return;
        }
        if (!seg) {
          ctx.globalCompositeOperation = "source-over";
          desenharFundo();
          return;
        }
        let resultado;
        try {
          resultado = seg.segmentForVideo(origem, performance.now());
        } catch {
          return;
        }
        const mapa = resultado.confidenceMasks?.[0];
        if (!mapa) {
          (resultado as { close?: () => void }).close?.();
          return;
        }
        const dados = mapa.getAsFloat32Array();
        const { width: w, height: h } = mapa;
        if (inverter === null) {
          let centro = 0;
          let nCentro = 0;
          let borda = 0;
          let nBorda = 0;
          for (let y = 0; y < h; y += 4) {
            for (let x = 0; x < w; x += 4) {
              const v = dados[y * w + x];
              if (x > w * 0.35 && x < w * 0.65 && y > h * 0.3 && y < h * 0.8) {
                centro += v;
                nCentro++;
              } else if (y < h * 0.15 && (x < w * 0.15 || x > w * 0.85)) {
                borda += v;
                nBorda++;
              }
            }
          }
          if (nCentro && nBorda) inverter = borda / nBorda > centro / nCentro;
        }
        if (mascara.width !== w || mascara.height !== h) {
          mascara.width = w;
          mascara.height = h;
        }
        const imagem = ctxMascara.createImageData(w, h);
        for (let i = 0; i < dados.length; i++) {
          imagem.data[i * 4 + 3] = (inverter ? 1 - dados[i] : dados[i]) * 255;
        }
        (resultado as { close?: () => void }).close?.();
        ctxMascara.putImageData(imagem, 0, 0);

        ctx.globalCompositeOperation = "copy";
        ctx.filter = "blur(3px)";
        ctx.drawImage(mascara, 0, 0, saida.width, saida.height);
        ctx.filter = "none";
        ctx.globalCompositeOperation = "source-in";
        ctx.drawImage(origem, 0, 0, saida.width, saida.height);
        ctx.globalCompositeOperation = "destination-over";
        desenharFundo();
        ctx.globalCompositeOperation = "source-over";
      });

      return saida.captureStream(FPS);
    },

    stopEffect(): void {
      parar?.();
      parar = null;
      if (video) {
        video.pause();
        video.srcObject = null;
      }
      video = null;
    },
  };
}
