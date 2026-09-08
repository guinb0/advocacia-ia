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
import re
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


# Um LINK DE ASSINATURA de verdade carrega o token do signatário no caminho —
# `/verificar/<uuid>`, `/sign/…`, `/signatario/…`. Uma página genérica do ZapSign
# (o "ferramentas" do rodapé, a home) NÃO tem isso. Casar por `zapsign` no href,
# como antes, pegava o link do rodapé e o mandava ao cliente como se fosse a
# assinatura. A extração agora exige um destes trechos no caminho.
PADROES_LINK = ("/verificar/", "/sign/", "/signatario/", "/assinar/", "/doc-token/")


def _e_link_de_assinatura(url: str) -> bool:
    u = (url or "").strip().lower()
    return u.startswith("http") and any(p in u for p in PADROES_LINK)


#: URL solta no meio do texto — o link de assinatura do ZapSign aparece como
#: TEXTO na tela (ao lado de "Copiar link"), não como `<a href>`.
_RE_URL = re.compile(r"https?://[^\s\"'<>)]+", re.I)


def _login(pagina: Any, url_auth: str, espera: int) -> None:
    """Login em etapas (e-mail → Entrar → senha → Entrar). Levanta se não entrar.

    `domcontentloaded` em vez de `networkidle`: o ZapSign é um SPA que mantém
    conexão viva (polling/analytics), e esperar a rede "silenciar" era o grosso
    da demora — cada passo ficava parado até estourar o timeout.
    """
    pagina.goto(f"{url_auth}/access/sign-in", wait_until="domcontentloaded")
    pagina.fill(_sel("EMAIL", "input[placeholder='Digite seu e-mail']"), _env("ZAPSIGN_LOGIN_EMAIL"))
    pagina.click(_sel("ENTRAR", "button:has-text('Entrar')"))
    pagina.fill(
        _sel("SENHA", "input[type='password']"),
        _env("ZAPSIGN_LOGIN_SENHA"),
        timeout=int(espera / 2),
    )
    pagina.click(_sel("ENTRAR", "button:has-text('Entrar')"))
    pagina.wait_for_url("**/conta/**", timeout=espera)


def _extrair_link(pagina: Any, espera: int) -> str:
    """O link de assinatura exposto na tela — só se for de assinatura de verdade.

    Varre âncoras e campos e devolve o PRIMEIRO cujo destino casa com um padrão
    de assinatura. Nunca devolve link genérico: melhor voltar vazio (e o chamador
    dizer que não achou) do que mandar o cliente para a home do ZapSign.
    """
    seletor = ", ".join(
        [f"a[href*='{p}']" for p in PADROES_LINK] + [f"input[value*='{p}']" for p in PADROES_LINK]
    )
    try:
        pagina.wait_for_selector(seletor, timeout=int(espera / 3))
    except Exception:  # noqa: BLE001 - sem link à vista; segue para a varredura manual
        pass
    # 1) Âncora ou campo cujo destino é um link de assinatura.
    for el in pagina.query_selector_all("a, input"):
        try:
            valor = (el.get_attribute("href") or el.get_attribute("value") or "").strip()
        except Exception:  # noqa: BLE001
            continue
        if _e_link_de_assinatura(valor):
            return valor
    # 2) O link no ZapSign vem como TEXTO na tela de envio (ao lado de "Copiar
    # link"), não num href — então varre o texto visível da página por uma URL
    # de assinatura. É isto que pega o `app.zapsign.com.br/verificar/<token>`.
    try:
        texto = pagina.inner_text("body")
    except Exception:  # noqa: BLE001
        texto = ""
    for url in _RE_URL.findall(texto):
        if _e_link_de_assinatura(url):
            return url.rstrip(".,;)")
    return ""


def _diagnostico_pagina(pagina: Any) -> str:
    """O que a página oferece AGORA: textos de botões e campos de formulário.

    Sem enxergar a UI do ZapSign, é isto que permite descobrir o seletor certo do
    passo em que a automação travou — os rótulos reais dos botões e os
    placeholders/nomes dos campos, na tela onde ela parou.
    """
    partes: list[str] = []
    try:
        rotulos: list[str] = []
        for b in pagina.query_selector_all("button, a[role='button'], [type='submit']")[:60]:
            try:
                txt = (b.inner_text() or "").strip().replace("\n", " ")
                estado = "" if b.is_enabled() else " (desabilitado)"
                if txt:
                    rotulos.append(txt[:40] + estado)
            except Exception:  # noqa: BLE001
                continue
        if rotulos:
            partes.append("BOTÕES: " + " | ".join(dict.fromkeys(rotulos)))
    except Exception:  # noqa: BLE001
        pass
    try:
        campos: list[str] = []
        for i in pagina.query_selector_all("input, textarea, select")[:60]:
            try:
                ph = i.get_attribute("placeholder") or ""
                nm = i.get_attribute("name") or ""
                tp = i.get_attribute("type") or "campo"
                desc = f"{tp}[{ph or nm}]" if (ph or nm) else tp
                campos.append(desc[:44])
            except Exception:  # noqa: BLE001
                continue
        if campos:
            partes.append("CAMPOS: " + " | ".join(dict.fromkeys(campos)))
    except Exception:  # noqa: BLE001
        pass
    return " || ".join(partes)[:1600]


