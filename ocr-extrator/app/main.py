"""API do extrator de documentos (FastAPI + PaddleOCR)."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from . import armazenamento, casos, categorias, pipeline
from .extractors import ROTULOS_TIPO

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("api")

BASE = Path(__file__).resolve().parent.parent
STATIC = BASE / "static"

MAX_BYTES = 20 * 1024 * 1024
EXTENSOES = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}

app = FastAPI(title="Extrator de Documentos — PaddleOCR", version="1.0.0")

# O frontend Next (:3100) chama esta API direto do navegador, então precisa de CORS.
# `*` é aceitável aqui porque o servidor escuta só em 127.0.0.1 e não usa cookies nem
# sessão — não há credencial que uma página de terceiros pudesse reaproveitar. Se um dia
# isto for exposto na rede, troque por uma lista explícita de origens.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


armazenamento.inicializar()


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/tipos")
def tipos():
    return {"tipos": [{"codigo": k, "descricao": v} for k, v in ROTULOS_TIPO.items()]}


@app.get("/api/categorias")
def listar_categorias():
    """Categorias de processo, cada uma com seu checklist de documentos."""
    return {"categorias": [c.to_dict() for c in categorias.listar()]}


@app.get("/api/categorias/{codigo}")
def obter_categoria(codigo: str):
    categoria = categorias.obter(codigo)
    if categoria is None:
        raise HTTPException(404, f"Categoria '{codigo}' não encontrada.")
    return categoria.to_dict()


@app.get("/api/saude")
def saude():
    from . import ocr_engine  # lê o atributo do módulo, não uma cópia do valor

    return {"status": "ok", "modelo_carregado": ocr_engine._engine is not None}


@app.post("/api/aquecer")
def aquecer():
    """Baixa e carrega os modelos do PaddleOCR antes do primeiro upload."""
    import numpy as np

    from .ocr_engine import rodar_ocr

    branco = np.full((80, 400, 3), 255, dtype=np.uint8)
    try:
        rodar_ocr(branco)
        return {"status": "pronto"}
    except Exception as exc:
        log.exception("Falha ao aquecer o modelo")
        raise HTTPException(status_code=500, detail=f"Falha ao carregar o modelo: {exc}") from exc


async def _ler_upload(arquivo: UploadFile) -> bytes:
    """Valida extensão e tamanho, devolvendo os bytes do arquivo enviado."""
    ext = Path(arquivo.filename or "").suffix.lower()
    if ext and ext not in EXTENSOES:
        raise HTTPException(400, f"Extensão '{ext}' não suportada. Use: {', '.join(sorted(EXTENSOES))}")

    conteudo = await arquivo.read()
    if not conteudo:
        raise HTTPException(400, "Arquivo vazio.")
    if len(conteudo) > MAX_BYTES:
        raise HTTPException(413, f"Arquivo maior que {MAX_BYTES // (1024 * 1024)}MB.")
    return conteudo


async def _processar(conteudo: bytes, nome: str, idioma: str, tipo_forcado: str | None) -> dict:
    try:
        # O OCR leva segundos e é puro CPU: fora do event loop, senão o servidor
        # para de responder (inclusive ao /api/saude) enquanto processa.
        return await run_in_threadpool(pipeline.processar, conteudo, nome, idioma, tipo_forcado)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        log.exception("Erro ao processar %s", nome)
        raise HTTPException(500, f"Erro ao processar a imagem: {exc}") from exc


@app.post("/api/extrair")
async def extrair(
    arquivo: UploadFile = File(...),
    idioma: str = Form("pt"),
    tipo: str | None = Form(None),
):
    conteudo = await _ler_upload(arquivo)
    tipo_forcado = tipo if tipo and tipo not in ("auto", "", "None") else None
    resultado = await _processar(conteudo, arquivo.filename or "sem-nome", idioma, tipo_forcado)
    return JSONResponse(resultado)


# ------------------------------------------------------------------- casos


@app.post("/api/casos", status_code=201)
def criar_caso(cliente: str = Form(...), categoria: str = Form(...), observacao: str = Form("")):
    if not cliente.strip():
        raise HTTPException(400, "Informe o nome do cliente.")
    if categorias.obter(categoria) is None:
        raise HTTPException(400, f"Categoria '{categoria}' não existe.")
    return armazenamento.criar_caso(cliente, categoria, observacao)


@app.get("/api/casos")
def listar_casos():
    return {"casos": armazenamento.listar_casos()}


@app.get("/api/casos/{caso_id}")
def obter_caso(caso_id: str):
    situacao = casos.montar_situacao(caso_id)
    if situacao is None:
        raise HTTPException(404, "Caso não encontrado.")
    return situacao


@app.patch("/api/casos/{caso_id}")
def atualizar_caso(caso_id: str, cliente: str | None = Form(None), observacao: str | None = Form(None)):
    if not armazenamento.atualizar_caso(caso_id, cliente, observacao):
        raise HTTPException(404, "Caso não encontrado ou nada para atualizar.")
    return armazenamento.obter_caso(caso_id)


@app.delete("/api/casos/{caso_id}")
def excluir_caso(caso_id: str):
    if not armazenamento.excluir_caso(caso_id):
        raise HTTPException(404, "Caso não encontrado.")
    return {"removido": True}


@app.get("/api/casos/{caso_id}/pedido")
def pedido_do_caso(caso_id: str, incluir_opcionais: bool = False):
    """Texto pronto para o advogado mandar ao cliente com o que ainda falta."""
    pedido = casos.montar_pedido(caso_id, incluir_opcionais)
    if pedido is None:
        raise HTTPException(404, "Caso não encontrado.")
    return pedido


@app.post("/api/casos/{caso_id}/documentos", status_code=201)
async def enviar_documento(
    caso_id: str,
    item: str = Form(...),
    arquivo: UploadFile = File(...),
    idioma: str = Form("pt"),
    usar_para_rg_e_cpf: bool = Form(False),
):
    """Recebe um documento, roda o OCR e marca o item do checklist."""
    caso = armazenamento.obter_caso(caso_id)
    if caso is None:
        raise HTTPException(404, "Caso não encontrado.")

    categoria = categorias.obter(caso["categoria"])
    if categoria is None:
        raise HTTPException(409, f"Categoria '{caso['categoria']}' não existe mais.")

    item_checklist = next((i for i in categoria.itens if i.codigo == item), None)
    if item_checklist is None:
        raise HTTPException(400, f"Item '{item}' não pertence ao checklist de {categoria.nome}.")

    try:
        itens_atendidos = (
            casos.itens_para_identidade_unificada(categoria, item_checklist)
            if usar_para_rg_e_cpf
            else [item_checklist.codigo]
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    conteudo = await _ler_upload(arquivo)
    nome = arquivo.filename or "sem-nome"

    # Passar o tipo esperado orienta a extração dos campos, mas o classificador
    # continua opinando por conta própria — é a opinião dele que revela se veio o
    # arquivo trocado.
    # Na opção unificada, a extração precisa seguir o layout da CIN, não o de um
    # RG antigo nem o de um cartão CPF.
    tipo_extracao = "cin" if usar_para_rg_e_cpf else item_checklist.tipo_ocr
    resultado = await _processar(conteudo, nome, idioma, tipo_extracao)

    detectado = resultado.get("tipo", {}).get("detectado")
    confere = casos.tipo_confere(item_checklist, detectado, usar_para_rg_e_cpf)

    destino = armazenamento.DIR_ARQUIVOS / caso_id
    destino.mkdir(parents=True, exist_ok=True)
    caminho = destino / f"{item}_{resultado['id']}{Path(nome).suffix.lower()}"
    caminho.write_bytes(conteudo)

    entrega = armazenamento.registrar_entrega(
        caso_id, item, nome, caminho, resultado, confere, itens_atendidos
    )
    return {"entrega": entrega, "extracao": resultado}


@app.post("/api/casos/{caso_id}/identidade-unificada")
async def vincular_identidade_unificada(caso_id: str, entrega_id: str = Form(...)):
    """Faz uma entrega de RG/CPF existente valer para os dois itens quando for CIN."""
    caso = armazenamento.obter_caso(caso_id)
    if caso is None:
        raise HTTPException(404, "Caso não encontrado.")

    entrega = armazenamento.obter_entrega(entrega_id)
    if entrega is None or entrega["caso_id"] != caso_id:
        raise HTTPException(404, "Entrega não encontrada neste caso.")

    categoria = categorias.obter(caso["categoria"])
    item = next((i for i in categoria.itens if i.codigo == entrega["item_codigo"]), None) if categoria else None
    if item is None:
        raise HTTPException(400, "Esta entrega não pertence a um item de checklist válido.")
    try:
        itens_atendidos = casos.itens_para_identidade_unificada(categoria, item)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    caminho = Path(entrega["caminho"]).resolve()
    if armazenamento.DIR_ARQUIVOS.resolve() not in caminho.parents or not caminho.is_file():
        raise HTTPException(404, "Arquivo original não encontrado.")

    # O botão é a confirmação expressa de que se trata de identidade unificada.
    # Reprocessamos no layout da CIN para extrair e validar o CPF sem depender de
    # o classificador conseguir nomear corretamente todas as versões do documento.
    resultado = await _processar(caminho.read_bytes(), entrega["arquivo"], "pt", "cin")

    atualizada = armazenamento.atualizar_para_identidade_unificada(
        entrega_id, resultado, itens_atendidos
    )
    if atualizada is None:
        raise HTTPException(404, "Entrega não encontrada.")
    return {"entrega": atualizada, "extracao": resultado}


@app.get("/api/entregas/{entrega_id}")
def obter_entrega(entrega_id: str):
    entrega = armazenamento.obter_entrega(entrega_id)
    if entrega is None:
        raise HTTPException(404, "Entrega não encontrada.")
    entrega.pop("caminho", None)  # caminho no disco não interessa ao cliente HTTP
    return entrega


@app.get("/api/entregas/{entrega_id}/arquivo")
def baixar_arquivo_entrega(entrega_id: str):
    entrega = armazenamento.obter_entrega(entrega_id)
    if entrega is None:
        raise HTTPException(404, "Entrega não encontrada.")

    caminho = Path(entrega["caminho"]).resolve()
    if armazenamento.DIR_ARQUIVOS.resolve() not in caminho.parents or not caminho.is_file():
        raise HTTPException(404, "Arquivo não encontrado no disco.")
    return FileResponse(caminho, filename=entrega["arquivo"])


@app.delete("/api/entregas/{entrega_id}")
def excluir_entrega(entrega_id: str):
    if not armazenamento.excluir_entrega(entrega_id):
        raise HTTPException(404, "Entrega não encontrada.")
    return {"removido": True}


@app.get("/api/temp/{nome}")
def baixar_temp(nome: str):
    """Serve o JSON/XML temporário gerado para um documento."""
    if not nome.endswith((".json", ".xml")) or "/" in nome or "\\" in nome or ".." in nome:
        raise HTTPException(400, "Nome de arquivo inválido.")

    caminho = (pipeline.TMP_DIR / nome).resolve()
    if pipeline.TMP_DIR.resolve() not in caminho.parents or not caminho.is_file():
        raise HTTPException(404, "Arquivo temporário não encontrado ou já expirado.")

    media = "application/json" if nome.endswith(".json") else "application/xml"
    return FileResponse(caminho, media_type=media, filename=nome)


@app.delete("/api/temp")
def limpar():
    return {"removidos": pipeline.limpar_temporarios()}
