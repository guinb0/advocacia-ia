"""Geração de contrato e manutenção dos modelos `.docx`."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    UploadFile,
)
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from .. import (
    armazenamento,
    auth,
    contrato,
    docx_pdf,
)
from .comum import MAX_BYTES

roteador = APIRouter()


class PedidoContrato(BaseModel):
    """As respostas do roteiro, como a tela as tem em mãos."""

    respostas: dict[str, Any]
    #: Onde o contrato é assinado. Vazio: tenta deduzir do endereço.
    municipio: str = ""
    #: Qual dos documentos da papelada. Ver `contrato.MODELOS`.
    documento: str = "contrato"
    formato: str = "docx"


@roteador.post("/api/contrato")
def gerar_contrato(pedido: PedidoContrato):
    """Preenche o modelo oficial do escritório com os dados da entrevista.

    Devolve o .docx para conferência e assinatura — nada é gerado por modelo de
    linguagem aqui: as cláusulas, os percentuais e as inscrições na OAB saem do
    arquivo em `docs/`, palavra por palavra (ver `app/contrato.py`).

    Nome completo e CPF válido são obrigatórios. Os demais campos que a
    entrevista não respondeu voltam no cabeçalho `X-Campos-Faltando`, e
    continuam visíveis entre colchetes no documento.
    """
    # Documento desconhecido é erro de quem chamou, não do serviço: sem esta
    # barreira ele cairia no 503 lá embaixo, mandando procurar o problema no
    # servidor em vez de na requisição.
    if pedido.documento not in contrato.CODIGOS:
        raise HTTPException(
            422,
            f"Documento {pedido.documento!r} não existe. Conhecidos: {', '.join(contrato.CODIGOS)}.",
        )
    if pedido.formato not in {"docx", "pdf"}:
        raise HTTPException(422, "Formato inválido: escolha docx ou pdf.")

    try:
        alvo = contrato.modelo(pedido.documento)
        respostas = contrato.normalizar_respostas(pedido.respostas)
        docx, faltando = contrato.gerar(
            respostas, pedido.municipio, codigo=pedido.documento
        )
    except contrato.DadosObrigatoriosContrato as exc:
        raise HTTPException(422, str(exc)) from exc
    except contrato.ErroContrato as exc:
        raise HTTPException(503, str(exc)) from exc

    nome_cliente = str(respostas["nome"])
    extensao = pedido.formato
    arquivo = f"{alvo['arquivo']} - {nome_cliente}.{extensao}".replace(
        "/", "-"
    ).replace("\\", "-")

    if pedido.formato == "pdf":
        try:
            conteudo = docx_pdf.converter(docx)
        except docx_pdf.ErroConversaoDocx as exc:
            raise HTTPException(503, str(exc)) from exc
        media_type = "application/pdf"
    else:
        conteudo = docx
        media_type = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )

    return Response(
        content=conteudo,
        media_type=media_type,
        headers={
            # `filename*` em UTF-8 porque nome de cliente tem acento, e o
            # `filename` sem aspas quebraria no primeiro espaço.
            "Content-Disposition": (
                f'attachment; filename="{pedido.documento}.{extensao}"; '
                f"filename*=UTF-8''{quote(arquivo)}"
            ),
            "X-Campos-Faltando": ", ".join(faltando),
        },
    )


# ------------------------------------------- modelos .docx do escritorio
#
# O contrato de honorarios nao e versionado (traz honorarios, CNPJ e as OAB), e
# por isso nao existe em `docs/` dentro do conteiner. Estas rotas sao como ele
# chega la: sobe uma vez, fica no banco, vale para todos os conteineres. Ver
# `contrato.caminho_modelo` e a tabela em `app/banco.py`.

PodeManterModelos = Depends(auth.exigir_algum_modulo("contratos", "modelos_contrato"))


@roteador.get("/api/modelos")
async def listar_modelos(_autorizado=PodeManterModelos):
    """Os modelos guardados no banco e de onde cada documento esta vindo.

    `origem` e o que responde a pergunta que aparece quando um contrato sai
    errado: o arquivo que gerou este documento e o que subiram pela tela, ou um
    que ficou no disco do servidor?
    """
    guardados = {
        m["codigo"]: m for m in await run_in_threadpool(armazenamento.listar_modelos)
    }
    saida = []
    for alvo in contrato.MODELOS:
        codigo = alvo["codigo"]
        registro = guardados.get(codigo)
        anterior = guardados.get(f"{codigo}{_SUFIXO_ANTERIOR}")
        try:
            caminho = await run_in_threadpool(contrato.caminho_modelo, codigo)
            nome, disponivel = caminho.name, True
        except contrato.ErroContrato:
            nome, disponivel = "", False
        saida.append(
            {
                "codigo": codigo,
                "rotulo": alvo["rotulo"],
                "disponivel": disponivel,
                "origem": "banco"
                if registro
                else ("docs" if disponivel else "nenhuma"),
                "arquivo": registro["nome_arquivo"] if registro else nome,
                "enviado_por": registro["enviado_por"] if registro else "",
                "atualizado_em": registro["atualizado_em"] if registro else "",
                "tem_anterior": bool(anterior),
                "anterior_arquivo": anterior["nome_arquivo"] if anterior else "",
            }
        )
    return {"modelos": saida}


_SUFIXO_ANTERIOR = "__anterior"


_RESPOSTAS_DE_TESTE = {
    "nome": "Maria Teste da Silva",
    "cpf": "11144477735",
    "estado_civil": "Solteiro(a)",
    "nacionalidade": "Brasileira",
    "profissao": "Carteiro",
    "rg": "1234567",
    "rg_orgao": "SSP",
    "rg_uf": "SP",
    "endereco": "Rua de Teste, 100, Centro, São Paulo/SP, CEP 01001-000",
    "uf": "SP",
    "municipio": "São Paulo",
    "telefone": "11999999999",
    "email": "teste@exemplo.com",
}


def _testar_modelo(conteudo: bytes) -> dict[str, list[str]]:
    import tempfile

    with tempfile.TemporaryDirectory() as pasta:
        caminho = Path(pasta) / "modelo.docx"
        caminho.write_bytes(conteudo)
        try:
            marcadores = contrato.marcadores_do_modelo(caminho)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"O sistema não conseguiu ler este Word, então o modelo não foi trocado: {exc}") from exc
        if not marcadores:
            raise HTTPException(
                400,
                "Nenhum campo entre colchetes foi encontrado neste modelo, como [nome completo] ou [CPF]. "
                "Sem eles o documento sairia sem os dados do cliente, então o modelo não foi trocado.",
            )
        valores = contrato.valores_da_entrevista(_RESPOSTAS_DE_TESTE)
        try:
            gerado, _faltando = contrato.preencher(valores, caminho)
            with zipfile.ZipFile(io.BytesIO(gerado)) as zf:
                if zf.testzip() is not None:
                    raise ValueError("o documento gerado saiu corrompido")
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"O teste de preenchimento falhou, então o modelo não foi trocado: {exc}") from exc
    preenchiveis = {contrato._chave(f"[{k}]") for k in contrato.valores_da_entrevista({})}
    return {"marcadores": marcadores, "sem_origem": [m for m in marcadores if m not in preenchiveis]}


def _modelo_em_uso(codigo: str) -> tuple[bytes, str, str] | None:
    registro = armazenamento.obter_modelo(codigo)
    if registro and registro.get("conteudo"):
        return registro["conteudo"], str(registro["nome_arquivo"]), str(registro.get("enviado_por") or "")
    try:
        caminho = contrato.caminho_modelo(codigo)
    except contrato.ErroContrato:
        return None
    return caminho.read_bytes(), caminho.name, "padrão local"


@roteador.get("/api/modelos/{codigo}/arquivo")
async def baixar_modelo(codigo: str, _autorizado=PodeManterModelos):
    try:
        contrato.modelo(codigo)
        caminho = await run_in_threadpool(contrato.caminho_modelo, codigo)
    except contrato.ErroContrato as exc:
        raise HTTPException(404, str(exc)) from exc
    return FileResponse(
        caminho,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=caminho.name,
    )


@roteador.post("/api/modelos/{codigo}/restaurar-anterior")
async def restaurar_modelo_anterior(codigo: str, usuario: auth.Usuario = PodeManterModelos):
    try:
        alvo = contrato.modelo(codigo)
    except contrato.ErroContrato as exc:
        raise HTTPException(404, str(exc)) from exc
    anterior = await run_in_threadpool(armazenamento.obter_modelo, f"{codigo}{_SUFIXO_ANTERIOR}")
    if not anterior or not anterior.get("conteudo"):
        raise HTTPException(404, "Não há versão anterior guardada deste documento.")
    atual = await run_in_threadpool(_modelo_em_uso, codigo)
    registro = await run_in_threadpool(
        armazenamento.salvar_modelo,
        codigo,
        nome_arquivo=anterior["nome_arquivo"],
        conteudo=anterior["conteudo"],
        enviado_por=usuario.nome,
    )
    if atual:
        await run_in_threadpool(
            armazenamento.salvar_modelo,
            f"{codigo}{_SUFIXO_ANTERIOR}",
            nome_arquivo=atual[1],
            conteudo=atual[0],
            enviado_por=atual[2],
        )
    return {"codigo": codigo, "rotulo": alvo["rotulo"], **registro}


@roteador.post("/api/modelos/{codigo}", status_code=201)
async def enviar_modelo(
    codigo: str,
    arquivo: UploadFile = File(...),
    usuario: auth.Usuario = PodeManterModelos,
):
    """Guarda o .docx daquele documento no banco, substituindo o anterior."""
    try:
        alvo = contrato.modelo(codigo)
    except contrato.ErroContrato as exc:
        raise HTTPException(404, str(exc)) from exc

    nome = arquivo.filename or f"{codigo}.docx"
    if Path(nome).suffix.lower() != ".docx":
        raise HTTPException(400, "O modelo precisa ser um arquivo .docx.")

    conteudo = await arquivo.read()
    if not conteudo:
        raise HTTPException(400, "Arquivo vazio.")
    if len(conteudo) > MAX_BYTES:
        raise HTTPException(413, f"Arquivo maior que {MAX_BYTES // (1024 * 1024)}MB.")
    # Conferir ANTES de gravar: um .docx corrompido guardado no banco quebraria a
    # geracao de todo mundo, e o erro apareceria na hora de fechar um contrato.
    if not zipfile.is_zipfile(io.BytesIO(conteudo)):
        raise HTTPException(400, "Este arquivo nao e um .docx valido.")

    teste = await run_in_threadpool(_testar_modelo, conteudo)
    atual = await run_in_threadpool(_modelo_em_uso, codigo)
    if atual:
        await run_in_threadpool(
            armazenamento.salvar_modelo,
            f"{codigo}{_SUFIXO_ANTERIOR}",
            nome_arquivo=atual[1],
            conteudo=atual[0],
            enviado_por=atual[2],
        )
    registro = await run_in_threadpool(
        armazenamento.salvar_modelo,
        codigo,
        nome_arquivo=nome,
        conteudo=conteudo,
        enviado_por=usuario.nome,
    )
    return {"codigo": codigo, "rotulo": alvo["rotulo"], **registro, **teste}


@roteador.delete("/api/modelos/{codigo}")
async def excluir_modelo(codigo: str, _autorizado=PodeManterModelos):
    """Tira o modelo do banco. O arquivo de `docs/` volta a valer, se houver."""
    if not await run_in_threadpool(armazenamento.excluir_modelo, codigo):
        raise HTTPException(404, f"Nenhum modelo guardado para {codigo!r}.")
    return {"codigo": codigo}


@roteador.get("/api/contrato/campos")
def campos_do_contrato():
    """Marcadores que o modelo pede — para conferir o mapeamento da entrevista."""
    try:
        marcadores = contrato.marcadores_do_modelo()
    except contrato.ErroContrato as exc:
        raise HTTPException(503, str(exc)) from exc
    preenchiveis = set(contrato.valores_da_entrevista({}))
    return {
        "modelo": contrato.caminho_modelo().name,
        "marcadores": marcadores,
        # O que o modelo pede e a entrevista não sabe responder: some daqui e
        # vira colchete no contrato assinado.
        "sem_origem": [
            m
            for m in marcadores
            if m not in {contrato._chave(f"[{k}]") for k in preenchiveis}
        ],
    }
