"""Análise e organização documental do caso, insights, jurimetria e diagnósticos."""

from __future__ import annotations

import os
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from .. import (
    analise_documental,
    analise_documentos,
    armazenamento,
    auth,
    case_brief_estado,
    jurimetria_caso,
    organizacao_documental,
    peticao_local,
    peticao_skill_arquivos,
    rag,
)
from .comum import _autor_da_acao

roteador = APIRouter()


@roteador.post("/api/casos/{caso_id}/analise-documentos")
def analisar_documentos_do_caso(caso_id: str):
    """O que os anexos dizem e a entrevista não registrou.

    Sob demanda, com botão, e não a cada upload: são vinte documentos num caso
    grande, e reanalisar a cada um pagaria vinte chamadas de modelo para
    responder a mesma pergunta. O advogado clica quando o checklist já está de
    pé, que é quando a resposta vale.

    Falta de chave e modelo mudo viram 503 com o que dá para fazer — os
    documentos continuam anexados e legíveis de qualquer forma.
    """
    if armazenamento.obter_caso(caso_id) is None:
        raise HTTPException(404, "Caso não encontrado.")
    try:
        analise = analise_documentos.analisar(caso_id)
        analise["relatorio_global"] = analise_documentos.relatorio_global(caso_id)
    except analise_documentos.ErroAnaliseDocumentos as exc:
        raise HTTPException(503, str(exc)) from exc
    # `fato_id` é o MESMO id que `case_brief.montar` atribui (mesma ordem, mesma
    # lista) — é por ele que a tela confirma/corrige/rejeita um achado em
    # `POST /api/casos/{caso_id}/insights/{fato_id}/estado`, e é por ele que a
    # próxima geração aplica a resposta do advogado em vez de perguntar de novo.
    try:
        estados = case_brief_estado.estados_do_caso(caso_id)
    except Exception:
        estados = {}
    for indice, achado in enumerate(analise.get("achados") or [], start=1):
        fato_id = f"fato-{indice}"
        achado["fato_id"] = fato_id
        if fato_id in estados:
            achado["estado"] = estados[fato_id]["estado"]
    for indice, evento in enumerate(analise.get("cronologia") or [], start=1):
        fato_id = f"evento-{indice}"
        evento["fato_id"] = fato_id
        if fato_id in estados:
            evento["estado"] = estados[fato_id]["estado"]
    return analise


class _EstadoInsightPayload(BaseModel):
    estado: str
    valor_corrigido: str = ""
    observacao: str = ""


# ------------------------------------------------------------ análise documental (skill documental)


def _caso_ou_404(caso_id: str) -> None:
    if armazenamento.obter_caso(caso_id) is None:
        raise HTTPException(404, "Caso não encontrado.")


@roteador.post("/api/casos/{caso_id}/analise-documental", status_code=202)
def iniciar_analise_documental(caso_id: str):
    """Dispara a análise pela skill documental (assíncrona: queued → processing → analyzing → ready|error)."""
    _caso_ou_404(caso_id)
    return analise_documental.iniciar(caso_id)


@roteador.get("/api/casos/{caso_id}/analise-documental")
def obter_analise_documental(caso_id: str):
    _caso_ou_404(caso_id)
    registro = analise_documental.obter(caso_id)
    if registro is None:
        return {"status": "none"}
    return registro


class _RespostaPerguntaPayload(BaseModel):
    resposta: str


@roteador.post("/api/casos/{caso_id}/analise-documental/perguntas/{pergunta_id}/resposta")
def responder_pergunta_documental(
    caso_id: str, pergunta_id: str, payload: _RespostaPerguntaPayload,
    usuario: auth.Usuario = Depends(auth.usuario_atual),
):
    _caso_ou_404(caso_id)
    try:
        analise_documental.responder(caso_id, pergunta_id, payload.resposta, _autor_da_acao(usuario))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True}


