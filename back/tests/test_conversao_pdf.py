"""Conversão de entregas para PDF sem passar novamente pelo OCR."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PIL import Image

from app import conversao_pdf


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ocr-pdf-") as pasta:
        raiz = Path(pasta)
        original = raiz / "original.pdf"
        original.write_bytes(b"%PDF-1.7\n%teste\n")
        preservado = conversao_pdf.converter_para_pdf(original, "Original.pdf", raiz / "ignorar.pdf")
        assert preservado.caminho == original and not preservado.temporario

        imagem = raiz / "foto-transparente.png"
        Image.new("RGBA", (320, 180), (255, 255, 255, 120)).save(imagem)
        convertido = conversao_pdf.converter_para_pdf(imagem, "foto.png", raiz / "foto.pdf")
        assert convertido.temporario
        assert convertido.caminho.read_bytes().startswith(b"%PDF-")
        assert convertido.nome_download == "foto.pdf"

        multipagina = raiz / "frente-verso.tiff"
        frente = Image.new("RGB", (100, 100), "white")
        verso = Image.new("RGB", (100, 100), "gray")
        frente.save(multipagina, save_all=True, append_images=[verso])
        convertido = conversao_pdf.converter_para_pdf(multipagina, multipagina.name, raiz / "duas.pdf")
        assert convertido.caminho.read_bytes().startswith(b"%PDF-")

        # Foto de celular: o PDF gerado pelo próprio Acervo precisa caber de
        # volta no limite de upload (20 MB), sem carregar a resolução integral.
        grande = raiz / "foto-celular.png"
        Image.effect_noise((4000, 3000), 80).convert("RGB").save(grande)
        compacto = conversao_pdf.converter_para_pdf(grande, grande.name, raiz / "compacto.pdf")
        assert compacto.caminho.stat().st_size < 20 * 1024 * 1024
        assert compacto.caminho.stat().st_size < grande.stat().st_size

        # .docx passa pelo LibreOffice (`app/docx_pdf.py`), que não existe em
        # toda máquina de teste: o que importa aqui é o roteamento — .docx deixa
        # de cair na recusa por "tipo não suportado" e vira PDF temporário.
        docx = raiz / "qualificacao.docx"
        docx.write_bytes(b"PK\x03\x04fingindo-ser-docx")
        from app import docx_pdf

        real = docx_pdf.converter
        docx_pdf.converter = lambda conteudo: b"%PDF-1.7\nword"
        try:
            do_word = conversao_pdf.converter_para_pdf(docx, "Qualificacao.docx", raiz / "word.pdf")
            assert do_word.temporario
            assert do_word.caminho.read_bytes().startswith(b"%PDF-")
            assert do_word.nome_download == "Qualificacao.pdf"
        finally:
            docx_pdf.converter = real

        texto = raiz / "relato.txt"
        texto.write_text("não suportado", encoding="utf-8")
        try:
            conversao_pdf.converter_para_pdf(texto, texto.name, raiz / "relato.pdf")
        except conversao_pdf.ErroConversaoPdf:
            pass
        else:
            raise AssertionError("arquivo não suportado deveria ser recusado")
    print("conversao_pdf_ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
