"""O worklet que reamostra o áudio para 16 kHz — rodado num Chrome de verdade.

Este teste existe por causa de um bug real: a voz do entrevistado, quando vinha
pela chamada em vez do microfone, chegava MUDA e o Whisper descartava a resposta
inteira. A causa era o `AudioContext` forçado a 16 kHz recebendo a faixa do
WebRTC a 48 kHz — o `MediaStreamAudioSourceNode` de faixa remota devolve silêncio
nesse descompasso, no Chrome. A correção foi rodar o contexto na taxa nativa e
reamostrar para 16 kHz dentro do `worklet-pcm.js`.

O que ele prova, e que nenhum teste de unidade em Node provaria (não há
`AudioWorkletProcessor` fora do navegador): tocando uma senoide de 440 Hz num
contexto a 48 kHz, o worklet devolve áudio que **não é silêncio**, na frequência
certa, e cuja frequência só fecha se a taxa de saída for de fato 16 kHz. É o
caminho exato do conserto.

NÃO testa a faixa REMOTA do WebRTC em si — isso exigiria um segundo par numa
chamada Jitsi. Testa a peça consertada: a reamostragem de 48→16 kHz, que é o que
deixava de sair silêncio.

Rodar: .venv\\Scripts\\python.exe -m tests.test_worklet
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
WORKLET = BASE / "frontend" / "public" / "worklet-pcm.js"
PORTA = 8124

CAMINHOS_CHROME = [
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
    / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
    / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
]


def achar_chrome() -> Path | None:
    for caminho in CAMINHOS_CHROME:
        if caminho.is_file():
            return caminho
    do_path = shutil.which("chrome") or shutil.which("google-chrome")
    return Path(do_path) if do_path else None


PAGINA = """<!doctype html><meta charset="utf-8"><title>worklet</title>
<script type="module">
const R = [];
const anota = (ok, o_que, extra = "") => R.push({ ok, o_que, extra });
async function run() {
  try {
    const ctx = new AudioContext({ sampleRate: 48000 });
    await ctx.resume();
    anota(ctx.sampleRate === 48000, "contexto abre a 48 kHz (a taxa que quebrava)", ctx.sampleRate);

    await ctx.audioWorklet.addModule("./worklet-pcm.js");
    const osc = new OscillatorNode(ctx, { frequency: 440, type: "sine" });
    const node = new AudioWorkletNode(ctx, "encaminhador-pcm", {
      processorOptions: { taxaEntrada: ctx.sampleRate },
    });
    const chunks = [];
    node.port.onmessage = (e) => chunks.push(e.data);
    const mudo = ctx.createGain();
    mudo.gain.value = 0;
    osc.connect(node);
    node.connect(mudo).connect(ctx.destination);

    osc.start();
    await new Promise((r) => setTimeout(r, 1500));
    osc.stop();

    const tot = chunks.reduce((s, c) => s + c.length, 0);
    const all = new Float32Array(tot);
    let o = 0;
    for (const c of chunks) { all.set(c, o); o += c.length; }

    // Áudio de fato saiu (o headless renderiza mais devagar que o relógio, então
    // não se cobra a duração — só que veio material sustentado, mais de um bloco).
    anota(all.length >= 4096, "o worklet entregou áudio, não uma rajada vazia", all.length + " amostras");

    let sum = 0;
    for (let i = 0; i < all.length; i++) sum += all[i] * all[i];
    const rms = Math.sqrt(sum / (all.length || 1));
    anota(rms > 0.1, "a saída NÃO é silêncio (era esse o bug)", "RMS=" + rms.toFixed(3));

    // A frequência só fecha em 440 se a taxa de saída for mesmo 16 kHz: é a
    // prova de que a reamostragem 48->16 acertou, não só de que saiu som.
    let zc = 0;
    for (let i = 1; i < all.length; i++) if ((all[i - 1] < 0) !== (all[i] < 0)) zc++;
    const freq = (zc / 2) / ((all.length || 1) / 16000);
    anota(Math.abs(freq - 440) < 45, "440 Hz preservados após reamostrar 48k->16k", freq.toFixed(1) + " Hz");
  } catch (e) {
    anota(false, "estourou", String((e && e.stack) || e));
  }
  navigator.sendBeacon("/resultado", JSON.stringify(R));
}
run();
</script>
"""


def main_teste() -> int:
    chrome = achar_chrome()
    if chrome is None:
        print("PULADO: Chrome não encontrado — este teste precisa de um navegador real.")
        return 0
    if not WORKLET.is_file():
        print(f"  FALHA worklet não encontrado em {WORKLET}")
        return 1

    with tempfile.TemporaryDirectory() as pasta:
        raiz = Path(pasta)
        shutil.copy(WORKLET, raiz / "worklet-pcm.js")
        (raiz / "teste.html").write_text(PAGINA, encoding="utf-8")

        resultado: list[dict] = []
        chegou = threading.Event()

        class Manipulador(SimpleHTTPRequestHandler):
            def __init__(self, *a, **kw):
                super().__init__(*a, directory=str(raiz), **kw)

            def do_POST(self):
                corpo = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                resultado.extend(json.loads(corpo))
                self.send_response(204)
                self.end_headers()
                chegou.set()

            def log_message(self, *a):
                pass

        servidor = HTTPServer(("127.0.0.1", PORTA), Manipulador)
        threading.Thread(target=servidor.serve_forever, daemon=True).start()

        perfil = tempfile.mkdtemp()
        navegador = subprocess.Popen(
            [
                str(chrome),
                "--headless=new",
                "--no-sandbox",
                f"--user-data-dir={perfil}",
                "--autoplay-policy=no-user-gesture-required",
                f"http://127.0.0.1:{PORTA}/teste.html",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            respondeu = chegou.wait(60)
        finally:
            navegador.terminate()
            servidor.shutdown()
            shutil.rmtree(perfil, ignore_errors=True)

        if not respondeu:
            print("  FALHA o navegador não devolveu resultado em 60s")
            return 1

    falhas = 0
    for passo in resultado:
        falhas += 0 if passo["ok"] else 1
        extra = f"  ({passo['extra']})" if passo.get("extra") else ""
        print(f"  {'PASS' if passo['ok'] else 'FALHA'} {passo['o_que']}{extra}")

    print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
