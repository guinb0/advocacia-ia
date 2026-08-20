import cv2
import numpy as np

from app.quality import preparar_para_ocr


def test_limita_foto_de_celular_sem_deformar() -> None:
    imagem = np.full((4000, 3000, 3), 180, dtype=np.uint8)
    pronta = preparar_para_ocr(imagem)
    assert pronta.shape[:2] == (2000, 1500)
    assert pronta.dtype == np.uint8


def test_recupera_documento_escuro_e_preserva_bordas() -> None:
    imagem = np.full((600, 900, 3), 35, dtype=np.uint8)
    cv2.putText(imagem, "CPF 123.456.789-00", (40, 310), cv2.FONT_HERSHEY_SIMPLEX, 1.3, (100, 100, 100), 3)
    antes = cv2.cvtColor(imagem, cv2.COLOR_BGR2GRAY)
    pronta = preparar_para_ocr(imagem)
    depois = cv2.cvtColor(pronta, cv2.COLOR_BGR2GRAY)
    assert depois.mean() > antes.mean()
    assert cv2.Laplacian(depois, cv2.CV_64F).var() > 0


def test_imagem_vazia_falha_com_mensagem_clara() -> None:
    try:
        preparar_para_ocr(np.empty((0, 0, 3), dtype=np.uint8))
    except ValueError as exc:
        assert "vazia" in str(exc).lower()
    else:
        raise AssertionError("imagem vazia deveria ser recusada")
