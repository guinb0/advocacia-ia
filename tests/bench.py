"""Mede o custo do classificador de orientação de página.

Rodar: .venv\\Scripts\\python.exe -m tests.bench
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

AMOSTRAS = ["cnh.png", "ctps.png", "cpf.png", "cnh_deitada.png"]


def medir(doc_ori: bool) -> None:
    from paddleocr import PaddleOCR

    import cv2

    print(f"\n{'=' * 60}\nuse_doc_orientation_classify={doc_ori}\n{'=' * 60}")
    t0 = time.perf_counter()
    ocr = PaddleOCR(
        lang="pt",
        use_doc_orientation_classify=doc_ori,
        use_doc_unwarping=False,
        use_textline_orientation=True,
    )
    print(f"  carga do modelo ....... {time.perf_counter() - t0:.2f}s")

    base = Path(__file__).resolve().parent / "amostras"
    for nome in AMOSTRAS:
        caminho = base / nome
        if not caminho.is_file():
            print(f"  {nome:20} (ausente)")
            continue
        img = cv2.imread(str(caminho))

        ocr.predict(input=img)  # aquecimento: descarta a 1ª medição
        tempos = []
        for _ in range(3):
            t = time.perf_counter()
            saida = ocr.predict(input=img)
            tempos.append(time.perf_counter() - t)

        blocos = sum(len(r["rec_texts"]) for r in saida)
        print(f"  {nome:20} {min(tempos):5.2f}s (melhor de 3)  blocos={blocos}")


if __name__ == "__main__":
    medir(False)
    medir(True)
