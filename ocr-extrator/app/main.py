"""API do extrator de documentos (FastAPI + PaddleOCR)."""

from __future__ import annotations

import logging
import os
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from . import armazenamento, auth, casos, categorias, pipeline, portal, rag, triagem
from .extractors import ROTULOS_TIPO

# Onde o frontend atende — é o que monta o link enviado ao cliente.
URL_PORTAL = os.getenv("URL_PORTAL", "http://localhost:3000").rstrip("/")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("api")

BASE = Path(__file__).resolve().parent.parent
STATIC = BASE / "static"

MAX_BYTES = 20 * 1024 * 1024
EXTENSOES = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff", ".pdf"}

@asynccontextmanager
async def ciclo_de_vida(_: FastAPI):
    """Aquece o OCR no boot, tirando os ~25s de carga do 1º upload.

    Vai para uma thread solta: o servidor precisa responder /api/saude de
    imediato, senão o `iniciar.ps1` espera o modelo para liberar o frontend.
    """
    threading.Thread(target=_tentar_aquecer, name="aquecer-ocr", daemon=True).start()
    yield


app = FastAPI(title="Extrator de Documentos — PaddleOCR", version="1.0.0", lifespan=ciclo_de_vida)

# O frontend Next chama esta API direto do navegador, então precisa de CORS.
# Com autenticação passou a existir credencial em jogo (o Bearer), então a lista
# de origens deixou de ser `*` e virou explícita — um `*` permitiria que qualquer
# página lesse as respostas se conseguisse um token.
ORIGENS = [
    o.strip()
    for o in os.getenv(
        "ORIGENS_PERMITIDAS", "http://localhost:3000,http://127.0.0.1:3000"
    ).split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGENS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Rotas que respondem sem token. Tudo que não estiver aqui exige autenticação —
# a lista é de exceções justamente para que uma rota nova nasça protegida.
PUBLICAS = {"/", "/api/saude", "/api/config", "/docs", "/openapi.json", "/redoc"}

# O portal do cliente não passa pelo Keycloak: o cliente não tem conta. Quem o
# protege é a senha do caso, conferida dentro de cada rota `/api/portal/...`
# (ver `_caso_do_portal`). O prefixo é fechado de propósito — nenhuma outra
# rota entra por aqui.
PREFIXO_PORTAL = "/api/portal/"


@app.middleware("http")
async def exigir_autenticacao(request: Request, call_next):
    caminho = request.url.path
    # O preflight não carrega o Authorization; recusá-lo quebraria todo o CORS.
    livre = (
        request.method == "OPTIONS"
        or caminho in PUBLICAS
        or caminho.startswith(PREFIXO_PORTAL)
    )

    if auth.ATIVA and not livre:
        try:
            request.state.usuario = auth.usuario_atual(request)
        except HTTPException as exc:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    else:
        request.state.usuario = auth.USUARIO_ABERTO

    return await call_next(request)


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


@app.get("/api/config")
def config():
    """Como o frontend deve falar com o Keycloak. Público e sem segredo — são os
    mesmos dados que apareceriam na URL de login."""
    return {"auth": auth.configuracao_publica()}


@app.get("/api/eu")
def eu(usuario: auth.Usuario = Depends(auth.usuario_atual)):
    """Quem está autenticado nesta requisição."""
    return usuario.to_dict()


def _aquecer_modelo() -> None:
    """Constrói os modelos do PaddleOCR rodando um OCR numa imagem em branco.

    A construção acontece dentro da thread dona do predictor (ver `ocr_engine`),
    porque é `rodar_ocr` quem a agenda lá — não chamar `get_engine` daqui.
    """
    import numpy as np

    from .ocr_engine import rodar_ocr

    rodar_ocr(np.full((80, 400, 3), 255, dtype=np.uint8))


def _tentar_aquecer() -> None:
    try:
        _aquecer_modelo()
        log.info("Modelo de OCR aquecido e pronto.")
    except Exception:
        # Sem rede na primeira execução, por exemplo: o upload tenta de novo.
        log.exception("Falha ao aquecer o modelo no boot")


@app.post("/api/aquecer")
def aquecer():
    """Baixa e carrega os modelos do PaddleOCR antes do primeiro upload."""
    try:
        _aquecer_modelo()
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


def _criar_portal(caso_id: str) -> dict[str, Any]:
    """Sorteia link e senha do portal e grava só o hash da senha."""
    token = portal.gerar_token()
    senha = portal.gerar_senha()
    senha_hash, sal = portal.hash_senha(senha)
    armazenamento.definir_portal(caso_id, token, senha_hash, sal)
    portal.limpar_tentativas(token)
    return {
        "url": f"{URL_PORTAL}/portal/{token}",
        "token": token,
        "senha": senha,
        "aviso": "Anote a senha agora: ela não pode ser consultada depois, só trocada.",
    }


@app.post("/api/triagem")
async def triar_entrevista(
    texto: str = Form(""),
    arquivo: UploadFile | None = File(None),
):
    """Lê a entrevista e sugere a categoria do caso — sem criar nada.

    Devolve um ranking com a evidência de cada categoria. Quem decide é o
    advogado: errar a categoria é errar o checklist inteiro, e o sistema passaria
    a cobrar documentos que a ação não usa.
    """
    conteudo = texto or ""

    if arquivo is not None and arquivo.filename:
        if not arquivo.filename.lower().endswith((".txt", ".md")):
            raise HTTPException(400, "Envie a entrevista em .txt (ou cole o texto).")
        bruto = await arquivo.read()
        if len(bruto) > 2 * 1024 * 1024:
            raise HTTPException(400, "Arquivo grande demais para uma entrevista (máx. 2 MB).")
        # Entrevista digitada no Word e salva como txt costuma vir em latin-1.
        for cod in ("utf-8", "utf-8-sig", "latin-1"):
            try:
                conteudo = bruto.decode(cod)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise HTTPException(400, "Não foi possível ler o texto do arquivo.")

    if not conteudo.strip():
        raise HTTPException(400, "Cole a entrevista ou envie um arquivo .txt.")

    resultado = triagem.triar(conteudo)
    resultado["dados"] = triagem.extrair_dados_do_cliente(conteudo)
    resultado["caracteres"] = len(conteudo)
    return resultado


class PedidoEstrategia(BaseModel):
    relato: str = Field(min_length=30, max_length=50_000)
    limite_precedentes: int = Field(default=8, ge=3, le=15)


@app.post("/api/estrategia")
async def estrategia(pedido: PedidoEstrategia):
    """Sugere próximos atos com precedentes recuperados antes da geração.

    Esta rota não é pública: passa pelo Keycloak. A resposta é apoio à decisão
    e inclui número, fonte, resultado e similaridade de cada precedente usado.
    """
    try:
        return await run_in_threadpool(
            rag.sugerir_acoes, pedido.relato, limite=pedido.limite_precedentes
        )
    except rag.ErroRAG as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        log.exception("Falha na análise estratégica")
        raise HTTPException(status_code=503, detail="Base estratégica indisponível.") from exc


@app.post("/api/casos", status_code=201)
def criar_caso(cliente: str = Form(...), categoria: str = Form(...), observacao: str = Form("")):
    """Cria o caso já com o portal do cliente pronto.

    O link nasce junto com o caso porque é isso que o escritório manda ao cliente
    logo depois de abrir o processo. A senha vai NESTA resposta e em nenhuma
    outra — o banco guarda apenas o hash.
    """
    if not cliente.strip():
        raise HTTPException(400, "Informe o nome do cliente.")
    if categorias.obter(categoria) is None:
        raise HTTPException(400, f"Categoria '{categoria}' não existe.")

    caso = armazenamento.criar_caso(cliente, categoria, observacao)
    return {**caso, "portal": _criar_portal(caso["id"])}


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


@app.post("/api/casos/{caso_id}/portal", status_code=201)
def gerar_portal(caso_id: str):
    """Troca a senha do portal. O link e a senha anteriores param de valer.

    Serve para casos criados antes do portal existir e para quando o cliente
    perde a senha — que não tem como ser recuperada, só substituída.
    """
    if armazenamento.obter_caso(caso_id) is None:
        raise HTTPException(404, "Caso não encontrado.")
    return _criar_portal(caso_id)


@app.get("/api/casos/{caso_id}/portal")
def consultar_portal(caso_id: str):
    """Estado do portal. Devolve o link, nunca a senha."""
    caso = armazenamento.obter_caso(caso_id)
    if caso is None:
        raise HTTPException(404, "Caso não encontrado.")

    token = caso.get("portal_token")
    return {
        "ativo": bool(token),
        "url": f"{URL_PORTAL}/portal/{token}" if token else None,
        "criado_em": caso.get("portal_criado_em"),
    }


@app.get("/api/casos/{caso_id}/pedido")
def pedido_do_caso(caso_id: str, incluir_opcionais: bool = False):
    """Texto pronto para o advogado mandar ao cliente com o que ainda falta."""
    pedido = casos.montar_pedido(caso_id, incluir_opcionais)
    if pedido is None:
        raise HTTPException(404, "Caso não encontrado.")
    return pedido


def _ler_documento(
    entrega_id: str,
    caso_id: str,
    conteudo: bytes,
    nome: str,
    item_checklist,
    categoria,
    idioma: str,
    usar_para_rg_e_cpf: bool,
) -> None:
    """O OCR propriamente dito, já fora do ciclo da requisição.

    Roda numa thread de fundo: a requisição do upload não espera por isto. O
    PaddleOCR continua serializado na thread dele (ver `ocr_engine`), então
    vários envios simplesmente entram na fila em vez de brigar por CPU.
    """
    try:
        if item_checklist.tipo_ocr in {"rg", "cpf"}:
            tipo_extracao = "cin" if usar_para_rg_e_cpf else None
        else:
            tipo_extracao = item_checklist.tipo_ocr

        resultado = pipeline.processar(conteudo, nome, idioma, tipo_extracao)

        unificar = usar_para_rg_e_cpf
        if not unificar and item_checklist.tipo_ocr in {"rg", "cpf"}:
            unificar = casos.cobre_rg_e_cpf(resultado)

        try:
            itens_atendidos = (
                casos.itens_para_identidade_unificada(categoria, item_checklist)
                if unificar
                else [item_checklist.codigo]
            )
        except ValueError:
            itens_atendidos = [item_checklist.codigo]
            unificar = False

        detectado = resultado.get("tipo", {}).get("detectado")
        confere = casos.tipo_confere(item_checklist, detectado, unificar)
        armazenamento.concluir_entrega(entrega_id, resultado, confere, itens_atendidos)
    except Exception as exc:
        log.exception("Falha ao ler o documento da entrega %s", entrega_id)
        armazenamento.falhar_entrega(entrega_id, str(exc))


async def _registrar_documento(
    caso: dict[str, Any],
    item: str,
    arquivo: UploadFile,
    idioma: str,
    usar_para_rg_e_cpf: bool,
) -> dict[str, Any]:
    """OCR + registro da entrega. Compartilhado pelo advogado e pelo portal.

    O cliente passa pelo mesmo caminho de propósito: a validação de tipo, a
    legibilidade e o vínculo RG/CPF não podem depender de quem enviou.
    """
    caso_id = caso["id"]
    categoria = categorias.obter(caso["categoria"])
    if categoria is None:
        raise HTTPException(409, f"Categoria '{caso['categoria']}' não existe mais.")

    item_checklist = next((i for i in categoria.itens if i.codigo == item), None)
    if item_checklist is None:
        raise HTTPException(400, f"Item '{item}' não pertence ao checklist de {categoria.nome}.")

    # Valida a opção manual antes de gastar o OCR, para o erro sair na hora.
    if usar_para_rg_e_cpf:
        try:
            casos.itens_para_identidade_unificada(categoria, item_checklist)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    conteudo = await _ler_upload(arquivo)
    nome = arquivo.filename or "sem-nome"

    # O arquivo vai para o disco e a entrega é criada ANTES do OCR: é isso que
    # permite responder o upload em milissegundos. Medido nesta máquina, a
    # leitura leva de 12s (ociosa) a 200s (saturada) — tempo demais para segurar
    # uma requisição de celular, que morreria por timeout no meio.
    destino = armazenamento.DIR_ARQUIVOS / caso_id
    destino.mkdir(parents=True, exist_ok=True)
    caminho = destino / f"{item}_{uuid.uuid4()}{Path(nome).suffix.lower()}"
    caminho.write_bytes(conteudo)

    entrega = armazenamento.registrar_entrega_pendente(caso_id, item, nome, caminho)

    # Passar o tipo esperado orienta a extração dos campos, mas o classificador
    # continua opinando por conta própria — é a opinião dele que revela se veio o
    # arquivo trocado. A decisão fica em `_ler_documento`, junto do OCR.
    threading.Thread(
        target=_ler_documento,
        args=(
            entrega["id"], caso_id, conteudo, nome,
            item_checklist, categoria, idioma, usar_para_rg_e_cpf,
        ),
        name=f"ocr-{entrega['id'][:8]}",
        daemon=True,
    ).start()

    return {"entrega": entrega, "processando": True}


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
    return await _registrar_documento(caso, item, arquivo, idioma, usar_para_rg_e_cpf)


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


# ------------------------------------------------------ portal do cliente
#
# Estas rotas são públicas (não passam pelo Keycloak): quem as protege é a senha
# do caso. Cada uma confere a sessão do portal por conta própria — não há
# dependência global que faça isso por elas.


def _caso_do_portal(token: str, request: Request) -> dict[str, Any]:
    """Resolve o caso pelo token E exige uma sessão válida deste caso."""
    caso = armazenamento.obter_caso_por_token(token)
    if caso is None:
        # Mesma resposta de sessão inválida: não confirmamos se o link existe.
        raise HTTPException(404, "Link inválido ou expirado.")

    cabecalho = request.headers.get("authorization", "")
    sessao = cabecalho[7:].strip() if cabecalho.lower().startswith("bearer ") else ""
    if not portal.validar_sessao(sessao, token):
        raise HTTPException(401, "Informe a senha para acessar seus documentos.")
    return caso


@app.post("/api/portal/{token}/entrar")
def portal_entrar(token: str, senha: str = Form(...)):
    espera = portal.bloqueado(token)
    if espera > 0:
        raise HTTPException(
            429,
            f"Muitas tentativas. Tente novamente em {espera // 60 + 1} minuto(s) "
            "ou peça uma senha nova ao escritório.",
        )

    caso = armazenamento.obter_caso_por_token(token)
    # Link inexistente e senha errada devolvem a mesma coisa, para o link não
    # virar um oráculo que diz quais casos existem.
    if caso is None or not caso.get("portal_senha_hash"):
        portal.registrar_falha(token)
        raise HTTPException(401, "Link ou senha incorretos.")

    if not portal.conferir_senha(senha, caso["portal_senha_hash"], caso["portal_sal"]):
        portal.registrar_falha(token)
        raise HTTPException(401, "Link ou senha incorretos.")

    portal.limpar_tentativas(token)
    return {**portal.criar_sessao(token), "cliente": caso["cliente"]}


@app.get("/api/portal/{token}/situacao")
def portal_situacao(token: str, request: Request):
    """O checklist na visão do cliente: o que chegou e o que falta."""
    caso = _caso_do_portal(token, request)
    situacao = casos.montar_situacao(caso["id"])
    if situacao is None:
        raise HTTPException(404, "Caso não encontrado.")
    return casos.visao_do_cliente(situacao)


@app.post("/api/portal/{token}/documentos", status_code=201)
async def portal_enviar(
    token: str,
    request: Request,
    item: str = Form(...),
    arquivo: UploadFile = File(...),
):
    """Upload feito pelo cliente. Mesmo caminho do advogado, resposta enxuta."""
    caso = _caso_do_portal(token, request)
    await _registrar_documento(caso, item, arquivo, "pt", False)

    situacao = casos.montar_situacao(caso["id"])
    return casos.visao_do_cliente(situacao) if situacao else {}


@app.get("/api/entregas/{entrega_id}")
def obter_entrega(entrega_id: str):
    entrega = armazenamento.obter_entrega(entrega_id)
    if entrega is None:
        raise HTTPException(404, "Entrega não encontrada.")
    entrega.pop("caminho", None)  # caminho no disco não interessa ao cliente HTTP
    return entrega


@app.get("/api/entregas/{entrega_id}/arquivo")
def baixar_arquivo_entrega(entrega_id: str, download: bool = False):
    entrega = armazenamento.obter_entrega(entrega_id)
    if entrega is None:
        raise HTTPException(404, "Entrega não encontrada.")

    caminho = Path(entrega["caminho"]).resolve()
    if armazenamento.DIR_ARQUIVOS.resolve() not in caminho.parents or not caminho.is_file():
        raise HTTPException(404, "Arquivo não encontrado no disco.")

    # `inline` deixa o navegador exibir o arquivo em vez de baixá-lo, que é o que
    # permite a pré-visualização no checklist. Passar só `filename=` produzia
    # `Content-Disposition: attachment` e obrigava a baixar para ver o que chegou.
    # Com `?download=1` o comportamento antigo continua disponível.
    return FileResponse(
        caminho,
        filename=entrega["arquivo"],
        content_disposition_type="attachment" if download else "inline",
    )


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