def _clicar(pagina: Any, textos: tuple[str, ...], espera: int) -> bool:
    """Clica o primeiro botão/link cujo texto casa, esperando ele ficar clicável.

    `:has-text` é substring e ignora caixa, então "Continuar" acha "CONTINUAR".
    `.first.click()` AUTO-ESPERA a ação: se o botão está visível mas ainda
    desabilitado (upload em curso), aguarda habilitar — sem isto, ao tirar o
    `networkidle`, o clique caía num botão desabilitado e a etapa não avançava.
    `.first` também evita erro de múltiplos matches ("Continuar" casa também com
    "Continuar sem posicionar"). Devolve se clicou; SPA, cada avanço é um clique.
    """
    limite = min(int(espera / 2), 10000)
    for t in textos:
        try:
            pagina.locator(f"button:has-text('{t}'), a:has-text('{t}')").first.click(timeout=limite)
            return True
        except Exception:  # noqa: BLE001 - este rótulo não está nesta etapa; tenta o próximo
            continue
    return False


def _enviar_um(
    pagina: Any, caminho_pdf: Path, cliente_nome: str, cliente_email: str, url_app: str, espera: int
) -> str:
    """Percorre o assistente de 4 etapas do ZapSign e devolve o link de assinatura.

    Etapas (calibradas contra a conta real, ver prints em docs/):
      1. Selecionar documento — subir o PDF → "Continuar".
      2. Adicionar signatários — "Nome do signatário" (+ e-mail) → "Continuar".
      3. Posicionar assinaturas (opcional) — "Continuar sem posicionar".
      4. Enviar documento — "Enviar" → o link `/verificar/` aparece.
    """
    pagina.goto(f"{url_app}/conta/documentos/novo", wait_until="domcontentloaded")

    # 1) Subir o PDF e avançar. Não espera "networkidle" (trava em SPA); o clique
    # em "Continuar" já espera o botão ficar visível/habilitado.
    pagina.set_input_files(_sel("UPLOAD", "input[type='file']"), str(caminho_pdf))
    _clicar(pagina, ("Continuar",), espera)

    # 2) Signatário: nome e, quando o campo aparece, e-mail. O nome é obrigatório;
    # o e-mail costuma surgir depois de digitado o nome (ou já está visível).
    try:
        campo_nome = pagina.wait_for_selector(
            _sel("SIGNATARIO_NOME", "input[placeholder*='signat'], input[placeholder*='Nome do signat']"),
            timeout=espera,
            state="visible",
        )
        campo_nome.fill(cliente_nome)
    except Exception:  # noqa: BLE001 - sem o campo, o diagnóstico dirá o porquê
        pass
    try:
        campo_email = pagina.wait_for_selector(
            _sel("SIGNATARIO_EMAIL", "input[type='email'], input[placeholder*='mail']"),
            timeout=int(espera / 3),
            state="visible",
        )
        campo_email.fill(cliente_email)
    except Exception:  # noqa: BLE001 - e-mail pode não ser exigido nesta conta
        pass
    _clicar(pagina, ("Continuar",), espera)

    # 3) Posicionar assinaturas é OPCIONAL — seguir sem posicionar.
    _clicar(pagina, ("Continuar sem posicionar", "Salvar e continuar", "Continuar"), espera)

    # 4) Na tela de envio o link JÁ está à vista (o token do signatário é
    # permanente). Captura ANTES de finalizar; depois clica "Enviar e finalizar"
    # para o documento sair de fato (o convite por e-mail do ZapSign).
    link = _extrair_link(pagina, espera)
    _clicar(
        pagina,
        ("Enviar e finalizar", "Enviar documento", "Enviar para assinatura", "Finalizar", "Enviar"),
        espera,
    )
    pagina.wait_for_timeout(1500)  # deixa o envio registrar, sem travar em networkidle
    return link or _extrair_link(pagina, espera)


