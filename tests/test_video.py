"""Gravação de vídeo da entrevista — rodada num Chrome de verdade.

Este é o único teste do projeto que abre um navegador, e há um motivo: o que
está sendo testado é `MediaRecorder`, câmera e `Blob`. Nada disso existe fora do
navegador, e um dublê provaria apenas que o dublê funciona — justamente na parte
em que o comportamento real varia de versão para versão do Chrome.

O que ele prova, e que ninguém consegue afirmar lendo o código:

- que este Chrome grava em **MP4** (e não só em WebM), que é o formato pedido;
- que a extensão do arquivo bate com o contêiner que saiu de verdade;
- que o arquivo abre num player, com duração legível;
- que o vídeo vive só em `blob:` — nada foi para o servidor, que é o combinado;
- que `descartar` revoga o blob e devolve a memória.

Como funciona: compila `lib/gravacaoVideo.ts` com o `tsc` do próprio projeto,
serve a página num `127.0.0.1` (getUserMedia exige contexto seguro, e localhost
conta), e sobe o Chrome headless com câmera e microfone falsos. A página devolve
o resultado por `sendBeacon`.

Rodar: .venv\\Scripts\\python.exe -m tests.test_video
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
FRONTEND = BASE / "frontend"
PORTA = 8123

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
    doPath = shutil.which("chrome") or shutil.which("google-chrome")
    return Path(doPath) if doPath else None


# A página é o teste. Fica aqui, e não num .html à parte, para não haver duas
# metades de um mesmo arquivo em pastas diferentes.
PAGINA = """<!doctype html>
<meta charset="utf-8">
<title>gravador de video</title>
<script type="module">
import { GravacaoVideo, podeGravarVideo } from "./gravacaoVideo.js";

const passos = [];
const anota = (ok, o_que, extra = "") => passos.push({ ok, o_que, extra });

async function principal() {
  anota(podeGravarVideo(), "o navegador sabe gravar video");

  let pronto = null;
  const erros = [];
  const g = new GravacaoVideo({
    onPronto: (v) => (pronto = v),
    onErro: (m) => erros.push(m),
  });

  await g.iniciar("camera");
  anota(g.estado === "gravando", "entra em gravando", g.estado);
  anota(g.temPendente === false, "nada pendente enquanto grava");

  await new Promise((ok) => setTimeout(ok, 3500));
  const decorrido = g.decorridoS;
  g.parar();
  await new Promise((ok) => setTimeout(ok, 1200));  // o onstop monta o arquivo

  anota(pronto !== null, "o arquivo fica pronto depois de parar");
  anota(erros.length === 0, "sem erros", erros.join(" | "));
  anota(g.estado === "pronto", "estado final e pronto", g.estado);
  anota(g.temPendente === true, "fica marcado como ainda NAO baixado");
  anota(decorrido > 3 && decorrido < 5, "o cronometro bate com o relogio", String(decorrido));

  if (pronto) {
    anota(pronto.bytes > 20000, "o video tem conteudo", pronto.bytes + " bytes");
    anota(pronto.url.startsWith("blob:"), "vive em blob local, sem servidor");
    const ext = pronto.nome.split(".").pop();
    anota(
      (pronto.tipo.includes("mp4") && ext === "mp4") ||
        (pronto.tipo.includes("webm") && ext === "webm"),
      "a extensao bate com o conteiner gravado",
      pronto.tipo + " -> ." + ext,
    );
    anota(pronto.tipo.includes("mp4"), "este Chrome grava em MP4", pronto.tipo);
    anota(
      /^Entrevista \\d\\d-\\d\\d-\\d{4} \\d\\dh\\d\\d\\./.test(pronto.nome),
      "nome de arquivo legivel",
      pronto.nome,
    );

    const buf = new Uint8Array(await (await fetch(pronto.url)).arrayBuffer());
    const cabeca = new TextDecoder("latin1").decode(buf.slice(0, 4096));
    if (pronto.tipo.includes("mp4")) {
      anota(cabeca.includes("ftyp"), "MP4 de verdade (atomo ftyp)");
      anota(cabeca.includes("avc1") || cabeca.includes("mp4a"), "com faixa de video e de audio");
    } else {
      anota(buf[0] === 0x1a && buf[1] === 0x45, "WebM de verdade (EBML)");
    }

    const el = document.createElement("video");
    el.src = pronto.url;
    const dur = await new Promise((ok) => {
      el.onloadedmetadata = () => ok(el.duration);
      el.onerror = () => ok(-1);
      setTimeout(() => ok(-2), 4000);
    });
    anota(dur === Infinity || dur > 2, "o player abre o arquivo", "duracao=" + dur);
  }

  g.marcarBaixado();
  anota(g.temPendente === false, "baixar tira a marca de pendente");

  const url = pronto?.url;
  g.descartar();
  const morto = await fetch(url).then(() => false).catch(() => true);
  anota(morto, "descartar revoga o blob e devolve a memoria");

  g.encerrar();
  return passos;
}

principal()
  .then((p) => navigator.sendBeacon("/resultado", JSON.stringify(p)))
  .catch((e) =>
    navigator.sendBeacon(
      "/resultado",
      JSON.stringify([{ ok: false, o_que: "estourou", extra: String((e && e.stack) || e) }]),
    ),
  );
</script>
"""


def _compilar(destino: Path) -> str | None:
    """`lib/gravacaoVideo.ts` -> JS de módulo. Devolve o erro, ou None."""
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if npx is None:
        return "npx não encontrado (Node.js não está no PATH)."
    proc = subprocess.run(
        [
            npx, "tsc", "lib/gravacaoVideo.ts",
            "--target", "es2020", "--module", "es2020",
            "--lib", "es2020,dom", "--moduleResolution", "bundler",
            "--outDir", str(destino),
        ],
        cwd=FRONTEND,
        capture_output=True,
        text=True,
        timeout=300,
    )
    return None if proc.returncode == 0 else (proc.stdout + proc.stderr)[:800]


def main_teste() -> int:
    chrome = achar_chrome()
    if chrome is None:
        print("PULADO: Chrome não encontrado — este teste precisa de um navegador real.")
        return 0

    with tempfile.TemporaryDirectory() as pasta:
        raiz = Path(pasta)
        if (erro := _compilar(raiz)) is not None:
            print(f"  FALHA não foi possível compilar o gravador:\n{erro}")
            return 1
        (raiz / "teste.html").write_text(PAGINA, encoding="utf-8")

        resultado: list[dict] = []
        chegou = threading.Event()

        class Manipulador(SimpleHTTPRequestHandler):
            def __init__(self, *a, **kw):
                super().__init__(*a, directory=str(raiz), **kw)

            def do_POST(self):  # o sendBeacon da página
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
                # Câmera e microfone sintéticos, e permissão concedida sem
                # ninguém para clicar no aviso.
                "--use-fake-device-for-media-stream",
                "--use-fake-ui-for-media-stream",
                "--autoplay-policy=no-user-gesture-required",
                f"http://127.0.0.1:{PORTA}/teste.html",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            respondeu = chegou.wait(90)
        finally:
            navegador.terminate()
            servidor.shutdown()
            shutil.rmtree(perfil, ignore_errors=True)

        if not respondeu:
            print("  FALHA o navegador não devolveu resultado em 90s")
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
