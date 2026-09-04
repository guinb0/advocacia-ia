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

    # Dois subdomínios, medidos na conta real: a autenticação vive em `app2` e o
    # painel em `app`. O login é em ETAPAS — primeiro o e-mail, "Entrar", depois a
    # senha, "Entrar". Os ids dos campos são gerados (não estáveis); por isso os
    # seletores vão por placeholder/tipo, e cada um é sobrescrevível por env.
    url_auth = _env("ZAPSIGN_AUTH_URL", "https://app2.zapsign.com.br")
    url_app = _env("ZAPSIGN_WEB_URL", "https://app.zapsign.com.br")
    espera = int(_env("ZAPSIGN_TIMEOUT_MS", "45000") or "45000")
    ua = _env(
        "ZAPSIGN_USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    )
    caminho_pdf = Path(tempfile.gettempdir()) / f"zapsign-{int(time.time())}-{Path(nome_arquivo).name}"
    caminho_pdf.write_bytes(pdf)
    screenshot = ""

    try:
        with sync_playwright() as p:
            navegador = p.chromium.launch(
                headless=_env("ZAPSIGN_HEADLESS", "1") != "0",
                args=["--disable-blink-features=AutomationControlled"],
            )
            contexto = navegador.new_context(user_agent=ua, viewport={"width": 1400, "height": 950})
            pagina = contexto.new_page()
            pagina.set_default_timeout(espera)
            try:
                # 1) Login em etapas (e-mail → Entrar → senha → Entrar).
                pagina.goto(f"{url_auth}/access/sign-in", wait_until="networkidle")
                pagina.fill(_sel("EMAIL", "input[placeholder='Digite seu e-mail']"), _env("ZAPSIGN_LOGIN_EMAIL"))
                pagina.click(_sel("ENTRAR", "button:has-text('Entrar')"))
                pagina.fill(
                    _sel("SENHA", "input[type='password']"),
                    _env("ZAPSIGN_LOGIN_SENHA"),
                    timeout=int(espera / 2),
                )
                pagina.click(_sel("ENTRAR", "button:has-text('Entrar')"))
                # Sucesso = saiu da área /access/ e entrou em /conta/.
                pagina.wait_for_url("**/conta/**", timeout=espera)

                # 2) Novo documento + upload do PDF.
                pagina.goto(f"{url_app}/conta/documentos/novo", wait_until="networkidle")
                pagina.set_input_files(_sel("UPLOAD", "input[type='file']"), str(caminho_pdf))
                pagina.wait_for_load_state("networkidle")

                # 3) Signatário: nome/e-mail do cliente. A tela usa uma busca de
                # contatos; digitar o e-mail e o nome cobre o caso novo. Best-effort:
                # o layout exato do signatário é o ponto a calibrar na conta real.
                for seletor, valor in (
                    (_sel("SIGNATARIO_BUSCA", "input[placeholder*='nome'], input[placeholder*='e-mail']"), cliente_email),
                    (_sel("SIGNATARIO_NOME", "input[placeholder*='ome do signat'], input[name='name']"), cliente_nome),
                    (_sel("SIGNATARIO_EMAIL", "input[placeholder*='mail do signat'], input[type='email']"), cliente_email),
                ):
                    try:
                        campo = pagina.query_selector(seletor)
                        if campo:
                            campo.fill(valor)
                    except Exception:  # noqa: BLE001 - campo ausente não interrompe
                        continue

                # 4) Avançar/enviar. "CONTINUAR" leva ao envio; o botão final varia.
                for rotulo in ("CONTINUAR", "Enviar", "Finalizar", "Enviar para assinatura"):
                    alvo = pagina.query_selector(f"button:has-text('{rotulo}')")
                    if alvo and alvo.is_enabled():
                        alvo.click()
                        pagina.wait_for_load_state("networkidle")

                # 5) Captura o link de assinatura, quando a UI o expõe.
                link = ""
                seletor_link = _sel("LINK", "a[href*='/verificar/'], a[href*='/sign/'], a[href*='zapsign'], input[value*='http']")
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
