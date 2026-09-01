from pathlib import Path

from app import docx_pdf


def test_converte_docx_em_pdf_sem_deixar_arquivo_temporario(monkeypatch):
    monkeypatch.setattr(docx_pdf, "_executavel", lambda: "soffice")

    def executar(comando, **_opcoes):
        pasta = Path(comando[comando.index("--outdir") + 1])
        (pasta / "documento.pdf").write_bytes(b"%PDF-1.7\ncontrato")

        class Resultado:
            returncode = 0

        return Resultado()

    monkeypatch.setattr(docx_pdf.subprocess, "run", executar)

    assert docx_pdf.converter(b"PK\x03\x04docx").startswith(b"%PDF-")