@roteador.post("/api/casos/{caso_id}/organizacao/plano")
def plano_de_organizacao(caso_id: str):
    """Monta o plano e PARA (gate da Etapa 4 da skill): nada é gerado até a confirmação."""
    _caso_ou_404(caso_id)
    try:
        return organizacao_documental.preparar(caso_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@roteador.get("/api/casos/{caso_id}/organizacao")
def organizacao_do_caso(caso_id: str):
    _caso_ou_404(caso_id)
    return analise_documental.armazenamento_padrao().organizacao(caso_id) or {"status": "none"}


@roteador.post("/api/casos/{caso_id}/organizacao/confirmar")
def confirmar_organizacao(caso_id: str, usuario: auth.Usuario = Depends(auth.usuario_atual)):
    _caso_ou_404(caso_id)
    try:
        return organizacao_documental.confirmar(caso_id, _autor_da_acao(usuario))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@roteador.post("/api/casos/{caso_id}/analise-documental/continuar")
def continuar_para_a_peca(caso_id: str):
    """O advogado revisou a análise: segue para a elaboração da peça (o contexto já está persistido)."""
    _caso_ou_404(caso_id)
    registro = analise_documental.obter(caso_id)
    if not registro or registro.get("status") != "ready":
        raise HTTPException(409, "A análise documental ainda não está pronta.")
    abertas = [p for p in (registro["resultado"].get("perguntas") or []) if not p.get("resposta")]
    return {"proximo": "peticao", "perguntas_sem_resposta": len(abertas),
            "contexto_da_peca": bool(analise_documental.contexto_para_peticao(caso_id))}


@roteador.post("/api/casos/{caso_id}/insights/{fato_id}/estado")
def definir_estado_insight(
    caso_id: str,
    fato_id: str,
    payload: _EstadoInsightPayload,
    usuario: auth.Usuario = Depends(auth.usuario_atual),
):
    """O advogado confirma, corrige ou rejeita um achado da análise.

    A partir daqui essa resposta vale para toda geração seguinte deste caso —
    ver `case_brief.montar`, que aplica o estado por cima da leitura crua dos
    documentos. Não pergunta de novo o que já foi respondido.
    """
    if armazenamento.obter_caso(caso_id) is None:
        raise HTTPException(404, "Caso não encontrado.")
    try:
        return case_brief_estado.definir_estado(
            caso_id,
            fato_id,
            payload.estado,
            valor_corrigido=payload.valor_corrigido,
            observacao=payload.observacao,
            usuario=_autor_da_acao(usuario),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@roteador.get("/api/diagnostico/pureza-da-skill")
def diagnostico_pureza_da_skill(
    categoria_nome: str = "", categoria_codigo: str = "", texto_caso: str = "",
    _usuario: auth.Usuario = Depends(auth.usuario_atual),
):
    """De onde vêm as instruções de uma geração: só a skill ativa, ou algo mais?"""
    return peticao_local.pureza_da_skill(categoria_nome, categoria_codigo, texto_caso)


@roteador.get("/api/diagnostico/geracao")
def diagnostico_da_geracao(
    caso_id: str = "", _usuario: auth.Usuario = Depends(auth.usuario_atual)
):
    """Prova, dentro do container que está no ar, o que a geração da petição enxerga.

    Roda as MESMAS dependências que `peticao_local.gerar` usa — skill de arquivo,
    embeddings, banco vetorial (peças, legislação, julgados) e o modelo da análise
    de documentos — e devolve o resultado de cada uma, com o erro quando falha.
    Sem isto, "o acervo não respondeu" era um aviso sem causa: chave sem crédito,
    banco vetorial fora de alcance e modelo recusando parâmetro pareciam iguais.
    Nunca devolve valor de variável de ambiente, só se está preenchida.
    """
    resultado: dict[str, Any] = {"versao": os.getenv("VERSION", "dev")}
    resultado["ambiente"] = {
        nome: bool(os.getenv(nome, "").strip())
        for nome in (
            "DATABASE_URL", "EMBEDDINGS_API_KEY", "OPENROUTER_API_KEY", "DEEPSEEK_API_KEY",
        )
    }
    resultado["modelos"] = {
        "redacao": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        "analise": os.getenv("OPENROUTER_MODELO_ANALISE", "").strip() or "google/gemini-3.7-flash",
        "embeddings": os.getenv("EMBEDDINGS_MODEL_NAME", "google/gemini-embedding-001"),
    }

    def _tentar(fn):
        inicio = time.monotonic()
        try:
            dados = fn()
            return {"ok": True, "segundos": round(time.monotonic() - inicio, 1), **dados}
        except Exception as erro:  # noqa: BLE001 - o objetivo é justamente ver o erro
            return {"ok": False, "segundos": round(time.monotonic() - inicio, 1),
                    "erro": f"{type(erro).__name__}: {str(erro)[:300]}"}

    nome, codigo = ("", "")
    if caso_id:
        nome, codigo = peticao_local._nome_e_codigo_da_categoria(caso_id)  # noqa: SLF001
    resultado["skill"] = _tentar(lambda: peticao_skill_arquivos.resumo(nome, codigo))
    consulta = "acidente de trabalho empregado dos Correios dano moral responsabilidade do empregador"
    resultado["acervo_pecas"] = _tentar(lambda: {
        "n": len(pecas := rag.buscar_pecas_conteudisticas(consulta, limite=8, assunto=peticao_skill_arquivos.resumo(nome, codigo)["assunto"])),
        "arquivos": [p["arquivo"] for p in pecas][:8],
        "mesmo_assunto": sum(1 for p in pecas if p.get("mesmo_assunto")),
    })
    resultado["legislacao"] = _tentar(lambda: {"n": len(rag.buscar_legislacao(consulta, limite=5))})
    if caso_id:
        resultado["analise_documentos"] = _tentar(lambda: {
            "achados": len((leitura := analise_documentos.analisar(caso_id)).get("achados") or []),
            "cronologia": len(leitura.get("cronologia") or []),
        })
    return resultado


@roteador.get("/api/casos/{caso_id}/jurimetria")
async def jurimetria_do_caso(caso_id: str, uf: str = ""):
    """Cruza os fatos do caso (entrevista + achados do OCR) com o acervo de decisões.

    `uf` foca a análise no TRT daquele estado — com fallback para os regionais da
    mesma região e, por fim, o acervo nacional. Entrega os precedentes semelhantes
    e a distribuição de desfechos POR VARA — o "seu caso × os números" num lugar só.
    Descritivo, não preditivo. Nunca dá 500: base fora do ar vira `disponivel:false`.
    """
    if armazenamento.obter_caso(caso_id) is None:
        raise HTTPException(404, "Caso não encontrado.")
    return await run_in_threadpool(lambda: jurimetria_caso.cruzar(caso_id, uf=uf))
