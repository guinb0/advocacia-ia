"""Conversão fiel dos modelos DOCX para PDF pelo LibreOffice."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


class ErroConversaoDocx(Exception):
    pass


def _executavel() -> str:
    encontrado = shutil.which("soffice") or shutil.which("libreoffice")
    if encontrado:
        return encontrado
    for candidato in (
        Path(r"C:\Program Files\LibreOffice\program\soffice.exe"),
        Path(r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"),
    ):
        if candidato.is_file():
            return str(candidato)
    raise ErroConversaoDocx("A conversão para PDF não está instalada no servidor.")


def converter(docx: bytes) -> bytes:
    if not docx:
        raise ErroConversaoDocx("O documento gerado está vazio.")
    with tempfile.TemporaryDirectory(prefix="contrato-pdf-") as temporario:
        pasta = Path(temporario)
        origem = pasta / "documento.docx"
        origem.write_bytes(docx)
        perfil = pasta / "perfil-libreoffice"
        try:
            processo = subprocess.run(
                [
                    _executavel(), "--headless", "--nologo", "--nodefault", "--nolockcheck",
                    f"-env:UserInstallation={perfil.as_uri()}",
                    "--convert-to", "pdf:writer_pdf_Export", "--outdir", str(pasta), str(origem),
                ],
                capture_output=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ErroConversaoDocx("Não foi possível converter o documento para PDF.") from exc
        destino = pasta / "documento.pdf"
        if processo.returncode != 0 or not destino.is_file() or destino.stat().st_size == 0:
            raise ErroConversaoDocx("O LibreOffice não conseguiu gerar o PDF do documento.")
        return destino.read_bytes()
