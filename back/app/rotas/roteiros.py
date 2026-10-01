"""Roteiros de entrevista: catálogo, importação, edição e exclusão."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
)
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .. import (
    armazenamento,
    auth,
    indexacao_roteiro,
    jobs,
    roteiro_ia,
    roteiros,
)
from ..tasks.roteiro import importar_roteiro as importar_roteiro_task
from .comum import BASE, MAX_BYTES, log

roteador = APIRouter()


@roteador.get("/api/roteiros")
def listar_roteiros(
    pagina: int | None = Query(None, ge=1),
    tamanho: int | None = Query(None, ge=1, le=100),
):
    """Roteiros de entrevista disponíveis, sem as perguntas.

    `importado` diz se aquele roteiro tem uma versão salva no catálogo. É o que
    a tela usa para oferecer "voltar ao original": só faz sentido em quem tem
    original para voltar.
    """
    # Não chama `roteiros.listar()`: ela materializa blocos e perguntas, mas o
    # seletor só precisa dos metadados abaixo.
    todos = roteiros.listar_resumos()
    total = len(todos)
    importados = sum(1 for r in todos if r["importado"])
    tamanho_real = tamanho or total or 1
    paginas = max(1, (total + tamanho_real - 1) // tamanho_real)
    pagina_real = min(pagina or 1, paginas)

    if pagina is not None or tamanho is not None:
        inicio = (pagina_real - 1) * tamanho_real
        todos = todos[inicio : inicio + tamanho_real]

    return {
        "roteiros": todos,
        "aviso_catalogo": (
            "O catálogo de roteiros salvos não respondeu. Mostrando apenas os roteiros originais do sistema."
            if roteiros.catalogo_resumos_parcial()
            else ""
        ),
        "total": total,
        "pagina": pagina_real,
        "tamanho": tamanho_real,
        "paginas": paginas,
        "importados": importados,
        "originais": total - importados,
    }


@roteador.get("/api/roteiros/{codigo}")
def obter_roteiro(codigo: str):
    """Roteiro completo: blocos, perguntas e quais delas abrem o gravador."""
    roteiro = roteiros.obter(codigo)
    if roteiro is None:
        raise HTTPException(404, f"Roteiro '{codigo}' não encontrado.")
    return {**roteiro.to_dict(), "mapa_rastreio": roteiros.mapa_rastreio(roteiro)}


# ------------------------------------------------ roteiro vindo de documento
#
# O roteiro do escritório está escrito em `app/roteiros.py` porque foi transcrito
# à mão de um `.docx`. Cada nova categoria de causa tem o seu documento, e
# transcrever 86 perguntas em dataclasses leva um dia. Estas três rotas fecham
# esse caminho: o documento entra como arquivo, vira proposta de roteiro, e o
# advogado corrige o que o modelo errou antes de salvar.
#
# Nada aqui grava sozinho. A importação devolve uma PROPOSTA; salvar é um passo
# separado e deliberado, porque um roteiro é o que a entrevista inteira segue.


#: Manter o catálogo é trabalho de escritório, não de atendimento: o secretário
#: tem este módulo sem ter `entrevista`. Ver `app/perfis.py`.
PodeManterRoteiros = Depends(auth.exigir_modulo("roteiros"))


@roteador.post("/api/roteiros/importar", status_code=202)
async def importar_roteiro(
    tarefas: BackgroundTasks,
    arquivo: UploadFile = File(...),
    _autorizado=PodeManterRoteiros,
):
    """Agenda a leitura do documento e a montagem do roteiro neste servidor.

    202 e não 200: são de dez segundos a dois minutos entre OCR e as chamadas ao
    modelo, uma por bloco. A tela acompanha por `GET /api/jobs/{id}`, onde o
    campo `resultado.etapa` diz em que bloco a montagem está.

    Não depende do worker Celery: esta é uma operação administrativa rara e a
    produção pode continuar atendendo mesmo quando os workers estiverem fora.
    O processamento começa em thread logo depois de a resposta 202 ser enviada.
    """
    nome = arquivo.filename or "documento"
    extensao = Path(nome).suffix.lower()
    if extensao not in roteiro_ia.EXTENSOES_ROTEIRO:
        raise HTTPException(
            400,
            f"Extensão '{extensao or '(sem)'}' não suportada. "
            f"Use: {', '.join(sorted(roteiro_ia.EXTENSOES_ROTEIRO))}.",
        )

    conteudo = await arquivo.read()
    if not conteudo:
        raise HTTPException(400, "Arquivo vazio.")
    if len(conteudo) > MAX_BYTES:
        raise HTTPException(413, f"Arquivo maior que {MAX_BYTES // (1024 * 1024)}MB.")

    pasta = BASE / "tmp" / "jobs"
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / f"{uuid.uuid4().hex}{extensao}"
    caminho.write_bytes(conteudo)

    try:
        await run_in_threadpool(jobs.inicializar)
        job_id = await run_in_threadpool(
            jobs.criar, "ROTEIRO", arquivo=str(caminho), conteudo=conteudo
        )
        tarefas.add_task(importar_roteiro_task.run, job_id, str(caminho), nome)
    except Exception as exc:
        caminho.unlink(missing_ok=True)
        log.exception("Falha ao agendar importação de roteiro")
        raise HTTPException(503, f"Processamento indisponível: {exc}") from exc

    return {"job_id": job_id}


class PedidoSalvarRoteiro(BaseModel):
    """O roteiro inteiro, como o editor da tela o tem em mãos."""

    roteiro: dict[str, Any]
    #: De onde ele veio — nome do arquivo importado, ou vazio se foi escrito à mão.
    origem: str = Field(default="", max_length=400)


def _indexar_roteiro_salvo(roteiro: roteiros.Roteiro) -> None:
    """Indexação é complemento da revisão, nunca motivo para perder um roteiro."""
    try:
        resultado = indexacao_roteiro.indexar(roteiro)
        log.info("Roteiro '%s' indexado: %d expectativa(s)", roteiro.codigo, resultado["chunks"])
    except Exception:
        # A revisão sempre lê o roteiro salvo diretamente. Se pgvector ou o
        # provedor de embeddings oscilarem, salvar o trabalho do escritório
        # continua sendo mais importante que atualizar este índice auxiliar.
        log.warning("Indexação vetorial do roteiro '%s' falhou", roteiro.codigo, exc_info=True)


@roteador.post("/api/roteiros", status_code=201)
async def salvar_roteiro(
    pedido: PedidoSalvarRoteiro,
    tarefas: BackgroundTasks,
    usuario: auth.Usuario = PodeManterRoteiros,
):
    """Grava o roteiro no catálogo. Regrava, se o código já existir.

    É por aqui que passa tanto o roteiro recém-importado quanto a edição feita no
    meio de um atendimento — e é de propósito que os dois usem a mesma validação:
    um roteiro escrito por um advogado às onze da noite pode quebrar a tela
    exatamente como um escrito pelo modelo.
    """
    try:
        roteiro = roteiros.de_dict(pedido.roteiro)
    except roteiros.RoteiroInvalido as exc:
        raise HTTPException(422, str(exc)) from exc

    try:
        registro = await run_in_threadpool(
            armazenamento.salvar_roteiro,
            roteiro.codigo,
            nome=roteiro.nome,
            descricao=roteiro.descricao,
            conteudo=roteiro.to_dict(),
            origem=pedido.origem.strip(),
            criado_por=usuario.nome,
        )
    except Exception as exc:
        log.exception("Falha ao salvar roteiro '%s'", roteiro.codigo)
        raise HTTPException(503, f"Não foi possível salvar o roteiro: {exc}") from exc

    roteiros.invalidar_cache()
    tarefas.add_task(_indexar_roteiro_salvo, roteiro)
    return {
        **roteiro.to_dict(),
        "mapa_rastreio": roteiros.mapa_rastreio(roteiro),
        "atualizado_em": registro.get("atualizado_em", ""),
    }


@roteador.delete("/api/roteiros/{codigo}")
async def excluir_roteiro(codigo: str, tarefas: BackgroundTasks, _autorizado=PodeManterRoteiros):
    """Tira o roteiro do catálogo.

    Num roteiro importado isto o apaga. Num que também existe em
    `app/roteiros.py`, desfaz a edição e devolve o do módulo — a saída para uma
    edição malfeita no meio do expediente, sem precisar de deploy.
    """
    removido = await run_in_threadpool(armazenamento.excluir_roteiro, codigo)
    if not removido:
        raise HTTPException(404, f"Roteiro '{codigo}' não está salvo no catálogo.")

    roteiros.invalidar_cache()
    tarefas.add_task(indexacao_roteiro.remover, codigo)
    return {"codigo": codigo, "revertido_para_o_modulo": codigo in roteiros.ROTEIROS}
