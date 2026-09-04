"""Pipeline Celery em etapas pequenas para documentos enviados ao caso."""

from __future__ import annotations

import hashlib
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from celery import chain
from prometheus_client import Counter, Histogram

from .. import (
    analise_documental,
    armazenamento,
    casos,
    categorias,
    documentos_juridicos,
    extracao_office,
    mistral_ocr,
    vinculos,
)
from ..celery_app import celery_app

log = logging.getLogger("pipeline-documentos")

ETAPAS_TOTAL = Counter(
    "forense_document_pipeline_stage_total",
    "Execucoes das etapas do pipeline documental.",
    ("etapa", "status"),
)
ETAPA_DURACAO = Histogram(
    "forense_document_pipeline_stage_duration_seconds",
    "Duracao de cada etapa do pipeline documental.",
    ("etapa",),
)


def _contexto(analise_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    analise = analise_documental.obter(analise_id)
    if not analise:
        raise RuntimeError(f"Análise documental {analise_id} não encontrada.")
    return analise, analise.get("contexto") or {}


def _checklist(contexto: dict[str, Any]) -> tuple[Any, list[dict[str, str]]]:
    categoria = categorias.obter(str(contexto.get("categoria_codigo") or ""))
    if categoria is None:
        raise RuntimeError("Categoria do caso não existe mais.")
    itens = [
        {"codigo": i.codigo, "nome": i.nome, "tipo_ocr": i.tipo_ocr or ""}
        for i in categoria.itens
    ]
    return categoria, itens


def _executar(analise_id: str, etapa: str, funcao, *, modelo: str | None = None) -> dict:
    analise_documental.iniciar_etapa(analise_id, etapa, modelo=modelo)
    inicio = time.perf_counter()
    try:
        with ETAPA_DURACAO.labels(etapa=etapa).time():
            resultado = funcao()
        analise_documental.concluir_etapa(
            analise_id,
            etapa,
            resultado,
            duracao_ms=round((time.perf_counter() - inicio) * 1000),
            modelo=modelo,
        )
        ETAPAS_TOTAL.labels(etapa=etapa, status="concluida").inc()
        return resultado
    except Exception as exc:
        ETAPAS_TOTAL.labels(etapa=etapa, status="falhou").inc()
        analise_documental.falhar_etapa(analise_id, etapa, str(exc))
        analise = analise_documental.obter(analise_id)
        if analise:
            armazenamento.falhar_entrega(analise["entrega_id"], str(exc))
        raise


def enfileirar_entrega(
    entrega_id: str,
    caso_id: str,
    *,
    item_codigo: str,
    categoria_codigo: str,
    idioma: str,
    usar_para_rg_e_cpf: bool,
) -> tuple[str, str]:
    entrega = armazenamento.obter_entrega(entrega_id)
    if not entrega:
        raise RuntimeError("Entrega recém-criada não foi encontrada.")
    analise = analise_documental.criar(
        entrega_id,
        caso_id,
        contexto={
            "item_codigo": item_codigo,
            "categoria_codigo": categoria_codigo,
            "idioma": idioma,
            "usar_para_rg_e_cpf": usar_para_rg_e_cpf,
            "arquivo": entrega.get("arquivo") or "documento",
        },
        hash_conteudo=entrega.get("conteudo_sha256"),
    )
    analise_id = str(analise["id"])
    fluxo = chain(
        # `mistral_ocr`, NÃO `gpu_background`. A fila do Paddle é servida por um
        # worker `--pool=solo --concurrency=1` por causa da afinidade de thread do
        # predictor nativo — restrição que a Mistral, sendo uma chamada HTTP, não
        # tem. Este `.set()` apontava para `gpu_background` e SOBRESCREVIA a rota
        # declarada em `celery_app.task_routes`, devolvendo a leitura ao teto de um
        # documento por vez: o worker `mistral` (6 threads) ficava ocioso enquanto
        # uma pasta com vinte arquivos era lida em fila indiana. Rota explícita e
        # `task_routes` precisam concordar — a explícita vence, e vencia errado.
        job_ocr_mistral.si(analise_id).set(queue="mistral_ocr", priority=7),
        job_classificar_documento.si(analise_id).set(queue="documents", priority=7),
        job_extrair_schema_especifico.si(analise_id).set(queue="documents", priority=7),
        job_validar_e_conciliar.si(analise_id).set(queue="documents", priority=7),
        job_extrair_evidencias.si(analise_id).set(queue="documents", priority=6),
        job_encaminhar_pos_validacao.si(analise_id).set(queue="documents", priority=5),
    )
    tarefa = fluxo.apply_async()
    return analise_id, tarefa.id


def enfileirar_reprocessamento(analise_id: str, desde: str = "classificar_documento") -> str:
    """Reexecuta regras/schemas com o OCR durável, sem cobrar a Mistral novamente."""
    ordem = [
        "classificar_documento",
        "extrair_schema_especifico",
        "validar_e_conciliar",
        "extrair_evidencias",
        "encaminhar_pos_validacao",
    ]
    if desde not in ordem[:-1]:
        raise ValueError("Etapa inválida para reprocessamento.")
    analise = analise_documental.reiniciar_desde(analise_id, desde)
    armazenamento.marcar_entrega_processando(analise["entrega_id"])
    tarefas = {
        "classificar_documento": job_classificar_documento,
        "extrair_schema_especifico": job_extrair_schema_especifico,
        "validar_e_conciliar": job_validar_e_conciliar,
        "extrair_evidencias": job_extrair_evidencias,
        "encaminhar_pos_validacao": job_encaminhar_pos_validacao,
    }
    inicio = ordem.index(desde)
    fluxo = chain(*[
        tarefas[nome].si(analise_id).set(queue="documents", priority=6)
        for nome in ordem[inicio:]
    ])
    return fluxo.apply_async().id


#: Falhas que valem uma segunda tentativa: rede, timeout e banco fora do ar. Um
#: erro de lógica (`ValueError` num campo torto) não entra aqui de propósito —
#: repetir não conserta e só atrasa a fila.
#:
#: Só o OCR tinha retry. As outras cinco etapas rodavam sem nenhum, então uma
#: oscilação do PostgreSQL no meio do `validar_e_conciliar` reprovava o documento
#: em definitivo, com a leitura paga da Mistral já feita e jogada fora. Como as
#: etapas seguintes leem o OCR salvo, repetir é barato: não recobra a Mistral.
FALHAS_TRANSITORIAS = (OSError, TimeoutError, httpx.HTTPError, ConnectionError)

RETENTATIVA = {
    "autoretry_for": FALHAS_TRANSITORIAS,
    "retry_backoff": True,
    "retry_backoff_max": 60,
    "retry_jitter": True,
    "retry_kwargs": {"max_retries": 3},
}


@celery_app.task(
    bind=True,
    name="app.tasks.pipeline_documentos.ocr_mistral",
    **RETENTATIVA,
)
def job_ocr_mistral(self, analise_id: str) -> dict:
    analise, contexto = _contexto(analise_id)
    modelo = os.getenv("MISTRAL_OCR_MODEL", "mistral-ocr-4-1")

    def rodar() -> dict:
        caminho = armazenamento.caminho_duravel_da_entrega(analise["entrega_id"])
        if caminho is None:
            raise RuntimeError("Arquivo original indisponível ou com checksum inválido.")
        conteudo = caminho.read_bytes()
        nome = str(contexto.get("arquivo") or caminho.name)
        extensao = Path(nome).suffix.lower()
        categoria, itens = _checklist(contexto)
        if extensao in extracao_office.EXTENSOES_TEXTO:
            texto = extracao_office.extrair_texto(conteudo, extensao)
            return {
                "modelo": "texto-digital",
                "schema_anotacao": None,
                "paginas": [{"numero": 1, "markdown": texto, "cabecalho": "", "rodape": "", "confianca": 1.0, "blocos": []}],
                "texto_completo": texto,
                "anotacao": {},
                "uso": {},
                "tempo_s": 0.0,
            }
        return mistral_ocr.ler_documento(
            conteudo,
            nome,
            categoria=categoria.nome,
            checklist=itens,
            anotar=True,
        )

    return _executar(analise_id, "ocr_mistral", rodar, modelo=modelo)


@celery_app.task(name="app.tasks.pipeline_documentos.classificar_documento", **RETENTATIVA)
def job_classificar_documento(analise_id: str) -> dict:
    ocr = analise_documental.resultado_etapa(analise_id, "ocr_mistral")
    return _executar(
        analise_id,
        "classificar_documento",
        lambda: documentos_juridicos.classificar(ocr),
        modelo="regras+mistral-annotation",
    )


@celery_app.task(name="app.tasks.pipeline_documentos.extrair_schema_especifico", **RETENTATIVA)
def job_extrair_schema_especifico(analise_id: str) -> dict:
    ocr = analise_documental.resultado_etapa(analise_id, "ocr_mistral")
    classificacao = analise_documental.resultado_etapa(analise_id, "classificar_documento")
    return _executar(
        analise_id,
        "extrair_schema_especifico",
        lambda: documentos_juridicos.extrair(ocr, classificacao),
        modelo="schema-juridico-v1",
    )


@celery_app.task(name="app.tasks.pipeline_documentos.validar_e_conciliar", **RETENTATIVA)
def job_validar_e_conciliar(analise_id: str) -> dict:
    analise, contexto = _contexto(analise_id)
    ocr = analise_documental.resultado_etapa(analise_id, "ocr_mistral")
    classificacao = analise_documental.resultado_etapa(analise_id, "classificar_documento")
    extracao = analise_documental.resultado_etapa(analise_id, "extrair_schema_especifico")
    _, itens = _checklist(contexto)
    caso = armazenamento.obter_caso(analise["caso_id"]) or {}
    item = str(contexto.get("item_codigo") or "")
    escolhido = None if item == categorias.ITEM_TRIAGEM else item

    def rodar() -> dict:
        resultado = documentos_juridicos.validar(
            ocr,
            classificacao,
            extracao,
            cliente=str(caso.get("cliente") or ""),
            checklist=itens,
            item_escolhido=escolhido,
        )
        # O documento raramente diz de quem a pessoa é parente — quem diz é a
        # entrevista ("meu filho Artur"). Só as pessoas que ficaram SEM vínculo
        # declarado vão para o cruzamento, e só se houver entrevista gravada:
        # sem nome pendente ou sem entrevista, `resolver_por_entrevista` devolve
        # vazio sem gastar chamada.
        pendentes = [
            str(p.get("nome") or "")
            for p in resultado.get("partes") or []
            if str(p.get("nome") or "").strip() and not str(p.get("relacao_com_cliente") or "").strip()
        ]
        if pendentes:
            achados = vinculos.resolver_por_entrevista(
                analise["caso_id"], str(caso.get("cliente") or ""), pendentes
            )
            resultado = vinculos.aplicar(resultado, achados)
        if contexto.get("usar_para_rg_e_cpf") and classificacao.get("tipo") in {"cin", "cnh"}:
            identidade = [
                i["codigo"] for i in itens if i.get("tipo_ocr") in {"rg", "cpf"}
            ]
            if len(identidade) == 2:
                resultado["itens_atendidos"] = identidade
                resultado["estados"]["atende_checklist"] = True
        return resultado

    return _executar(
        analise_id,
        "validar_e_conciliar",
        rodar,
        modelo="validadores-v1",
    )


def _campo_compatível(campo: dict[str, Any]) -> dict[str, Any]:
    """Traduz o campo extraído para o formato que a tela consome.

    `valido` diz respeito ao VALOR, não à citação. Antes desta função distinguir as
    duas coisas, todo campo saía "✓ válido / 100%" só por ter citação encontrada no
    OCR — ou seja, só porque o modelo não inventou o trecho. Um CPF com dígito
    trocado exibia o mesmo selo verde de um CPF correto, que é exatamente a
    informação que o advogado não pode receber errada.

    Agora são três estados: `True` passou no dígito verificador, `False` reprovou,
    `None` não tem regra nacional (nome, RG, endereço) e segue para conferência
    humana. A confiança acompanha: valor conferido vale 1.0; citação encontrada mas
    valor sem regra vale 0.75, que é o que ela realmente representa.
    """
    nome = documentos_juridicos.normalizar(str(campo.get("campo") or "dado")).lower().replace(" ", "_")
    citado = bool(campo.get("evidencia_verificada"))
    regra = campo.get("valido_regra")

    if regra is True:
        confianca, valido = 1.0, True
    elif regra is False:
        confianca, valido = 0.0, False
    else:
        confianca, valido = (0.75 if citado else 0.0), None

    procedencia = (
        f"Fonte: página {campo.get('pagina')}; citação conferida no OCR."
        if citado
        else "Sem citação conferida no OCR."
    )
    observacao_regra = str(campo.get("observacao_regra") or "")
    return {
        "nome": nome,
        "rotulo": str(campo.get("campo") or nome),
        "valor": str(campo.get("valor") or ""),
        "valor_bruto": str(campo.get("valor") or ""),
        "confianca": confianca,
        "valido": valido,
        "observacao": f"{observacao_regra} {procedencia}".strip(),
        "origem": str(campo.get("origem") or "mistral_annotation"),
        "citacao": campo.get("citacao"),
        "pagina": campo.get("pagina"),
    }


def _resultado_compativel(
    ocr: dict[str, Any],
    classificacao: dict[str, Any],
    extracao: dict[str, Any],
    validacao: dict[str, Any],
    evidencias: dict[str, Any],
) -> dict[str, Any]:
    # Com a revisão humana desligada na política do escritório, a ressalva não
    # segura mais o documento: ele fica utilizável e o item verde, exatamente o
    # que o botão da tela promete. A leitura continua guardada e a análise da LLM
    # é o que passa a valer.
    revisao = bool(validacao.get("revisao_necessaria")) and armazenamento.revisao_humana_obrigatoria()
    validacao_ui = {
        **validacao,
        "aprovado": validacao.get("veredito") == "APROVADO" and not revisao,
        # Enquanto há revisão, o checklist fica em "conferir". O texto segue
        # preservado em `texto_completo`, mas não cumpre automaticamente o item.
        "texto_disponivel": bool(validacao.get("texto_utilizavel")),
        "texto_utilizavel": bool(validacao.get("texto_utilizavel")) and not revisao,
        "dados_utilizaveis": bool(validacao.get("dados_utilizaveis")) and not revisao,
    }
    paginas = ocr.get("paginas") or []
    linhas = []
    for pagina in paginas:
        if pagina.get("blocos"):
            linhas.extend(
                {"texto": b.get("texto") or "", "confianca": b.get("confianca") or 0, "pagina": pagina.get("numero"), "bbox": b.get("bbox")}
                for b in pagina.get("blocos") or [] if str(b.get("texto") or "").strip()
            )
        else:
            linhas.extend(
                {"texto": linha.strip(), "confianca": pagina.get("confianca") or 0, "pagina": pagina.get("numero")}
                for linha in str(pagina.get("markdown") or "").splitlines() if linha.strip()
            )
    return {
        "id": hashlib.sha256(str(ocr.get("texto_completo") or "").encode()).hexdigest()[:32],
        "arquivo": "",
        "processado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tempo_processamento_s": round(sum(float(x or 0) for x in [ocr.get("tempo_s")]), 2),
        "tipo": {
            "codigo": classificacao["tipo"],
            "descricao": classificacao["rotulo"],
            "detectado": classificacao["tipo"],
            "descricao_detectado": classificacao["rotulo"],
            "confianca_classificacao": classificacao["confianca"],
            "pontuacoes": classificacao.get("pontuacoes") or {},
            "forcado_pelo_usuario": False,
        },
        "campos": [_campo_compatível(c) for c in extracao.get("campos") or []],
        "validacao": validacao_ui,
        "qualidade_imagem": {
            "score_legibilidade": validacao.get("score_legibilidade"),
            "legivel": validacao.get("estados", {}).get("arquivo_legivel"),
            "metricas": [],
            "problemas": validacao.get("motivos_revisao") or [],
            "sugestoes": [],
        },
        "ocr": {
            "motor": "Mistral Document AI",
            "modelo": ocr.get("modelo"),
            "idioma": "pt",
            "confianca_media": validacao.get("confianca_ocr"),
            "blocos_detectados": len(linhas),
            "caracteres_detectados": len(str(ocr.get("texto_completo") or "")),
            "paginas": len(paginas),
            "estrutura_preservada": True,
        },
        "texto_linhas": linhas,
        "texto_completo": ocr.get("texto_completo") or "",
        "paginas": paginas,
        "classificacao_semantica": {
            "tipo_semantico": classificacao["rotulo"],
            "documento": classificacao["rotulo"],
            "codigo_documento": classificacao["tipo"],
            "classificador": classificacao["fonte"],
            "pessoas": extracao.get("pessoas") or [],
            "organizacoes": extracao.get("organizacoes") or [],
            "achados": [
                {"campo": c.get("campo"), "valor": c.get("valor"), "citacao": c.get("citacao"), "pagina": c.get("pagina"), "importancia": "Dado localizado no documento.", "relevante_para": "Conferência e instrução do caso."}
                for c in extracao.get("campos") or []
            ],
            "serve_para": [
                {"item": codigo, "porque": "Item sustentado pela leitura estruturada e sujeito à validação."}
                for codigo in validacao.get("itens_atendidos") or []
            ],
            "atencao": validacao.get("avisos") or [],
            "evidencias": evidencias.get("evidencias") or [],
            "dados_sensiveis": evidencias.get("dados_sensiveis") or [],
        },
        "analise_documental": {
            "versao": analise_documental.VERSAO_PIPELINE,
            "estados": validacao.get("estados") or {},
            "revisao_necessaria": revisao,
        },
    }


@celery_app.task(name="app.tasks.pipeline_documentos.extrair_evidencias", **RETENTATIVA)
def job_extrair_evidencias(analise_id: str) -> dict:
    analise, contexto = _contexto(analise_id)
    ocr = analise_documental.resultado_etapa(analise_id, "ocr_mistral")
    classificacao = analise_documental.resultado_etapa(analise_id, "classificar_documento")
    extracao = analise_documental.resultado_etapa(analise_id, "extrair_schema_especifico")
    validacao = analise_documental.resultado_etapa(analise_id, "validar_e_conciliar")

    resultado = _executar(
        analise_id,
        "extrair_evidencias",
        lambda: documentos_juridicos.extrair_evidencias(ocr, extracao, validacao),
        modelo="evidencias-citadas-v1",
    )
    compat = _resultado_compativel(ocr, classificacao, extracao, validacao, resultado)
    compat["arquivo"] = str(contexto.get("arquivo") or "documento")
    itens = validacao.get("itens_atendidos") or []
    item_codigo = itens[0] if itens else categorias.ITEM_TRIAGEM
    item_cfg = None
    categoria, _ = _checklist(contexto)
    if itens:
        item_cfg = next((i for i in categoria.itens if i.codigo == itens[0]), None)
    tipo_confere = None
    if item_cfg is not None and item_cfg.tipo_ocr:
        tipo_confere = casos.tipo_confere(item_cfg, classificacao["tipo"], len(itens) > 1)
    # A ressalva só derruba o item para "conferir" quando a revisão humana é
    # obrigatória. Com a política desligada, o documento é aceito e a leitura da
    # LLM passa a valer — é o que o botão da tela promete: "verde e sob a LLM".
    if (
        validacao.get("revisao_necessaria")
        and item_cfg is not None
        and armazenamento.revisao_humana_obrigatoria()
    ):
        tipo_confere = False
    armazenamento.concluir_entrega(
        analise["entrega_id"],
        compat,
        tipo_confere,
        list(itens),
        item_codigo=item_codigo,
        origem="mistral",
        confianca=int(classificacao.get("confianca") or 0),
        motivo=(validacao.get("motivos_revisao") or [f"Reconhecido como {classificacao['rotulo']}."])[0],
    )
    return resultado


@celery_app.task(name="app.tasks.pipeline_documentos.encaminhar_pos_validacao", **RETENTATIVA)
def job_encaminhar_pos_validacao(analise_id: str) -> dict:
    validacao = analise_documental.resultado_etapa(analise_id, "validar_e_conciliar")
    # A revisão humana só barra o documento quando é política do escritório
    # (botão na tela). Desligada, mesmo o documento com ressalva segue direto
    # para o resumo — a leitura da LLM vale e o item fica verde.
    if validacao.get("revisao_necessaria") and armazenamento.revisao_humana_obrigatoria():
        tarefa = job_revisao_humana.apply_async((analise_id,), queue="documents", priority=5)
        return {"destino": "revisao_humana", "task_id": tarefa.id}
    tarefa = job_resumo_do_caso.apply_async((analise_id,), queue="documents", priority=5)
    return {"destino": "resumo_do_caso", "task_id": tarefa.id}


@celery_app.task(name="app.tasks.pipeline_documentos.revisao_humana")
def job_revisao_humana(analise_id: str) -> dict:
    validacao = analise_documental.resultado_etapa(analise_id, "validar_e_conciliar")
    motivos = validacao.get("motivos_revisao") or ["Conferência profissional necessária."]
    analise_documental.aguardar_revisao(analise_id, motivos)
    analise_documental.pular_etapa(analise_id, "resumo_do_caso", "Aguardando revisão humana.")
    ETAPAS_TOTAL.labels(etapa="revisao_humana", status="aguardando").inc()
    return {"status": "REVISAO_NECESSARIA", "motivos": motivos}


@celery_app.task(name="app.tasks.pipeline_documentos.resumo_do_caso", **RETENTATIVA)
def job_resumo_do_caso(analise_id: str) -> dict:
    classificacao = analise_documental.resultado_etapa(analise_id, "classificar_documento")
    extracao = analise_documental.resultado_etapa(analise_id, "extrair_schema_especifico")
    validacao = analise_documental.resultado_etapa(analise_id, "validar_e_conciliar")
    evidencias = analise_documental.resultado_etapa(analise_id, "extrair_evidencias")
    analise_documental.pular_etapa(analise_id, "revisao_humana", "Confiança suficiente; revisão não obrigatória.")
    resumo = _executar(
        analise_id,
        "resumo_do_caso",
        lambda: documentos_juridicos.resumo_documento(classificacao, extracao, validacao, evidencias),
        modelo="resumo-baseado-em-evidencias-v1",
    )
    analise_documental.concluir(analise_id, resumo)
    return resumo


def concluir_revisao(
    analise_id: str,
    *,
    itens: list[str],
    tipo_documento: str | None,
    aceito: bool,
    observacao: str,
    corrigido_por: str,
) -> dict[str, Any]:
    analise, _ = _contexto(analise_id)
    classificacao = analise_documental.resultado_etapa(analise_id, "classificar_documento")
    extracao = analise_documental.resultado_etapa(analise_id, "extrair_schema_especifico")
    validacao = analise_documental.resultado_etapa(analise_id, "validar_e_conciliar")
    evidencias = analise_documental.resultado_etapa(analise_id, "extrair_evidencias")
    anterior = classificacao.get("tipo")
    itens_anteriores = validacao.get("itens_atendidos") or []
    if tipo_documento:
        normalizado = documentos_juridicos.normalizar_tipo(tipo_documento)
        classificacao.update({
            "tipo": normalizado,
            "rotulo": documentos_juridicos.TIPOS[normalizado]["rotulo"],
            "confianca": 100,
            "fonte": "humano",
            "conflito": False,
        })
        analise_documental.registrar_feedback(
            analise_id, analise["entrega_id"], etapa="classificar_documento",
            campo="tipo_documento", valor_anterior=anterior,
            valor_correto=normalizado, motivo=observacao,
            corrigido_por=corrigido_por,
        )
    if list(itens) != list(itens_anteriores):
        analise_documental.registrar_feedback(
            analise_id, analise["entrega_id"], etapa="validar_e_conciliar",
            campo="itens_atendidos", valor_anterior=itens_anteriores,
            valor_correto=itens, motivo=observacao,
            corrigido_por=corrigido_por,
        )
    validacao.update({
        "revisao_necessaria": False,
        "motivos_revisao": [],
        "itens_atendidos": list(dict.fromkeys(itens)),
        "dados_utilizaveis": bool(aceito),
        "texto_utilizavel": bool(aceito),
        "veredito": "APROVADO" if aceito else "REPROVADO",
        "resumo": "Análise conferida manualmente pelo escritório.",
    })
    validacao.setdefault("estados", {}).update({
        "tipo_confirmado": bool(aceito),
        "campos_validados": bool(aceito),
        "atende_checklist": bool(aceito and itens),
    })
    ocr = analise_documental.resultado_etapa(analise_id, "ocr_mistral")
    compat = _resultado_compativel(ocr, classificacao, extracao, validacao, evidencias)
    compat["arquivo"] = analise.get("contexto", {}).get("arquivo") or "documento"
    armazenamento.concluir_entrega(
        analise["entrega_id"], compat, True if aceito else False,
        itens if aceito else [], item_codigo=itens[0] if itens else categorias.ITEM_TRIAGEM,
        origem="humano", confianca=100,
        motivo=f"Revisado por {corrigido_por}. {observacao}"[:600],
    )
    analise_documental.iniciar_etapa(analise_id, "revisao_humana", modelo="humano")
    analise_documental.concluir_etapa(
        analise_id, "revisao_humana",
        {"aceito": aceito, "itens": itens, "tipo_documento": classificacao["tipo"], "observacao": observacao},
        duracao_ms=0, modelo="humano",
    )
    resumo = documentos_juridicos.resumo_documento(classificacao, extracao, validacao, evidencias)
    analise_documental.iniciar_etapa(analise_id, "resumo_do_caso", modelo="resumo-baseado-em-evidencias-v1")
    analise_documental.concluir_etapa(
        analise_id, "resumo_do_caso", resumo, duracao_ms=0,
        modelo="resumo-baseado-em-evidencias-v1",
    )
    analise_documental.concluir(analise_id, resumo)
    return analise_documental.obter(analise_id) or {}
