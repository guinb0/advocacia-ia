"""Verifica se o OCR aguenta chamadas simultâneas (vários uploads ao mesmo tempo).

Rodar: .venv\\Scripts\\python.exe -m tests.test_concorrencia
"""

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

N_THREADS = 3


def main() -> int:
    import cv2

    from app.ocr_engine import rodar_ocr

    amostra = Path(__file__).resolve().parent / "amostras" / "cnh.png"
    if not amostra.is_file():
        print("Rode tests.test_pipeline antes para gerar as amostras.")
        return 1

    img = cv2.imread(str(amostra))
    rodar_ocr(img)  # aquece o modelo fora da medição

    resultados: dict[int, object] = {}
    barreira = threading.Barrier(N_THREADS)

    def tarefa(n: int) -> None:
        try:
            barreira.wait()  # todas partem no mesmo instante
            t = time.perf_counter()
            linhas = rodar_ocr(img)
            resultados[n] = (len(linhas), round(time.perf_counter() - t, 2))
        except Exception as exc:
            resultados[n] = exc

    t0 = time.perf_counter()
    threads = [threading.Thread(target=tarefa, args=(i,)) for i in range(N_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    total = time.perf_counter() - t0

    falhas = 0
    for n in sorted(resultados):
        r = resultados[n]
        if isinstance(r, Exception):
            print(f"  thread {n}: FALHOU -> {type(r).__name__}: {r}")
            falhas += 1
        else:
            print(f"  thread {n}: OK, {r[0]} linhas em {r[1]}s")

    print(f"\n  tempo total: {total:.2f}s")
    print(f"\n{'TODAS AS THREADS PASSARAM' if not falhas else f'{falhas} THREAD(S) FALHARAM'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
