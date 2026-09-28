"""Modelo visual da petição, skill de petição e skills jurídicas."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    UploadFile,
)
from fastapi.responses import Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .. import (
    armazenamento,
    auth,
    docx_pdf,
    peticao_local,
    peticao_skills,
    rag,
    skills_juridicas,
)
from .comum import MAX_BYTES, _ler_upload, log

roteador = APIRouter()


PodeManterModeloPeticao = Depends(auth.exigir_modulo("agente"))


@roteador.get("/api/modelos/peticao/acervo-conteudistico")
async def estatisticas_acervo_conteudistico(_autorizado=PodeManterModeloPeticao):
    """Mostra apenas volume e integridade das peças usadas como padrão de redação."""
    try:
        return await run_in_threadpool(rag.estatisticas_pecas_conteudisticas)
    except Exception as exc:
        log.warning("Acervo conteudístico de peças indisponível: %s", exc)
        raise HTTPException(503, "Não foi possível consultar o acervo de treinamento agora.") from exc


@roteador.get("/api/modelos/peticao/visual")
async def obter_modelo_visual_peticao(_autorizado=PodeManterModeloPeticao):
    """Modelo global de marca, separado dos exemplos jurídicos do Style Engine."""
    try:
        registro = await run_in_threadpool(
            armazenamento.obter_modelo, peticao_local.MODELO_VISUAL_GERAL
        )
    except Exception:
        # O Lara & Melo já é o fallback usado na geração. A tela deve mostrar o
        # mesmo padrão mesmo se a cópia substituível estiver temporariamente
        # inacessível, em vez de morrer com 500 antes de renderizar o preview.
        log.exception("modelo visual não pôde ser lido; usando padrão embutido")
        registro = None
    if not registro:
        return {
            "arquivo": "Padrão Lara & Melo",
            "origem": "embutido",
            "fonte": "Arial",
            "enviado_por": "",
            "atualizado_em": "",
            "atributos": {},
        }
    fonte = await run_in_threadpool(peticao_local.extrair_fonte_visual, registro["conteudo"])
    # O que mais o .docx revela do padrão do escritório — tamanho, espaçamento,
    # margens, alinhamento — para a tela mostrar tudo que foi captado.
    atributos = await run_in_threadpool(
        peticao_local.analisar_estilo, registro["conteudo"]
    )
    return {
        "arquivo": registro["nome_arquivo"],
        "origem": "banco",
        "fonte": fonte,
        "enviado_por": registro["enviado_por"],
        "atualizado_em": registro["atualizado_em"],
        "atributos": atributos,
    }


@roteador.get("/api/modelos/peticao/visual/logo")
async def logo_do_modelo_visual(_autorizado=PodeManterModeloPeticao):
    """A logo que será carimbada nas petições, para conferir ANTES de gerar uma.

    O cartão dizia o nome do arquivo e a fonte, e mais nada — quem trocava o
    modelo descobria qual imagem o extrator escolheu só quando abria a primeira
    petição pronta. E há o que escolher: um .docx institucional costuma ter
    várias imagens, e a heurística prefere a que está relacionada por um
    cabeçalho (ver `extrair_identidade_visual`). Mostrar o resultado é o que
    separa "trocou o timbre" de "achou que trocou".

    Serve tanto o modelo do escritório quanto o Lara & Melo embutido: quem olha
    quer ver o que vai sair, não saber de onde veio.
    """
    try:
        logo, _fonte, extensao, _nome = await run_in_threadpool(
            peticao_local.identidade_visual
        )
    except peticao_local.ErroPeticao as exc:
        raise HTTPException(422, str(exc)) from exc
    return Response(
        content=logo,
        media_type="image/jpeg" if extensao == ".jpg" else "image/png",
        # Sem cache: trocar o modelo e continuar vendo a logo antiga faria a
        # tela mentir justamente no momento em que ela existe para confirmar.
        headers={"Cache-Control": "no-store"},
    )


class ConfiguracaoVisualEntrada(BaseModel):
    fonte: str = ""
    tamanho_fonte_pt: float = Field(12, ge=8, le=24)
    espacamento_linha: float = Field(1.5, ge=1, le=3)
    recuo_primeira_linha_cm: float = Field(1.25, ge=0, le=5)
    margem_superior_cm: float = Field(3.74, ge=1.5, le=7)
    margem_direita_cm: float = Field(1.89, ge=1, le=6)
    margem_inferior_cm: float = Field(1.25, ge=1, le=6)
    margem_esquerda_cm: float = Field(3.0, ge=1, le=6)
    alinhamento_corpo: str = "justificado"
    alinhamento_titulos: str = "esquerda"
    altura_logo_cm: float = Field(2.36, ge=0.5, le=5)
    preferir_tabelas: bool = False


@roteador.get("/api/modelos/peticao/visual/configuracao")
async def obter_configuracao_visual_peticao(_autorizado=PodeManterModeloPeticao):
    return peticao_local.configuracao_visual()


@roteador.put("/api/modelos/peticao/visual/configuracao")
async def salvar_configuracao_visual_peticao(
    entrada: ConfiguracaoVisualEntrada,
    usuario: auth.Usuario = PodeManterModeloPeticao,
):
    dados = entrada.model_dump()
    if dados["alinhamento_corpo"] not in {"justificado", "esquerda", "direita"}:
        raise HTTPException(422, "Alinhamento do corpo inválido.")
    if dados["alinhamento_titulos"] not in {"esquerda", "centralizado"}:
        raise HTTPException(422, "Alinhamento dos títulos inválido.")
    await run_in_threadpool(
        armazenamento.salvar_modelo,
        peticao_local.MODELO_VISUAL_CONFIG,
        nome_arquivo="configuracao-visual.json",
        conteudo=json.dumps(dados, ensure_ascii=False).encode("utf-8"),
        enviado_por=usuario.nome,
    )
    return dados


@roteador.post("/api/modelos/peticao/visual/logo", status_code=201)
async def enviar_logo_do_modelo_visual(
    arquivo: UploadFile = File(...),
    usuario: auth.Usuario = PodeManterModeloPeticao,
):
    nome = arquivo.filename or "logo-escritorio.png"
    if Path(nome).suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        raise HTTPException(400, "Envie a logo em PNG ou JPG.")
    conteudo = await arquivo.read()
    if not conteudo or len(conteudo) > MAX_BYTES:
        raise HTTPException(400, "Logo inválida ou maior que o limite permitido.")
    await run_in_threadpool(
        armazenamento.salvar_modelo,
        peticao_local.MODELO_VISUAL_LOGO,
        nome_arquivo=nome,
        conteudo=conteudo,
        enviado_por=usuario.nome,
    )
    return {"arquivo": nome}


@roteador.get("/api/modelos/peticao/visual/preview")
async def previa_do_modelo_visual(_autorizado=PodeManterModeloPeticao):
    """PDF do arquivo importado para conferência integral, sem recriar seu layout."""
    registro = await run_in_threadpool(armazenamento.obter_modelo, peticao_local.MODELO_VISUAL_GERAL)
    if not registro:
        raise HTTPException(404, "Envie um modelo .docx para ver sua prévia integral.")
    try:
        pdf = await run_in_threadpool(docx_pdf.converter, bytes(registro["conteudo"]))
    except docx_pdf.ErroConversaoDocx as exc:
        raise HTTPException(422, str(exc)) from exc
    return Response(content=pdf, media_type="application/pdf", headers={"Cache-Control": "no-store"})


@roteador.post("/api/modelos/peticao/visual", status_code=201)
async def enviar_modelo_visual_peticao(
    arquivo: UploadFile = File(...),
    usuario: auth.Usuario = PodeManterModeloPeticao,
):
    """Substitui o timbre geral usado nos .docx de petição."""
    nome = arquivo.filename or "modelo-visual-geral.docx"
    if Path(nome).suffix.lower() != ".docx":
        raise HTTPException(400, "O modelo visual precisa ser um arquivo .docx.")
    conteudo = await arquivo.read()
    if not conteudo:
        raise HTTPException(400, "Arquivo vazio.")
    if len(conteudo) > MAX_BYTES:
        raise HTTPException(413, f"Arquivo maior que {MAX_BYTES // (1024 * 1024)}MB.")
    fonte = await run_in_threadpool(peticao_local.extrair_fonte_visual, conteudo)
    registro = await run_in_threadpool(
        armazenamento.salvar_modelo,
        peticao_local.MODELO_VISUAL_GERAL,
        nome_arquivo=nome,
        conteudo=conteudo,
        enviado_por=usuario.nome,
    )
    atributos = await run_in_threadpool(peticao_local.analisar_estilo, conteudo)
    atual = peticao_local.configuracao_visual()
    margens = atributos.get("margens_cm") or {}
    atual.update({
        "fonte": fonte,
        "tamanho_fonte_pt": atributos.get("tamanho_fonte_pt", atual["tamanho_fonte_pt"]),
        "espacamento_linha": atributos.get("espacamento_linha", atual["espacamento_linha"]),
        "alinhamento_corpo": {"justificado": "justificado", "à esquerda": "esquerda", "à direita": "direita"}.get(
            atributos.get("alinhamento"), atual["alinhamento_corpo"]
        ),
        "margem_superior_cm": margens.get("top", atual["margem_superior_cm"]),
        "margem_direita_cm": margens.get("right", atual["margem_direita_cm"]),
        "margem_inferior_cm": margens.get("bottom", atual["margem_inferior_cm"]),
        "margem_esquerda_cm": margens.get("left", atual["margem_esquerda_cm"]),
        "preferir_tabelas": bool((atributos.get("tabelas") or {}).get("quantidade")),
    })
    await run_in_threadpool(
        armazenamento.salvar_modelo,
        peticao_local.MODELO_VISUAL_CONFIG,
        nome_arquivo="configuracao-visual.json",
        conteudo=json.dumps(atual, ensure_ascii=False).encode("utf-8"),
        enviado_por=usuario.nome,
    )
    return {"arquivo": nome, "origem": "banco", "fonte": fonte, "atributos": atributos, **registro}


@roteador.delete("/api/modelos/peticao/visual")
async def excluir_modelo_visual_peticao(_autorizado=PodeManterModeloPeticao):
    await run_in_threadpool(
        armazenamento.excluir_modelo, peticao_local.MODELO_VISUAL_GERAL
    )
    return {"arquivo": "Padrão Lara & Melo", "origem": "embutido", "fonte": "Arial"}


# --------------------------------------- skill de redação por categoria de petição
#
# Instrução extra que o escritório dá para a IA redigir cada categoria (ação) de um
# jeito próprio — issue "Configurar skill por modelo de petição". Fica no Postgres
# do pgvector (`app/peticao_skills.py`), não no SQL Server: é insumo da geração por
# IA, e é lá que mora o resto do que alimenta o RAG. `PodeManterModeloPeticao` é o
# mesmo gate desta tela inteira — só quem administra modelos de petição edita.


class SkillPeticaoEntrada(BaseModel):
    instrucoes: str = Field(default="", max_length=8000)


@roteador.get("/api/modelos/peticao/skill")
async def obter_skill_de_peticao(_autorizado=PodeManterModeloPeticao):
    """A orientação ÚNICA do escritório, válida para qualquer peça.

    Era uma skill por categoria de ação. O escritório pediu o contrário: o que
    ele ensina sobre como redigir vale para a peça inteira, e dividir por ação
    obrigava a reescrever a mesma instrução cinco vezes — e a lembrar de
    atualizar as cinco quando o entendimento mudasse.
    """
    await run_in_threadpool(peticao_skills.inicializar)
    registro = await run_in_threadpool(
        peticao_skills.obter, peticao_skills.CATEGORIA_GERAL
    ) or {}
    return {
        "instrucoes": registro.get("instrucoes", ""),
        "atualizado_por": registro.get("atualizado_por", ""),
        "atualizado_em": registro.get("atualizado_em", ""),
    }


@roteador.put("/api/modelos/peticao/skill")
async def salvar_skill_de_peticao(
    corpo: SkillPeticaoEntrada,
    usuario: auth.Usuario = PodeManterModeloPeticao,
):
    """Grava a orientação geral. Sem categoria no caminho: ela não tem mais dono."""
    await run_in_threadpool(peticao_skills.inicializar)
    registro = await run_in_threadpool(
        peticao_skills.salvar,
        peticao_skills.CATEGORIA_GERAL,
        instrucoes=corpo.instrucoes.strip(),
        atualizado_por=usuario.nome,
    )
    return {
        "instrucoes": registro.get("instrucoes", ""),
        "atualizado_por": registro.get("atualizado_por", ""),
        "atualizado_em": registro.get("atualizado_em", ""),
    }


@roteador.get("/api/skills-juridicas")
async def listar_skills_juridicas(_usuario: auth.Usuario = Depends(auth.usuario_atual)):
    """Skills disponíveis para análise e redação de novos casos."""
    return await run_in_threadpool(skills_juridicas.listar)


@roteador.get("/api/skills-modulos")
async def listar_modulos_de_skill(_usuario: auth.Usuario = Depends(auth.usuario_atual)):
    """Skills instaladas e as adicionadas, para o módulo Skills."""
    return await run_in_threadpool(skills_juridicas.catalogo)


@roteador.get("/api/skills-modulos/{skill_id}")
async def obter_modulo_de_skill(skill_id: str, _usuario: auth.Usuario = Depends(auth.usuario_atual)):
    registro = await run_in_threadpool(skills_juridicas.detalhe, skill_id)
    if registro is None:
        raise HTTPException(404, "Skill não encontrada.")
    return registro


class _SkillNova(BaseModel):
    nome: str
    descricao: str = ""
    texto: str


@roteador.post("/api/skills-juridicas", status_code=201)
async def criar_skill_juridica(corpo: _SkillNova, _autorizado=PodeManterModeloPeticao):
    """Adiciona uma skill. Ela passa a aparecer como módulo próprio."""
    try:
        return await run_in_threadpool(skills_juridicas.criar, corpo.nome, corpo.descricao, corpo.texto)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@roteador.post("/api/skills-juridicas/importar", status_code=201)
async def importar_skill_juridica(
    arquivo: UploadFile = File(...),
    _autorizado=PodeManterModeloPeticao,
):
    """Importa uma skill ZIP sem executar nenhum arquivo do pacote."""
    if not (arquivo.filename or "").lower().endswith(".zip"):
        raise HTTPException(400, "Envie uma skill no formato .skill.zip.")
    try:
        conteudo = await _ler_upload(arquivo)
        return await run_in_threadpool(skills_juridicas.importar_zip, arquivo.filename or "skill", conteudo)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
