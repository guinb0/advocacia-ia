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
    if not u.startswith("http") or not any(p in u for p in PADROES_LINK):
        return False
    # O botão "Enviar por WhatsApp" da tela de envio é uma âncora para
    # `api.whatsapp.com/send?text=…%0a<link de assinatura>` — ela CONTÉM
    # "/verificar/", então passava por link de assinatura e ia para o cliente
    # embrulhada. Mandar isso pelo WhatsApp abre a tela de compartilhar, não a
    # de assinar. O link de dentro se aproveita (`_desembrulhar`); a âncora
    # crua, não.
    return "api.whatsapp.com" not in u


def _desembrulhar(url: str) -> str:
    """O link de assinatura de dentro de um `api.whatsapp.com/send?text=…`.

    Devolve a própria URL quando ela já é o link direto. A tela de envio expõe
    as duas formas; só a de dentro serve para mandar ao cliente.
    """
    bruto = (url or "").strip()
    if "api.whatsapp.com" not in bruto.lower():
        return bruto
    from urllib.parse import unquote

    for candidato in _RE_URL.findall(unquote(bruto)):
        if _e_link_de_assinatura(candidato):
            return candidato.rstrip(".,;)")
    return ""


#: URL solta no meio do texto — o link de assinatura do ZapSign aparece como
#: TEXTO na tela (ao lado de "Copiar link"), não como `<a href>`.
_RE_URL = re.compile(r"https?://[^\s\"'<>)]+", re.I)


def _login(pagina: Any, url_auth: str, espera: int) -> None:
    """Login em etapas (e-mail → Entrar → senha → Entrar). Levanta se não entrar.

    Versão que FUNCIONA em produção (o diagnóstico prova que passa daqui e chega
    ao assistente). `networkidle` dá tempo do reCAPTCHA v3 da página de login
    carregar antes do submit; não é o SPA do wizard, então não trava aqui.
    """
    pagina.goto(f"{url_auth}/access/sign-in", wait_until="networkidle")
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
    # 1) O campo que o ZapSign usa para o link do signatário (`input.signer_link`,
    # o que fica ao lado de "Copiar link"). É a fonte mais confiável: já vem como
    # `https://app.zapsign.com.br/verificar/<token>`, limpo. Antes esta varredura
    # começava por `a`, e a primeira âncora com "/verificar/" no href era o botão
    # "Enviar por WhatsApp" — o link saía embrulhado em `api.whatsapp.com/send`.
    for el in pagina.query_selector_all("input.signer_link, input[class*='signer_link']"):
        try:
            # `input_value()` lê a PROPRIEDADE (o que o Angular setou); o atributo
            # `value` do HTML costuma vir vazio nesse campo.
            valor = (el.input_value() or el.get_attribute("value") or "").strip()
        except Exception:  # noqa: BLE001
            continue
        if _e_link_de_assinatura(valor):
            return valor
    # 2) Qualquer âncora ou campo cujo destino seja um link de assinatura —
    # desembrulhando o do WhatsApp, que é embrulho de um link bom.
    for el in pagina.query_selector_all("a, input"):
        try:
            valor = (el.get_attribute("href") or el.get_attribute("value") or "").strip()
        except Exception:  # noqa: BLE001
            continue
        direto = _desembrulhar(valor)
        if _e_link_de_assinatura(direto):
            return direto
    # 3) Último recurso: o link como TEXTO visível na tela de envio.
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
    """Clica o primeiro botão/link VISÍVEL cujo texto casa. Insiste — a etapa
    do assistente leva um instante pra estabilizar depois do clique anterior.

    Duas armadilhas descobertas calibrando contra a conta real (ver
    `docs/DIAGNOSTICO-zapsign-navegador.md`), nenhuma delas visível no HTML
    estático — só rodando de verdade:

    1. **`.first` sozinho não basta.** Depois de avançar de etapa, o ZapSign
       deixa no DOM um botão fantasma da etapa anterior (mesmo texto
       "Continuar", `data-cy="continuarBtn"`, mas invisível/fora da tela).
       `pagina.locator(...).first` obedece ORDEM NO DOM, não posição na tela —
       se o fantasma vem antes do botão de verdade, o clique "funciona" (sem
       erro) e a etapa não avança, porque caiu no elemento errado. Por isso
       aqui a filtragem é por `elemento.is_visible()` de verdade, elemento a
       elemento — não por pseudo-seletor, que teve o mesmo problema.
    2. **Uma tentativa só é insuficiente.** O Angular do assistente troca de
       etapa em mais de um passo (o botão certo pode levar até ~1s pra virar
       clicável depois de renderizar) — sem repetir, a automação clica cedo
       demais e erra por uma corrida, não por seletor errado.

    `.first.click()` com `timeout` grande e um seletor só, como era antes,
    ESCONDIA a corrida: parecia funcionar quando a sorte de timing colaborava,
    e travava direto quando não. Aqui a espera vira tentativas curtas e
    repetidas — mais parecido com como um seletor humano tenta de novo.
    """
    tentativas = max(1, int(espera / 700))
    for _ in range(tentativas):
        for t in textos:
            for el in pagina.query_selector_all("button, a"):
                try:
                    texto_el = (el.inner_text() or "").strip()
                except Exception:  # noqa: BLE001
                    continue
                if t.lower() not in texto_el.lower():
                    continue
                try:
                    if not (el.is_visible() and el.is_enabled()):
                        continue
                    el.click(timeout=5000)
                    return True
                except Exception:  # noqa: BLE001 - este candidato não clicou; tenta o próximo
                    continue
        pagina.wait_for_timeout(700)
    return False


