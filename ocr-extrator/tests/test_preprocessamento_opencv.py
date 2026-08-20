import cv2
import numpy as np

from app.quality import preparar_para_ocr, recortar_documento


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


def test_crop_remove_fundo_somente_com_quatro_bordas_claras() -> None:
    foto = np.zeros((1200, 1600, 3), dtype=np.uint8)
    pontos = np.array([[220, 180], [1410, 240], [1320, 980], [170, 910]], dtype=np.int32)
    cv2.fillConvexPoly(foto, pontos, (235, 235, 235))
    cv2.putText(foto, "DOCUMENTO", (420, 590), cv2.FONT_HERSHEY_SIMPLEX, 2, (20, 20, 20), 5)
    recorte, aplicado = recortar_documento(foto)
    assert aplicado is True
    assert recorte.shape[0] < foto.shape[0]
    assert recorte.shape[1] < foto.shape[1]


def test_crop_nao_inventa_borda_em_foto_sem_documento() -> None:
    gradiente = np.tile(np.arange(1000, dtype=np.uint8), (700, 1))
    foto = cv2.cvtColor(gradiente, cv2.COLOR_GRAY2BGR)
    recorte, aplicado = recortar_documento(foto)
    assert aplicado is False
    assert recorte.shape == foto.shape