def _navegador(sync_playwright: Any):
    ua = _env(
        "ZAPSIGN_USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    )
    p = sync_playwright().start()
    navegador = p.chromium.launch(
        headless=_env("ZAPSIGN_HEADLESS", "1") != "0",
        args=["--disable-blink-features=AutomationControlled"],
    )
    contexto = navegador.new_context(user_agent=ua, viewport={"width": 1400, "height": 950})
    return p, navegador, contexto


def enviar_para_assinatura(
    pdf: bytes,
    nome_arquivo: str,
    cliente_nome: str,
    cliente_email: str,
) -> dict[str, Any]:
    """Sobe UM PDF ao ZapSign pela web e devolve o link de assinatura do cliente.

    `{"ok", "link", "erro", "screenshot", "url_final"}`. Nunca levanta. `ok=False`
    quando não achou um link de assinatura de verdade — nunca devolve link
    genérico. `url_final` é a página onde a automação parou, para calibrar.
    """
    r = enviar_varios_para_assinatura(
        [{"pdf": pdf, "nome": nome_arquivo}], cliente_nome, cliente_email
    )
    doc = (r.get("documentos") or [{}])[0]
    link = doc.get("link", "")
    return {
        "ok": bool(r.get("ok") and link),
        "link": link,
        "erro": r.get("erro") or ("" if link else "O envio subiu, mas não achei o link de assinatura na tela do ZapSign."),
        "screenshot": r.get("screenshot", ""),
        "url_final": r.get("url_final", ""),
    }


def enviar_varios_para_assinatura(
    documentos: list[dict[str, Any]],
    cliente_nome: str,
    cliente_email: str,
) -> dict[str, Any]:
    """Manda VÁRIOS documentos numa sessão só (um login) — um clique para os três.

    `documentos`: lista de `{"pdf": bytes, "nome": str, "rotulo": str}`. Devolve
    `{"ok", "documentos": [{"rotulo","nome","link"}], "erro", "screenshot", "url_final"}`.
    O login é o passo caro; reaproveitá-lo é o que torna "mandar os três" viável.
    """
    if not configurado():
        return {"ok": False, "documentos": [], "erro": "Login do ZapSign não configurado no ambiente.", "screenshot": "", "url_final": ""}
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {
            "ok": False,
            "documentos": [],
            "erro": "Playwright não está instalado no servidor (pip install playwright && playwright install chromium).",
            "screenshot": "",
            "url_final": "",
        }

    url_auth = _env("ZAPSIGN_AUTH_URL", "https://app2.zapsign.com.br")
    url_app = _env("ZAPSIGN_WEB_URL", "https://app.zapsign.com.br")
    espera = int(_env("ZAPSIGN_TIMEOUT_MS", "45000") or "45000")

    caminhos: list[tuple[Path, dict[str, Any]]] = []
    for doc in documentos:
        caminho = Path(tempfile.gettempdir()) / f"zapsign-{int(time.time()*1000)}-{Path(str(doc.get('nome') or 'documento.pdf')).name}"
        caminho.write_bytes(bytes(doc["pdf"]))
        caminhos.append((caminho, doc))

    p = navegador = None
    screenshot = ""
    url_final = ""
    try:
        p, navegador, contexto = _navegador(sync_playwright)
        pagina = contexto.new_page()
        pagina.set_default_timeout(espera)
        _login(pagina, url_auth, espera)

        resultados: list[dict[str, str]] = []
        for caminho, doc in caminhos:
            link = _enviar_um(pagina, caminho, cliente_nome, cliente_email, url_app, espera)
            url_final = pagina.url
            resultados.append(
                {"rotulo": str(doc.get("rotulo") or doc.get("nome") or "documento"), "nome": str(doc.get("nome") or ""), "link": link}
            )

        achou_algum = any(r["link"] for r in resultados)
        diagnostico = ""
        if not achou_algum:
            diagnostico = _diagnostico_pagina(pagina)
            try:
                screenshot = str(_dir_screenshots() / f"sem-link-{int(time.time())}.png")
                pagina.screenshot(path=screenshot, full_page=True)
            except Exception:  # noqa: BLE001
                screenshot = ""
        return {
            "ok": achou_algum,
            "documentos": resultados,
            "erro": "" if achou_algum else (
                "Os documentos subiram, mas a automação não achou o link de assinatura na tela "
                f"(parou em {url_final}). O que a tela oferece agora — {diagnostico} — "
                "diz quais seletores calibrar."
            ),
            "screenshot": screenshot,
            "url_final": url_final,
            "diagnostico": diagnostico,
        }
    except Exception as exc:  # noqa: BLE001 - falha de UI vira mensagem + print
        try:
            if navegador is not None:
                screenshot = str(_dir_screenshots() / f"falha-{int(time.time())}.png")
                contexto.pages[0].screenshot(path=screenshot, full_page=True)
        except Exception:  # noqa: BLE001
            screenshot = ""
        log.warning("ZapSign (navegador) falhou: %s", str(exc)[:200])
        return {
            "ok": False,
            "documentos": [],
            "erro": (
                "Não foi possível concluir o envio pelo site do ZapSign. "
                "Confira o login e os seletores da tela (o screenshot da falha ajuda)."
            ),
            "screenshot": screenshot,
            "url_final": url_final,
        }
    finally:
        try:
            if navegador is not None:
                navegador.close()
            if p is not None:
                p.stop()
        except Exception:  # noqa: BLE001
            pass
        for caminho, _doc in caminhos:
            try:
                caminho.unlink(missing_ok=True)
            except OSError:
                pass