def _shot(pagina: Any, nome: str) -> None:
    """Screenshot de calibração, só quando `ZAPSIGN_DEBUG_DIR` está setado.

    No-op em produção (a env fica vazia). Serve para VER cada etapa do assistente
    ao ajustar seletores em dev — cada passo do SPA vira um PNG numerado.
    """
    destino = _env("ZAPSIGN_DEBUG_DIR", "")
    if not destino:
        return
    try:
        Path(destino).mkdir(parents=True, exist_ok=True)
        pagina.screenshot(path=str(Path(destino) / f"{nome}.png"), full_page=True)
    except Exception:  # noqa: BLE001 - debug nunca atrapalha o envio
        pass


def _preencher_campo(
    pagina: Any, valor: str, seletores: tuple[str, ...], rotulo: str, espera: int
) -> bool:
    """Preenche um campo tentando CSS e, por fim, o RÓTULO (label flutuante).

    Os campos do ZapSign usam Material com rótulo flutuante — não há atributo
    `placeholder`, então casar por placeholder falha (foi o que travou o passo do
    signatário). `get_by_label` acha pelo texto do rótulo, que é o que se enxerga.
    """
    limite = min(int(espera / 3), 8000)
    validos = tuple(s for s in seletores if s)
    # Espera QUALQUER uma das estratégias aparecer (o passo renderiza após o
    # clique anterior); depois o `count()` escolhe a que existe, sem esperar o
    # timeout de cada seletor morto.
    if validos:
        try:
            pagina.wait_for_selector(", ".join(validos), state="visible", timeout=espera)
        except Exception:  # noqa: BLE001 - segue para o rótulo, abaixo
            pass
    for s in validos:
        loc = pagina.locator(s)
        try:
            total = loc.count()
        except Exception:  # noqa: BLE001
            continue
        # O MESMO fantasma que atrapalhava `_clicar` existe nos campos: o passo
        # anterior deixa no DOM o input dele (`#signer-name-field-test-id` fica
        # invisível, `bounding_box` fora da tela) e `.first` obedece ordem de DOM,
        # não o que está na tela. Preencher o fantasma "funciona" sem erro e deixa
        # o campo de verdade vazio — foi assim que o e-mail do signatário ia em
        # branco e o convite nunca saía. Aqui procura-se o primeiro VISÍVEL.
        for i in range(min(total, 10)):
            alvo = loc.nth(i)
            try:
                if not alvo.is_visible():
                    continue
                alvo.fill(valor, timeout=limite)
                # Confirma que o valor entrou: `fill` num campo que o Angular
                # rejeita não levanta, e um "preenchi" falso aqui vale menos que
                # nada — é o que fazia a automação declarar sucesso sem convite.
                if (alvo.input_value() or "").strip() == valor.strip():
                    return True
            except Exception:  # noqa: BLE001 - tenta o próximo candidato
                continue
    try:
        alvo = pagina.get_by_label(re.compile(rotulo, re.I)).first
        alvo.fill(valor, timeout=limite)
        return (alvo.input_value() or "").strip() == valor.strip()
    except Exception:  # noqa: BLE001
        return False


