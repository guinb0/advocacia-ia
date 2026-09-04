"""Envio de documento à assinatura pelo ZapSign via NAVEGADOR (Playwright).

POR QUE ISTO EXISTE

O plano do escritório não dá acesso à API do ZapSign — a única via é a interface
web. Este módulo abre um navegador headless, entra na conta, sobe o documento,
adiciona o cliente como signatário e dispara o envio por e-mail. O link
resultante volta para também ser mandado ao cliente pelo WhatsApp (Evolution).

REGRAS QUE NÃO SE NEGOCIAM

- **Credencial só do ambiente.** `ZAPSIGN_LOGIN_EMAIL` e `ZAPSIGN_LOGIN_SENHA`
  nunca entram no código nem no Git; em produção vão como variável de CI/CD.
- **Desligado por padrão.** Só age quando `configurado()` — sem credencial, quem
  chama cai no caminho de sempre. Assim uma automação frágil não derruba o envio.
- **Seletores configuráveis.** A UI do ZapSign muda; os seletores têm padrão mas
  aceitam sobrescrita por env (`ZAPSIGN_SEL_*`) para ajuste sem novo deploy. Em
  qualquer falha, salva um screenshot para o ajuste ser rápido.

ESTE MÓDULO NÃO É TESTÁVEL SEM A CONTA REAL. A automação de UII exige uma passada
de calibração dos seletores contra a conta do escritório — ver `docs/` e o
screenshot de falha em `ZAPSIGN_SCREENSHOT_DIR`.
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("assinatura.navegador")


class ErroNavegador(RuntimeError):
    """Falha que o escritório precisa ver, com o que dá para fazer a respeito."""


def _env(nome: str, padrao: str = "") -> str:
    return os.getenv(nome, padrao).strip()


def configurado() -> bool:
    """Há credencial de login do ZapSign no ambiente?"""
    return bool(_env("ZAPSIGN_LOGIN_EMAIL") and _env("ZAPSIGN_LOGIN_SENHA"))


def _sel(nome: str, padrao: str) -> str:
    """Um seletor, com padrão sobrescrevível por env (`ZAPSIGN_SEL_<NOME>`)."""
    return _env(f"ZAPSIGN_SEL_{nome}", padrao)


def _dir_screenshots() -> Path:
    destino = Path(_env("ZAPSIGN_SCREENSHOT_DIR", tempfile.gettempdir())) / "zapsign"
    destino.mkdir(parents=True, exist_ok=True)
    return destino


def enviar_para_assinatura(
    pdf: bytes,
    nome_arquivo: str,
    cliente_nome: str,
    cliente_email: str,
) -> dict[str, Any]:
    """Sobe o PDF ao ZapSign pela web e dispara o envio ao cliente por e-mail.

    Devolve `{"ok": bool, "link": str, "erro": str, "screenshot": str}`. Nunca
    levanta para o chamador: o envio por WhatsApp e a resposta da tela dependem
    do que aqui aconteceu, e um traceback cru não ajudaria o secretário.
    """
    if not configurado():
        return {"ok": False, "link": "", "erro": "Login do ZapSign não configurado no ambiente.", "screenshot": ""}
    try:
        from playwright.sync_api import TimeoutError as PWTimeout, sync_playwright
    except ImportError:
        return {
            "ok": False,
            "link": "",
            "erro": "Playwright não está instalado no servidor (pip install playwright && playwright install chromium).",
            "screenshot": "",
        }

    base = _env("ZAPSIGN_WEB_URL", "https://app.zapsign.com.br")
    espera = int(_env("ZAPSIGN_TIMEOUT_MS", "45000") or "45000")
    caminho_pdf = Path(tempfile.gettempdir()) / f"zapsign-{int(time.time())}-{Path(nome_arquivo).name}"
    caminho_pdf.write_bytes(pdf)
    screenshot = ""

    try:
        with sync_playwright() as p:
            navegador = p.chromium.launch(headless=_env("ZAPSIGN_HEADLESS", "1") != "0")
            pagina = navegador.new_page()
            pagina.set_default_timeout(espera)
            try:
                # 1) Login
                pagina.goto(f"{base}/login", wait_until="domcontentloaded")
                pagina.fill(_sel("EMAIL", "input[type='email'], input[name='email']"), _env("ZAPSIGN_LOGIN_EMAIL"))
                pagina.fill(_sel("SENHA", "input[type='password'], input[name='password']"), _env("ZAPSIGN_LOGIN_SENHA"))
                pagina.click(_sel("ENTRAR", "button[type='submit']"))
                pagina.wait_for_load_state("networkidle")

                # 2) Novo documento + upload do PDF
                pagina.goto(f"{base}/doc/new", wait_until="domcontentloaded")
                pagina.set_input_files(_sel("UPLOAD", "input[type='file']"), str(caminho_pdf))
                pagina.wait_for_load_state("networkidle")

                # 3) Signatário: nome + e-mail do cliente
                pagina.fill(_sel("SIGNATARIO_NOME", "input[name='name'], input[placeholder*='ome']"), cliente_nome)
                pagina.fill(_sel("SIGNATARIO_EMAIL", "input[name='email'], input[placeholder*='mail']"), cliente_email)

                # 4) Enviar para assinatura
                pagina.click(_sel("ENVIAR", "button:has-text('Enviar'), button:has-text('assinatura')"))
                pagina.wait_for_load_state("networkidle")

                # 5) Captura o link de assinatura, quando a UI o expõe.
                link = ""
                seletor_link = _sel("LINK", "a[href*='/verificar/'], a[href*='/sign/'], input[value*='http']")
                try:
                    el = pagina.wait_for_selector(seletor_link, timeout=int(espera / 3))
                    link = (el.get_attribute("href") or el.get_attribute("value") or "").strip()
                except PWTimeout:
                    link = ""

                navegador.close()
                return {"ok": True, "link": link, "erro": "", "screenshot": ""}
            except Exception as exc:  # noqa: BLE001 - falha de UI vira mensagem + print
                try:
                    screenshot = str(_dir_screenshots() / f"falha-{int(time.time())}.png")
                    pagina.screenshot(path=screenshot, full_page=True)
                except Exception:  # noqa: BLE001
                    screenshot = ""
                navegador.close()
                log.warning("ZapSign (navegador) falhou: %s", str(exc)[:200])
                return {
                    "ok": False,
                    "link": "",
                    "erro": (
                        "Não foi possível concluir o envio pelo site do ZapSign. "
                        "Confira o login e os seletores da tela (o screenshot da falha ajuda)."
                    ),
                    "screenshot": screenshot,
                }
    finally:
        try:
            caminho_pdf.unlink(missing_ok=True)
        except OSError:
            pass
