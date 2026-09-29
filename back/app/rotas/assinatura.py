"""Assinatura eletrônica: provedores, envio pelo site e acompanhamento."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .. import (
    armazenamento,
    assinatura,
    assinatura_autentique,
    assinatura_clicksign,
    assinatura_config,
    assinatura_provedores,
    auth,
    contrato,
    docx_pdf,
    whatsapp,
)
from ..agente import dossie as dossie_agente
from .comum import _ler_upload, log
from .contratos import PedidoContrato

roteador = APIRouter()


# ------------------------------------------- contrato → assinatura eletrônica
#
# O contrato é gerado, conferido pelo advogado e só então mandado assinar. O
# fluxo é o mesmo de sempre, com um passo a menos de trabalho manual: em vez de
# baixar o .docx, subir no painel da ZapSign e digitar os contatos, o servidor
# faz o upload e dispara os convites com o que a entrevista já respondeu.
#
# O que NÃO muda: o documento continua sendo o modelo do escritório palavra por
# palavra (`app/contrato.py`), e quem escolhe mandar assinar é o advogado.


class Signatario(BaseModel):
    """Alguém a mais na assinatura — testemunha, segundo contratante, sócio."""

    nome: str
    email: str = ""
    telefone: str = ""
    papel: str = ""


class PedidoAssinatura(PedidoContrato):
    """As respostas do roteiro, mais quem assina além do cliente."""

    #: Somados ao cliente (da entrevista) e ao escritório (do `.env`).
    signatarios: list[Signatario] = Field(default_factory=list)
    #: Vincula o contrato a um caso já aberto. Em geral vem vazio: na ordem do
    #: escritório o contrato é assinado antes de o caso existir.
    caso_id: str | None = None


def _chave_nome_identidade(nome: object) -> str:
    """Forma estável do nome usada somente para correlacionar contrato e caso."""
    return " ".join(str(nome or "").split()).casefold()


def _cpf_identidade(cpf: object) -> str:
    """CPF canônico; as duas origens já passaram pela validação do contrato."""
    return "".join(c for c in str(cpf or "") if "0" <= c <= "9")


def _identidade_atual_do_caso(caso_id: str) -> tuple[str, str]:
    """Relê a identidade inequívoca do Case State, sem confiar no navegador."""
    montado = dossie_agente.montar(caso_id)
    if montado is None:
        raise HTTPException(404, "Caso não encontrado.")

    respostas, motivos = dossie_agente.dados_do_contrato(montado)
    if motivos:
        # Os motivos podem conter contexto útil na tela do dossiê, mas esta rota
        # só precisa declarar o conflito sem devolver nenhum dado de identificação.
        raise HTTPException(
            409,
            "A identidade atual do caso não está válida e inequívoca para vincular o contrato.",
        )
    return str(respostas["nome"]), str(respostas["cpf"])


def _exigir_identidade_do_caso(caso_id: str, nome: object, cpf: object) -> None:
    nome_caso, cpf_caso = _identidade_atual_do_caso(caso_id)
    if _chave_nome_identidade(nome) != _chave_nome_identidade(
        nome_caso
    ) or _cpf_identidade(cpf) != _cpf_identidade(cpf_caso):
        raise HTTPException(
            409,
            "A identificação do contrato não corresponde à identidade atual do caso.",
        )


def _resposta_assinatura(registro: dict[str, Any]) -> dict[str, Any]:
    """O registro local sem o token da ZapSign.

    O token identifica o documento na conta do escritório e serve para consultar
    e excluir pela API deles. Quem precisa dele é o servidor; a tela trabalha
    com o `id` local, que não vale nada fora daqui.
    """
    limpo = dict(registro)
    limpo.pop("doc_token", None)
    limpo.pop("cpf", None)
    return limpo


@roteador.get("/api/assinatura/config")
def config_assinatura():
    """Se dá para mandar assinar, e com que modo de autenticação.

    A tela pergunta antes de oferecer o botão: sem a chave no `.env` o envio não
    existe, e é melhor dizer isso do que deixar o advogado clicar e tomar erro.

    `whatsapp_proprio` é o nosso canal (Evolution), e não o da ZapSign. Os dois
    convivem: o e-mail da ZapSign sai sempre, e o WhatsApp entra por cima quando
    a instância do escritório está pareada. Enquanto não estiver, a tela não
    oferece o botão — mas o cliente continua recebendo o convite por e-mail.
    """
    return {
        **assinatura.configuracao(),
        "whatsapp_proprio": whatsapp.configurado(),
        # Envio pelo SITE do ZapSign (Playwright) OU pela API do provedor que o
        # escritório tiver ativado (Clicksign/Autentique) — ver `assinatura_provedores`.
        # A tela só oferece o botão quando há um caminho de envio pronto.
        "navegador": assinatura_provedores.configurado(),
        "provedor_ativo": assinatura_config.provedor_ativo(),
    }


@roteador.get("/api/assinatura/provedores", dependencies=[Depends(auth.exigir_modulo("contratos"))])
def listar_provedores_assinatura():
    """Status de cada provedor para a tela de configuração — nunca o token."""
    return {"provedores": assinatura_config.status()}


class PedidoTokenProvedor(BaseModel):
    token: str = Field(..., min_length=4, max_length=4000)


@roteador.post(
    "/api/assinatura/provedores/{provedor}/token",
    dependencies=[Depends(auth.exigir_modulo("contratos"))],
)
def salvar_token_provedor_assinatura(provedor: str, pedido: PedidoTokenProvedor):
    """Cifra e salva o token do escritório. Não testa sozinho — use o botão de teste."""
    try:
        assinatura_config.salvar_token(provedor, pedido.token)
    except assinatura_config.ErroConfigAssinatura as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"ok": True, "provedor": provedor, "configurado": True, "testado_ok": False}


@roteador.post(
    "/api/assinatura/provedores/{provedor}/testar",
    dependencies=[Depends(auth.exigir_modulo("contratos"))],
)
async def testar_provedor_assinatura(provedor: str):
    """Bate na API do provedor com o token salvo e registra o resultado."""
    adaptador = {
        "clicksign": assinatura_clicksign,
        "autentique": assinatura_autentique,
    }.get(provedor)
    if adaptador is None:
        raise HTTPException(
            422, f"Provedor {provedor!r} desconhecido. Use clicksign ou autentique."
        )
    try:
        token = assinatura_config.token_de(provedor)
    except assinatura_config.ErroConfigAssinatura as exc:
        raise HTTPException(422, str(exc)) from exc

    ok, mensagem = await adaptador.testar(token)
    assinatura_config.marcar_teste(provedor, ok, mensagem)
    if not ok:
        raise HTTPException(502, mensagem)
    return {"ok": True, "mensagem": mensagem}


class PedidoAtivarProvedor(BaseModel):
    provedor: str = Field(..., min_length=3, max_length=20)


@roteador.post(
    "/api/assinatura/provedores/ativar",
    dependencies=[Depends(auth.exigir_modulo("contratos"))],
)
def ativar_provedor_assinatura(pedido: PedidoAtivarProvedor):
    """Torna o provedor escolhido o caminho de envio — exige teste aprovado."""
    try:
        assinatura_config.ativar(pedido.provedor)
    except assinatura_config.ErroConfigAssinatura as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"ok": True, "provedor_ativo": assinatura_config.provedor_ativo()}


@roteador.post("/api/assinatura/navegador", status_code=201)
async def enviar_assinatura_pelo_site(
    arquivo: UploadFile = File(...),
    cliente_nome: str = Form(...),
    cliente_email: str = Form(...),
    cliente_whatsapp: str = Form(""),
):
    """Manda o documento à assinatura pelo SITE do ZapSign, e o link pelo WhatsApp.

    Existe para o plano do escritório, que não tem API do ZapSign: a automação
    entra na conta (Playwright), sobe o PDF e dispara o convite por e-mail. Se o
    site devolver o link e houver telefone, ele também vai ao cliente pela nossa
    Evolution. Ver `app/assinatura_navegador.py`.

    Quando o escritório tiver Clicksign ou Autentique ativada em Configurações, o
    envio sai por lá em vez do site do ZapSign — ver `app/assinatura_provedores.py`.
    """
    if not assinatura_provedores.configurado():
        raise HTTPException(503, assinatura_provedores.mensagem_nao_configurado())
    pdf = await _ler_upload(arquivo)
    resultado = await assinatura_provedores.enviar_um(
        pdf,
        arquivo.filename or "documento.pdf",
        cliente_nome.strip(),
        cliente_email.strip(),
    )
    if not resultado["ok"]:
        raise HTTPException(502, resultado["erro"])

    whatsapp_enviado = False
    if resultado["link"] and cliente_whatsapp.strip() and whatsapp.configurado():
        try:
            numero = whatsapp._numero_brasileiro(cliente_whatsapp)
            texto = (
                f"Olá! Segue o documento para assinatura digital: {resultado['link']}\n"
                "Qualquer dúvida, estamos à disposição."
            )
            await run_in_threadpool(whatsapp._enviar_texto_sync, numero, texto)
            whatsapp_enviado = True
        except Exception:  # noqa: BLE001 - o e-mail do ZapSign já saiu; WhatsApp é reforço
            log.warning("Falha ao enviar link de assinatura pelo WhatsApp", exc_info=True)

    return {"ok": True, "link": resultado["link"], "whatsapp_enviado": whatsapp_enviado}


class PedidoLinkAssinaturaSite(BaseModel):
    telefone: str = Field(..., min_length=8, max_length=20)
    link: str = Field(..., min_length=8, max_length=500)


@roteador.post("/api/assinatura/navegador/whatsapp", status_code=201)
async def reenviar_link_assinatura_site(pedido: PedidoLinkAssinaturaSite) -> dict[str, bool]:
    """(Re)envia ao cliente, pelo WhatsApp, o link de assinatura já criado no ZapSign.

    O envio pelo site já dispara o link uma vez, mas o convite cai no spam e o
    cliente jura que não recebeu — ou o telefone não estava à mão na criação.
    Este botão manda o MESMO link, sem recriar o documento na ZapSign. Aceita só
    um link http(s), não texto livre: não é um canal para mandar qualquer coisa a
    qualquer número (ver o cabeçalho de `app/whatsapp.py`).
    """
    if not whatsapp.configurado():
        raise HTTPException(
            503,
            "O WhatsApp do escritório não está conectado. Conecte a Evolution para enviar o link.",
        )
    link = pedido.link.strip()
    if not (link.startswith("http://") or link.startswith("https://")):
        raise HTTPException(422, "Link de assinatura inválido.")
    numero = whatsapp._numero_brasileiro(pedido.telefone)
    texto = (
        f"Olá! Segue o documento para assinatura digital: {link}\n"
        "Qualquer dúvida, estamos à disposição."
    )
    try:
        await run_in_threadpool(whatsapp._enviar_texto_sync, numero, texto)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - a Evolution pode oscilar; a tela reoferece o botão
        log.warning("Falha ao reenviar link de assinatura pelo WhatsApp", exc_info=True)
        raise HTTPException(
            502, "A Evolution não enviou a mensagem agora. Tente novamente."
        ) from exc
    return {"enviado": True}


class PedidoAssinaturaDireta(BaseModel):
    """Manda UM documento do escritório à assinatura sem baixar/reanexar o PDF."""

    respostas: dict[str, Any]
    municipio: str = ""
    documento: str = "contrato"
    cliente_whatsapp: str = ""


@roteador.post("/api/assinatura/navegador/documento", status_code=201)
async def enviar_documento_para_assinatura_site(pedido: PedidoAssinaturaDireta):
    """Gera o documento no servidor e o manda assinar pela conta ZapSign (site).

    Tira o vai-e-volta de baixar o PDF e reanexar: preenche o modelo com a
    qualificação da entrevista, converte para PDF e sobe pela automação, num
    clique. O convite sai por e-mail e, havendo telefone, o link também vai pelo
    WhatsApp do cliente.
    """
    if not assinatura_provedores.configurado():
        raise HTTPException(503, assinatura_provedores.mensagem_nao_configurado())
    if pedido.documento not in contrato.CODIGOS:
        raise HTTPException(
            422,
            f"Documento {pedido.documento!r} não existe. Conhecidos: {', '.join(contrato.CODIGOS)}.",
        )
    nome = str(pedido.respostas.get("nome") or "").strip()
    email = str(pedido.respostas.get("email") or "").strip()
    if not email:
        raise HTTPException(
            422,
            "O envio para assinatura exige um e-mail para mandar o convite. Preencha "
            "o e-mail do cliente na entrevista e tente de novo.",
        )
    try:
        docx, _faltando = await run_in_threadpool(
            contrato.gerar, pedido.respostas, pedido.municipio, None, pedido.documento
        )
        pdf = await run_in_threadpool(docx_pdf.converter, docx)
    except docx_pdf.ErroConversaoDocx as exc:
        raise HTTPException(502, str(exc)) from exc
    except contrato.ErroContrato as exc:
        raise HTTPException(422, str(exc)) from exc

    rotulo = next(
        (m["rotulo"] for m in contrato.MODELOS if m["codigo"] == pedido.documento),
        pedido.documento,
    )
    resultado = await assinatura_provedores.enviar_um(
        pdf,
        f"{rotulo} - {nome or 'cliente'}.pdf".replace("/", "-"),
        nome,
        email,
    )
    if not resultado["ok"]:
        raise HTTPException(502, resultado["erro"])

    whatsapp_enviado = False
    if resultado["link"] and pedido.cliente_whatsapp.strip() and whatsapp.configurado():
        try:
            numero = whatsapp._numero_brasileiro(pedido.cliente_whatsapp)
            texto = (
                f"Olá! Segue o documento para assinatura digital: {resultado['link']}\n"
                "Qualquer dúvida, estamos à disposição."
            )
            await run_in_threadpool(whatsapp._enviar_texto_sync, numero, texto)
            whatsapp_enviado = True
        except Exception:  # noqa: BLE001 - o e-mail já saiu; WhatsApp é reforço
            log.warning("Falha ao enviar link de assinatura pelo WhatsApp", exc_info=True)

    return {"ok": True, "link": resultado["link"], "whatsapp_enviado": whatsapp_enviado}


class PedidoAssinaturaTodos(BaseModel):
    """Manda os TRÊS documentos à assinatura de uma vez, num login só."""

    respostas: dict[str, Any]
    municipio: str = ""
    cliente_whatsapp: str = ""


def _juntar_pdfs(pdfs: list[bytes]) -> bytes:
    import io

    import pypdfium2 as pdfium

    destino = pdfium.PdfDocument.new()
    for conteudo in pdfs:
        destino.import_pages(pdfium.PdfDocument(conteudo))
    saida = io.BytesIO()
    destino.save(saida)
    return saida.getvalue()


@roteador.post("/api/assinatura/navegador/todos", status_code=201)
async def enviar_todos_para_assinatura_site(pedido: PedidoAssinaturaTodos):
    """Gera contrato + procuração + declaração e os manda assinar num clique.

    Os três sobem na MESMA sessão do navegador (um login só) quando o provedor
    ativo é a ZapSign; cada um volta com o seu link de assinatura e, havendo
    telefone, cada link vai ao cliente pelo WhatsApp — um por documento, para
    ele não achar que acabou no primeiro.
    """
    if not assinatura_provedores.configurado():
        raise HTTPException(503, assinatura_provedores.mensagem_nao_configurado())
    nome = str(pedido.respostas.get("nome") or "").strip()
    email = str(pedido.respostas.get("email") or "").strip()
    if not email:
        raise HTTPException(
            422,
            "O envio para assinatura exige um e-mail para mandar o convite. Preencha "
            "o e-mail do cliente na entrevista e tente de novo.",
        )
    try:
        gerados = await run_in_threadpool(
            contrato.gerar_todos, pedido.respostas, pedido.municipio
        )
        pdfs: list[bytes] = []
        rotulos: list[str] = []
        for item in gerados:
            pdfs.append(await run_in_threadpool(docx_pdf.converter, item["docx"]))
            rotulos.append(str(item["rotulo"]))
        rotulo = f"{', '.join(rotulos[:-1])} e {rotulos[-1]}" if len(rotulos) > 1 else rotulos[0]
        documentos = [
            {
                "pdf": await run_in_threadpool(_juntar_pdfs, pdfs),
                "nome": f"Documentos para assinatura - {nome or 'cliente'}.pdf".replace("/", "-"),
                "rotulo": rotulo,
            }
        ]
    except docx_pdf.ErroConversaoDocx as exc:
        raise HTTPException(502, str(exc)) from exc
    except contrato.ErroContrato as exc:
        raise HTTPException(422, str(exc)) from exc

    resultado = await assinatura_provedores.enviar_varios(documentos, nome, email)
    if not resultado["ok"]:
        raise HTTPException(502, resultado["erro"])

    docs_saida = resultado.get("documentos") or []
    whatsapp_enviado = False
    if pedido.cliente_whatsapp.strip() and whatsapp.configurado():
        try:
            numero = whatsapp._numero_brasileiro(pedido.cliente_whatsapp)
            for doc in docs_saida:
                if not doc.get("link"):
                    continue
                texto = (
                    f"Olá! Seguem os seus documentos ({doc.get('rotulo', 'contrato')}) para "
                    f"assinatura digital, todos em um só link — basta assinar uma vez: "
                    f"{doc['link']}\nQualquer dúvida, estamos à disposição."
                )
                await run_in_threadpool(whatsapp._enviar_texto_sync, numero, texto)
                whatsapp_enviado = True
        except Exception:  # noqa: BLE001 - o e-mail já saiu; WhatsApp é reforço
            log.warning("Falha ao enviar links de assinatura pelo WhatsApp", exc_info=True)

    return {
        "ok": True,
        "documentos": [{"rotulo": d.get("rotulo", ""), "link": d.get("link", "")} for d in docs_saida],
        "whatsapp_enviado": whatsapp_enviado,
    }


@roteador.post("/api/contrato/assinatura", status_code=201)
async def enviar_contrato_para_assinatura(pedido: PedidoAssinatura):
    """Gera a papelada INTEIRA e a manda para assinatura eletrônica.

    São três documentos e não um: contrato de honorários, procuração e
    declaração de hipossuficiência. Sem procuração o advogado não peticiona, e
    sem declaração não há gratuidade — mandar só o contrato deixava o cliente
    assinando uma vez e o escritório correndo atrás das outras duas assinaturas
    depois, fora do sistema.

    Cada documento vira um processo de assinatura próprio na ZapSign, porque é
    assim que ela funciona: um envelope por documento, com o seu próprio link e
    a sua própria trilha de auditoria. O cliente recebe três convites.

    O .docx sobe como está — a ZapSign converte para PDF e é esse PDF que o
    cliente assina. Nome completo e CPF válido são obrigatórios. Outro campo que
    a entrevista não respondeu continua entre colchetes e volta em `faltando`.
    """
    if not assinatura.ativa():
        raise HTTPException(
            503,
            "Assinatura eletrônica desligada: falta ZAPSIGN_API_TOKEN no .env. "
            "O contrato continua podendo ser gerado e assinado à mão.",
        )

    try:
        respostas = contrato.normalizar_respostas(pedido.respostas)
        cliente = str(respostas["nome"])
        if pedido.caso_id:
            await run_in_threadpool(
                _exigir_identidade_do_caso,
                pedido.caso_id,
                cliente,
                respostas["cpf"],
            )
        documentos = await run_in_threadpool(
            contrato.gerar_todos, respostas, pedido.municipio
        )
    except contrato.DadosObrigatoriosContrato as exc:
        raise HTTPException(422, str(exc)) from exc
    except contrato.ErroContrato as exc:
        raise HTTPException(503, str(exc)) from exc

    extras = [s.model_dump() for s in pedido.signatarios]

    # Montar a lista falha por dado que o usuário pode consertar — cliente sem
    # e-mail e sem telefone. É 400, e não 502: culpar a ZapSign por uma entrevista
    # incompleta manda o advogado procurar o problema no lugar errado.
    try:
        signatarios = assinatura.signatarios_do_contrato(respostas, extras)
    except assinatura.ErroAssinatura as exc:
        raise HTTPException(400, str(exc)) from exc

    enviados: list[dict[str, Any]] = []
    faltando: list[str] = []
    for doc in documentos:
        nome_documento = f"{doc['rotulo']} — {cliente}"
        try:
            resposta = await assinatura.enviar(nome_documento, doc["docx"], signatarios)
        except assinatura.ErroAssinatura as exc:
            # Um documento recusado no meio da fila deixa os anteriores JÁ
            # enviados — e eles são válidos, o cliente vai recebê-los. Devolver
            # 502 e calar sobre isso faria o escritório mandar tudo de novo,
            # duplicando convites. Por isso o que já subiu vai na resposta.
            if enviados:
                log.warning(
                    "%s falhou depois de %d documento(s) já enviado(s): %s",
                    doc["rotulo"],
                    len(enviados),
                    exc,
                )
                return {
                    "assinaturas": enviados,
                    "faltando": sorted(set(faltando)),
                    "parcial": (
                        f"{doc['rotulo']} não foi aceita pela ZapSign ({exc}). "
                        f"Os {len(enviados)} documento(s) anteriores já foram enviados — "
                        "mande apenas o que faltou, para não duplicar convites."
                    ),
                }
            raise HTTPException(502, str(exc)) from exc

        resumo = assinatura.resumir(
            resposta, assinatura.casar_com_enviados(signatarios, resposta)
        )
        if not resumo["doc_token"]:
            raise HTTPException(
                502,
                f"A ZapSign aceitou {doc['rotulo'].lower()} mas não devolveu o token.",
            )

        registro = armazenamento.registrar_assinatura(
            doc_token=resumo["doc_token"],
            nome=nome_documento,
            cliente=cliente,
            cpf=str(respostas["cpf"]),
            signatarios=resumo["signatarios"],
            estado=resumo["estado"],
            caso_id=pedido.caso_id,
        )
        enviados_whatsapp = await whatsapp.enviar_links_assinatura_automaticos(registro)
        if enviados_whatsapp:
            log.info(
                "%d link(s) de assinatura enviados automaticamente pelo WhatsApp.",
                enviados_whatsapp,
            )
        enviados.append(_resposta_assinatura(registro))
        faltando += doc["faltando"]

        log.info(
            "%s de %s enviada para assinatura (%d signatário(s)).",
            doc["rotulo"],
            cliente,
            resumo["total"],
        )

    return {"assinaturas": enviados, "faltando": sorted(set(faltando))}


@roteador.get("/api/assinaturas")
def listar_assinaturas(
    caso_id: str | None = None,
    cliente: str | None = None,
    cpf: str | None = None,
):
    """Os contratos já mandados assinar, do mais novo para o mais antigo.

    Devolve o último estado conhecido, sem consultar a ZapSign: a lista abre
    instantânea e uma consulta por contrato estouraria o limite de requisições
    deles numa carteira grande. Quem atualiza é o `GET` de um contrato só.
    """
    if cliente and not cpf:
        raise HTTPException(
            422, "Informe o CPF junto com o nome para evitar homônimos."
        )
    return {
        "assinaturas": [
            _resposta_assinatura(a)
            for a in armazenamento.listar_assinaturas(
                caso_id=caso_id, cliente=cliente, cpf=cpf
            )
        ]
    }


@roteador.get("/api/assinaturas/{assinatura_id}")
async def obter_assinatura(assinatura_id: str):
    """Quem já assinou e quem falta — consultado na ZapSign agora.

    Se a consulta falhar, devolve o último estado conhecido com `atualizado:
    false`. Some da tela é pior que estar desatualizado: o advogado precisa ver
    que o contrato existe mesmo quando a ZapSign está fora do ar.
    """
    registro = armazenamento.obter_assinatura(assinatura_id)
    if registro is None:
        raise HTTPException(404, "Contrato não encontrado.")

    try:
        documento = await assinatura.consultar(registro["doc_token"])
    except assinatura.ErroAssinatura as exc:
        return {
            "assinatura": _resposta_assinatura(registro),
            "atualizado": False,
            "aviso": str(exc),
        }

    # O que já se sabia de cada signatário: o papel e o link de assinatura, que a
    # consulta de detalhe não repete (ver `assinatura.resumir`).
    anteriores = {s.get("token", ""): s for s in registro["signatarios"]}
    resumo = assinatura.resumir(documento, anteriores)
    atualizado = armazenamento.atualizar_assinatura(
        assinatura_id, resumo["estado"], resumo["signatarios"]
    )
    registro_atual = atualizado or registro
    if (
        resumo["estado"] == "assinado"
        and armazenamento.caminho_do_assinado(assinatura_id) is None
    ):
        try:
            url = await assinatura.url_do_assinado(registro["doc_token"])
            pdf = await assinatura.baixar(url)
            destino = armazenamento.DIR_CONTRATOS / f"{assinatura_id}.pdf"
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(pdf)
            armazenamento.definir_arquivo_assinatura(assinatura_id, destino)
            registro_atual = (
                armazenamento.obter_assinatura(assinatura_id) or registro_atual
            )
            _anexar_documento_assinado_ao_caso(registro_atual, destino)
        except assinatura.ErroAssinatura as exc:
            log.warning(
                "Assinado %s ainda não pôde ser anexado ao caso: %s", assinatura_id, exc
            )
    return {
        "assinatura": _resposta_assinatura(registro_atual),
        "atualizado": True,
        "tem_assinado": resumo["tem_assinado"],
    }


@roteador.get("/api/assinaturas/{assinatura_id}/arquivo")
async def baixar_contrato_assinado(assinatura_id: str):
    """O PDF assinado, com a página de trilha de auditoria da ZapSign.

    Na primeira vez o arquivo é puxado de lá e guardado em `dados/contratos/`;
    depois sai do disco. Não é cache por velocidade: os links da ZapSign expiram
    em 60 minutos, e o escritório precisa da via assinada mesmo anos depois, com
    ou sem a conta ativa.
    """
    registro = armazenamento.obter_assinatura(assinatura_id)
    if registro is None:
        raise HTTPException(404, "Contrato não encontrado.")

    nome_arquivo = f"{registro['nome']}.pdf".replace("/", "-").replace("\\", "-")

    guardado = armazenamento.caminho_do_assinado(assinatura_id)
    if guardado is not None:
        _anexar_documento_assinado_ao_caso(registro, guardado)
        return FileResponse(
            guardado, media_type="application/pdf", filename=nome_arquivo
        )

    try:
        url = await assinatura.url_do_assinado(registro["doc_token"])
        pdf = await assinatura.baixar(url)
    except assinatura.ErroAssinatura as exc:
        # 409: o pedido está correto, o documento é que ainda não foi assinado
        # por todos. 502 faria a tela culpar a rede por uma assinatura pendente.
        raise HTTPException(409, str(exc)) from exc

    destino = armazenamento.DIR_CONTRATOS / f"{assinatura_id}.pdf"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(pdf)
    armazenamento.definir_arquivo_assinatura(assinatura_id, destino)
    _anexar_documento_assinado_ao_caso(registro, destino)

    return FileResponse(destino, media_type="application/pdf", filename=nome_arquivo)


def _codigo_documento_assinado(nome: str) -> str:
    normalizado = contrato._sem_acento(nome)
    if normalizado.startswith("procuracao"):
        return "DOC.01"
    if normalizado.startswith("contrato"):
        return "ASS.CONTRATO"
    if normalizado.startswith("declaracao"):
        return "ASS.HIPOSSUFICIENCIA"
    return "ASS.DOCUMENTO"


def _anexar_documento_assinado_ao_caso(registro: dict[str, Any], caminho: Path) -> None:
    """Transforma a via assinada em anexo do caso, uma única vez.

    A procuração atende diretamente o DOC.01 do checklist. Os demais papéis
    também ficam presos ao dossiê, embora não substituam documentos probatórios
    específicos da ação.
    """
    caso_id = str(registro.get("caso_id") or "")
    if not caso_id or not caminho.is_file():
        return
    nome = f"{registro['nome']}.pdf".replace("/", "-").replace("\\", "-")
    # Uma consulta para saber se este documento assinado já está no checklist.
    #
    # Era `listar_entregas` + um `obter_entrega` por anexo — e `obter_entrega` abre
    # conexão própria e consulta o agente jurídico. Num caso de 46 anexos, anexar UM
    # contrato assinado custava 92 idas ao banco só para descobrir que ele ainda não
    # estava lá. A origem da entrega vive dentro da extração, que é justamente o que
    # a lista em lote já traz.
    for entrega in armazenamento.listar_extracoes_do_caso(caso_id):
        origem = (entrega.get("extracao") or {}).get("origem") or {}
        if origem.get("assinatura_id") == registro.get("id"):
            return
    codigo = _codigo_documento_assinado(str(registro.get("nome") or ""))
    entrega = armazenamento.registrar_entrega_pendente(caso_id, codigo, nome, caminho)
    armazenamento.concluir_entrega(
        entrega["id"],
        {
            "tipo": {"codigo": "documento_assinado", "detectado": "documento_assinado"},
            "validacao": {
                "veredito": "valido",
                "dados_utilizaveis": True,
                "score_legibilidade": 100,
            },
            "origem": {"assinatura_id": registro["id"], "assinatura_eletronica": True},
        },
        True,
        [codigo],
    )


@roteador.post("/api/assinaturas/{assinatura_id}/caso")
def vincular_assinatura(assinatura_id: str, caso_id: str = Form(...)):
    """Liga o contrato ao caso aberto depois dele — a ordem do escritório."""
    registro = armazenamento.obter_assinatura(assinatura_id)
    if registro is None:
        raise HTTPException(404, "Contrato não encontrado.")
    _exigir_identidade_do_caso(caso_id, registro.get("cliente"), registro.get("cpf"))
    if not armazenamento.vincular_assinatura_ao_caso(assinatura_id, caso_id):
        raise HTTPException(404, "Contrato não encontrado.")
    atualizado = armazenamento.obter_assinatura(assinatura_id)
    guardado = armazenamento.caminho_do_assinado(assinatura_id)
    if atualizado and guardado:
        _anexar_documento_assinado_ao_caso(atualizado, guardado)
    return {"vinculado": True}


@roteador.delete("/api/assinaturas/{assinatura_id}")
def excluir_assinatura(assinatura_id: str):
    """Tira o contrato da lista local. Na ZapSign ele continua, com a auditoria."""
    if not armazenamento.excluir_assinatura(assinatura_id):
        raise HTTPException(404, "Contrato não encontrado.")
    return {"removido": True}