#: Input de texto visível que NÃO é arquivo/checkbox/oculto/busca/recaptcha — o
#: campo do signatário quando nada mais o identifica (sem placeholder nem name).
_INPUT_TEXTO_VISIVEL = (
    "input:visible:not([type='file']):not([type='checkbox']):not([type='hidden'])"
    ":not([type='search']):not([name='g-recaptcha-response'])"
)


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
    pagina.wait_for_timeout(600)
    _shot(pagina, "01-apos-upload")
    _clicar(pagina, ("Continuar",), espera)

    # 2) Signatário: SÓ O NOME nesta etapa (o e-mail é pedido na tela de envio).
    # O campo tem rótulo flutuante (sem placeholder) — daí as várias estratégias.
    pagina.wait_for_timeout(600)  # o passo 2 renderiza após o clique anterior
    if not _preencher_campo(
        pagina,
        cliente_nome,
        (
            _sel("SIGNATARIO_NOME", ""),
            # O ZapSign dá um `id` de teste estável a este campo — mais confiável
            # que placeholder (não tem) ou rótulo flutuante (Material).
            "input#signer-name-field-test-id",
            "input[id*='signer-name' i]",
            "input[placeholder*='signat' i]",
            "input[aria-label*='signat' i]",
            _INPUT_TEXTO_VISIVEL,
        ),
        "signat",
        espera,
    ):
        raise ErroNavegador(
            "Não consegui preencher o nome do signatário na etapa 2 do ZapSign."
        )
    _shot(pagina, "02-signatario-nome")
    _clicar(pagina, ("Continuar",), espera)

    # 3) Posicionar assinaturas é OPCIONAL — seguir sem posicionar.
    pagina.wait_for_timeout(600)
    _shot(pagina, "03-posicionar")
    _clicar(pagina, ("Continuar sem posicionar", "Salvar e continuar", "Continuar"), espera)

    # 4) Tela de envio: informa o E-MAIL do signatário; o link `/verificar/` já
    # aparece (o token é permanente). Captura o link ANTES de finalizar.
    pagina.wait_for_timeout(600)
    # O campo do e-mail é `input[type=text][name=email]` com `id` de sufixo
    # aleatório (`signer-email-158792783`) e SEM placeholder nem aria-label —
    # `input[type='email']` e as buscas por placeholder/rótulo casavam com ZERO
    # elementos. O e-mail ia em branco, o convite nunca saía, e a automação
    # ainda assim devolvia `ok` porque ninguém olhava o resultado deste
    # preenchimento. Agora casa por `name=email` e a falha interrompe o envio.
    if not _preencher_campo(
        pagina,
        cliente_email,
        (
            _sel("SIGNATARIO_EMAIL", ""),
            "input[name='email']",
            "input[id*='signer-email' i]",
            "input[type='email']",
            "input[placeholder*='mail' i]",
            "input[aria-label*='mail' i]",
        ),
        "mail",
        espera,
    ):
        raise ErroNavegador(
            "Não consegui preencher o e-mail do signatário na tela de envio do "
            "ZapSign — sem ele o convite não sai. Confira o seletor "
            "ZAPSIGN_SEL_SIGNATARIO_EMAIL."
        )
    _shot(pagina, "04-envio")
    link = _extrair_link(pagina, espera)
    if not _clicar(
        pagina,
        ("Enviar e finalizar", "Enviar documento", "Enviar para assinatura", "Finalizar", "Enviar"),
        espera,
    ):
        raise ErroNavegador(
            "O documento subiu e o link saiu, mas não achei o botão de enviar na "
            "última etapa do ZapSign — o convite não foi disparado."
        )
    _shot(pagina, "05-apos-enviar")
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
