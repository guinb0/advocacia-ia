"""Análise jurídica pós-entrevista: que ações cabem, com que fundamento.

O QUE ENTRA

- a transcrição da conversa e as respostas do roteiro (o que o cliente disse);
- os documentos já mostrados no atendimento;
- o catálogo de tipos de caso com os critérios de cada um (`criterios_caso`);
- as autoridades que o acervo recuperou para o relato (lei e precedente verificados).

O QUE SAI

Sugestões de ações do catálogo (com os critérios atendidos e pendentes) e, quando
o relato não cabe em nenhuma, "novas ações" — que o advogado pode aceitar, e aí
viram tipo de caso marcado "Gerado por IA — requer revisão".

POR QUE O FUNDAMENTO É CONFERIDO

O modelo só pode citar autoridade que veio da recuperação, pelo `authority_id`.
Fundamento com id fora dessa lista é descartado (e contado): número de artigo
inventado não chega à tela do advogado com cara de pesquisa feita.

A análise roda no Celery (fila `ai`). Se o broker não responder, roda numa
thread da própria API — mais lento para a requisição, mas o atendimento não
trava esperando uma fila que não existe. Falhou a IA, a análise ainda conclui
com as sugestões da triagem local e o erro à vista: quem decide é o advogado.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from . import atendimentos as at
from . import banco
from .banco import PREFIXO, SCHEMA
from .esquema_portavel import Coluna, Tabela, criar as criar_tabelas

log = logging.getLogger("analise_acoes")

TABELA = f"{SCHEMA}.{PREFIXO}analises_atendimento"
PENDENTE, PROCESSANDO, CONCLUIDA, FALHOU = "pendente", "processando", "concluida", "falhou"
#: Análise "processando" há mais que isto morreu com o worker.
MINUTOS_TRAVADA = 12
#: Na fila há mais que isto sem worker pegar: a própria API assume.
SEGUNDOS_NA_FILA = 30
LIMITE_TRANSCRICAO = 16000
TIMEOUT_LLM = 150

TABELAS = (
    Tabela(
        TABELA,
        (
            Coluna("id", "id", nula=False),
            Coluna("atendimento_id", "id", nula=False),
            Coluna("status", "codigo", nula=False, padrao=PENDENTE),
            Coluna("assinatura", "varchar(64)", nula=False),
            Coluna("entrada_json", "longo"),
            Coluna("resultado_json", "longo"),
            Coluna("erro", "texto"),
            Coluna("criado_em", "data", nula=False),
            Coluna("atualizado_em", "data", nula=False),
            Coluna("criado_por", "curto"),
        ),
        ("id",),
        indices=(("ix_acervo_analises_atend", ("atendimento_id", "criado_em")),),
    ),
)


def inicializar() -> None:
    with banco.conectar() as con:
        criar_tabelas(con, TABELAS)


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _registro(linha: Any) -> dict[str, Any]:
    r = dict(zip(linha.keys(), linha))
    r["entrada"] = json.loads(r.pop("entrada_json") or "{}")
    r["resultado"] = json.loads(r.pop("resultado_json") or "null")
    return r


def normalizar_entrada(entrada: dict[str, Any]) -> dict[str, Any]:
    respostas = entrada.get("respostas") or {}
    return {
        "transcricao": str(entrada.get("transcricao") or "")[-LIMITE_TRANSCRICAO * 2:],
        "relato": str(entrada.get("relato") or "")[:LIMITE_TRANSCRICAO],
        "respostas": {
            str(k)[:120]: (v if isinstance(v, str) else ", ".join(map(str, v)) if isinstance(v, list) else str(v))[:1500]
            for k, v in list(respostas.items())[:300]
        } if isinstance(respostas, dict) else {},
        "perguntas": {
            str(k)[:120]: str(v)[:300] for k, v in list((entrada.get("perguntas") or {}).items())[:300]
        } if isinstance(entrada.get("perguntas"), dict) else {},
        "documentos": [str(d)[:160] for d in (entrada.get("documentos") or [])][:60],
        "triagem_ao_vivo": entrada.get("triagem_ao_vivo") if isinstance(entrada.get("triagem_ao_vivo"), dict) else None,
    }


def assinatura(entrada: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(entrada, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def ultima(atendimento_id: str) -> dict[str, Any] | None:
    with banco.conectar() as con:
        linhas = con.execute(
            f"SELECT * FROM {TABELA} WHERE atendimento_id = ? ORDER BY criado_em DESC",
            (atendimento_id,),
        ).fetchall()
    if not linhas:
        return None
    registro = _registro(linhas[0])
    if registro["status"] in (PENDENTE, PROCESSANDO):
        parada = datetime.now(timezone.utc) - (at.ler_data(registro["atualizado_em"]) or datetime.now(timezone.utc))
        if parada > timedelta(minutes=MINUTOS_TRAVADA):
            _concluir_com_falha(registro, "A análise não respondeu a tempo (worker reiniciado?).")
            return ultima(atendimento_id)
        if registro["status"] == PENDENTE and parada > timedelta(seconds=SEGUNDOS_NA_FILA):
            # A fila `ai` divide o worker com documentos longos: quem está com o
            # cliente na sala não espera a vez dela. A trava em `executar` garante
            # uma execução só, venha da fila ou daqui.
            _rodar_na_api(registro["id"])
    return registro


def obter(analise_id: str) -> dict[str, Any] | None:
    with banco.conectar() as con:
        linha = con.execute(f"SELECT * FROM {TABELA} WHERE id = ?", (analise_id,)).fetchone()
    return _registro(linha) if linha else None


def iniciar(atendimento_id: str, entrada: dict[str, Any], *, usuario: str = "",
            refazer: bool = False) -> dict[str, Any]:
    """Começa (ou reaproveita) a análise do atendimento. Idempotente pela entrada."""
    registro = at.exigir(atendimento_id)
    if registro["estado"] == at.AGUARDANDO_CONFIRMACAO_ACOES and refazer:
        registro = at.transicionar(atendimento_id, at.ANALISE_JURIDICA,
                                   de={at.AGUARDANDO_CONFIRMACAO_ACOES},
                                   usuario_nome=usuario, detalhes="análise refeita")
    if registro["estado"] != at.ANALISE_JURIDICA:
        existente = ultima(atendimento_id)
        if existente is not None:
            return existente
        raise at.TransicaoInvalida(
            f"O atendimento está em {registro['estado']}: a análise roda depois da entrevista."
        )
    normalizada = normalizar_entrada(entrada)
    marca = assinatura(normalizada)
    existente = ultima(atendimento_id)
    if (
        existente is not None
        and existente["assinatura"] == marca
        and existente["status"] in (PENDENTE, PROCESSANDO, CONCLUIDA)
        and not refazer
    ):
        if existente["status"] == CONCLUIDA:
            _liberar_confirmacao(atendimento_id, existente)
        return existente
    novo_id = uuid.uuid4().hex
    instante = _agora()
    with banco.conectar() as con:
        con.execute(
            f"""INSERT INTO {TABELA}
                (id, atendimento_id, status, assinatura, entrada_json, criado_em, atualizado_em, criado_por)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (novo_id, atendimento_id, PENDENTE, marca,
             json.dumps(normalizada, ensure_ascii=False), instante, instante, usuario[:200] or None),
        )
    _enfileirar(novo_id)
    return obter(novo_id) or {}


_em_execucao_local: set[str] = set()
_trava_local = threading.Lock()


def _rodar_na_api(analise_id: str) -> None:
    with _trava_local:
        if analise_id in _em_execucao_local:
            return
        _em_execucao_local.add(analise_id)

    def rodar() -> None:
        try:
            executar(analise_id)
        finally:
            with _trava_local:
                _em_execucao_local.discard(analise_id)

    threading.Thread(target=rodar, name=f"analise-{analise_id[:8]}", daemon=True).start()


def _enfileirar(analise_id: str) -> None:
    try:
        from .tasks.ia import analisar_atendimento

        analisar_atendimento.apply_async(args=(analise_id,), queue="ai", priority=3)
        return
    except Exception:  # noqa: BLE001 - sem broker, a análise ainda precisa acontecer
        log.warning("Celery indisponível; análise %s roda na API.", analise_id, exc_info=True)
    _rodar_na_api(analise_id)


def _marcar(analise_id: str, status: str, *, de: tuple[str, ...], resultado: Any = None,
            erro: str | None = None) -> bool:
    marcadores = ",".join("?" for _ in de)
    sets, params = ["status = ?", "atualizado_em = ?"], [status, _agora()]
    if resultado is not None:
        sets.append("resultado_json = ?")
        params.append(json.dumps(resultado, ensure_ascii=False))
    if erro is not None:
        sets.append("erro = ?")
        params.append(erro[:1000])
    with banco.conectar() as con:
        return bool(con.execute(
            f"UPDATE {TABELA} SET {', '.join(sets)} WHERE id = ? AND status IN ({marcadores})",
            (*params, analise_id, *de),
        ).rowcount)


def _liberar_confirmacao(atendimento_id: str, analise: dict[str, Any]) -> None:
    try:
        at.transicionar(
            atendimento_id, at.AGUARDANDO_CONFIRMACAO_ACOES, de={at.ANALISE_JURIDICA},
            detalhes=f"análise {analise['id'][:8]} {analise['status']}",
        )
    except at.TransicaoInvalida:
        pass


def _concluir_com_falha(analise: dict[str, Any], motivo: str) -> None:
    resultado = resultado_de_reserva(analise.get("entrada") or {}, motivo)
    if _marcar(analise["id"], FALHOU, de=(PENDENTE, PROCESSANDO), resultado=resultado, erro=motivo):
        _liberar_confirmacao(analise["atendimento_id"], {**analise, "status": FALHOU})


def executar(analise_id: str, *, chamar_llm=None, recuperar=None) -> dict[str, Any] | None:
    """Roda a análise. `chamar_llm`/`recuperar` existem para os testes."""
    analise = obter(analise_id)
    if analise is None or not _marcar(analise_id, PROCESSANDO, de=(PENDENTE,)):
        return analise
    entrada = analise["entrada"]
    try:
        resultado = analisar(entrada, chamar_llm=chamar_llm, recuperar=recuperar)
    except Exception as erro:  # noqa: BLE001
        log.exception("Análise %s falhou.", analise_id)
        _concluir_com_falha({**analise, "status": PROCESSANDO}, f"{type(erro).__name__}: {str(erro)[:300]}")
        return obter(analise_id)
    if _marcar(analise_id, CONCLUIDA, de=(PROCESSANDO,), resultado=resultado):
        _liberar_confirmacao(analise["atendimento_id"], {**analise, "status": CONCLUIDA})
    return obter(analise_id)


# --------------------------------------------------------------- a análise


def texto_do_atendimento(entrada: dict[str, Any]) -> str:
    perguntas = entrada.get("perguntas") or {}
    linhas = [
        f"- {perguntas.get(k, k)}: {v}" for k, v in (entrada.get("respostas") or {}).items() if str(v).strip()
    ]
    partes = []
    if linhas:
        partes.append("RESPOSTAS DO ROTEIRO\n" + "\n".join(linhas))
    if entrada.get("documentos"):
        partes.append("DOCUMENTOS MOSTRADOS NO ATENDIMENTO\n" + "\n".join(f"- {d}" for d in entrada["documentos"]))
    corpo = entrada.get("transcricao") or entrada.get("relato") or ""
    if corpo:
        partes.append("TRANSCRIÇÃO DA CONVERSA\n" + corpo[-LIMITE_TRANSCRICAO:])
    return "\n\n".join(partes)


def catalogo_para_analise() -> list[dict[str, Any]]:
    from . import categorias, criterios_caso

    tipos = [c for c in categorias.listar() if c.codigo != categorias.CATEGORIA_EM_TRIAGEM.codigo]
    criterios = criterios_caso.por_tipos([c.codigo for c in tipos])
    try:
        from . import tipos_caso

        quando = {t["codigo"]: t["quando_usar"] for t in tipos_caso.listar()}
    except Exception:  # noqa: BLE001
        quando = {}
    return [
        {
            "codigo": c.codigo,
            "nome": c.nome,
            "descricao": c.descricao,
            "quando_usar": quando.get(c.codigo, ""),
            "criterios": criterios.get(c.codigo, []),
            "documentos_minimos": [i.nome for i in c.itens if i.obrigatorio],
        }
        for c in tipos
    ]


def recuperar_autoridades(texto: str, sugestoes_triagem: list[str]) -> tuple[list[Any], list[str]]:
    """Lei e precedente verificados para o relato. Falha vira lista vazia + erro."""
    from . import recuperacao_por_tese
    from .juridico import autoridades

    ancora = " ".join(texto.split())[:500]
    consultas = [{"tese": "(visão geral do caso)", "consulta": ancora}]
    for nome in sugestoes_triagem[:3]:
        consultas.append({"tese": nome, "consulta": f"{nome}. {ancora[:300]}"})
    erros: list[str] = []
    lista: list[Any] = []
    try:
        leis, _prov, erros_lei = recuperacao_por_tese.legislacao(consultas, por_tese=3, total=10)
        erros += erros_lei
        lista += autoridades.de_trechos_de_legislacao(leis)
    except Exception as erro:  # noqa: BLE001
        erros.append(f"legislação: {type(erro).__name__}")
    try:
        precs, _prov, erros_prec = recuperacao_por_tese.precedentes(consultas, texto[:4000], por_tese=3, total=8)
        erros += erros_prec
        lista += autoridades.de_trechos_de_precedentes(precs)
    except Exception as erro:  # noqa: BLE001
        erros.append(f"precedentes: {type(erro).__name__}")
    vistos: set[str] = set()
    unicas = []
    for a in lista:
        if a.id not in vistos:
            vistos.add(a.id)
            unicas.append(a)
    return unicas[:30], erros


INSTRUCAO = """Você é advogado(a) sênior de um escritório trabalhista e previdenciário.
Leia o atendimento e diga QUE AÇÕES cabem para este cliente.

Regras:
1. Use somente fatos do atendimento. Nada de supor fato não dito.
2. Para cada ação do CATÁLOGO que cabe, confira os critérios dela um a um: diga
   quais o relato atende e quais ainda faltam confirmar.
3. Pode haver mais de uma ação (ex.: doença ocupacional E acidente).
4. Se o relato indicar uma ação que o catálogo NÃO tem, descreva-a em "novas_acoes"
   com critérios, documentos (marque "minimo": true no que é indispensável para
   ajuizar) e informações que precisam ser colhidas.
5. Fundamento jurídico: cite APENAS autoridades da BASE JURÍDICA VERIFICADA, pelo
   authority_id entre colchetes. Sem autoridade adequada, deixe "fundamentos" vazio.
6. Responda SOMENTE com JSON neste formato:
{"sugestoes":[{"tipo_codigo":"","confianca":0.0,"justificativa":"","criterios_atendidos":[],"criterios_pendentes":[],"fundamentos":[{"authority_id":"","motivo":""}],"documentos_minimos_faltantes":[]}],
 "novas_acoes":[{"nome":"","descricao":"","justificativa":"","criterios":[],"documentos":[{"nome":"","minimo":true}],"informacoes_necessarias":[],"fundamentos":[{"authority_id":"","motivo":""}]}],
 "observacoes":""}"""


def _montar_prompt(texto: str, catalogo: list[dict[str, Any]], bloco_autoridades: str) -> str:
    linhas = ["CATÁLOGO DE AÇÕES DO ESCRITÓRIO"]
    for tipo in catalogo:
        linhas.append(f"- {tipo['codigo']} — {tipo['nome']}")
        if tipo["quando_usar"] or tipo["descricao"]:
            linhas.append(f"  Quando usar: {(tipo['quando_usar'] or tipo['descricao'])[:400]}")
        for c in tipo["criterios"][:15]:
            linhas.append(f"  • critério: {c}")
        if tipo["documentos_minimos"]:
            linhas.append(f"  Documentos mínimos: {', '.join(tipo['documentos_minimos'][:15])}")
    return "\n".join(linhas) + "\n\n" + bloco_autoridades + "\n\n" + texto


def chamar_llm_padrao(instrucao: str, conteudo: str) -> dict[str, Any]:
    import httpx

    from . import triagem

    chave = triagem._chave_llm()
    if not chave:
        raise RuntimeError("Modelo de linguagem não configurado (DEEPSEEK_API_KEY).")
    resposta = httpx.post(
        triagem.URL_LLM,
        headers={"Authorization": f"Bearer {chave}", "Content-Type": "application/json"},
        json={
            "model": triagem.MODELO_LLM,
            "messages": [{"role": "system", "content": instrucao}, {"role": "user", "content": conteudo}],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        },
        timeout=TIMEOUT_LLM,
    )
    resposta.raise_for_status()
    return json.loads(resposta.json()["choices"][0]["message"]["content"])


def _lista_de_textos(valor: Any, limite: int = 15, tamanho: int = 300) -> list[str]:
    if not isinstance(valor, list):
        return []
    return [" ".join(str(v).split())[:tamanho] for v in valor if str(v).strip()][:limite]


def validar_fundamentos(brutos: Any, permitidas: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    validos, descartados = [], 0
    for f in brutos if isinstance(brutos, list) else []:
        if not isinstance(f, dict):
            descartados += 1
            continue
        aid = str(f.get("authority_id") or "").strip().strip("[]")
        autoridade = permitidas.get(aid)
        if autoridade is None:
            descartados += 1
            continue
        validos.append({
            "authority_id": aid,
            "titulo": getattr(autoridade, "titulo", "") or getattr(autoridade, "chave", ""),
            "tipo": getattr(autoridade, "tipo", ""),
            "url": getattr(autoridade, "url", ""),
            "verificada": bool(getattr(autoridade, "verificada", False)),
            "motivo": " ".join(str(f.get("motivo") or "").split())[:400],
        })
    return validos[:8], descartados


def validar_resultado(
    bruto: dict[str, Any], catalogo: list[dict[str, Any]], autoridades_lista: list[Any],
    triagem_local: dict[str, Any] | None,
) -> dict[str, Any]:
    """Só o que dá para conferir sai daqui: código do catálogo, fundamento recuperado."""
    nomes = {t["codigo"]: t["nome"] for t in catalogo}
    permitidas = {a.id: a for a in autoridades_lista}
    descartados = 0
    sugestoes: list[dict[str, Any]] = []
    vistos: set[str] = set()
    for s in bruto.get("sugestoes") or []:
        if not isinstance(s, dict):
            continue
        codigo = str(s.get("tipo_codigo") or "").strip()
        if codigo not in nomes or codigo in vistos:
            continue
        vistos.add(codigo)
        fundamentos, fora = validar_fundamentos(s.get("fundamentos"), permitidas)
        descartados += fora
        try:
            confianca = max(0.0, min(1.0, float(s.get("confianca") or 0)))
        except (TypeError, ValueError):
            confianca = 0.0
        sugestoes.append({
            "tipo_codigo": codigo,
            "nome": nomes[codigo],
            "confianca": round(confianca, 3),
            "justificativa": " ".join(str(s.get("justificativa") or "").split())[:1200],
            "criterios_atendidos": _lista_de_textos(s.get("criterios_atendidos")),
            "criterios_pendentes": _lista_de_textos(s.get("criterios_pendentes")),
            "documentos_minimos_faltantes": _lista_de_textos(s.get("documentos_minimos_faltantes")),
            "fundamentos": fundamentos,
            "origem": "ia",
        })
    novas: list[dict[str, Any]] = []
    nomes_normalizados = {n.casefold() for n in nomes.values()}
    for n in bruto.get("novas_acoes") or []:
        if not isinstance(n, dict):
            continue
        nome = " ".join(str(n.get("nome") or "").split())[:120]
        if len(nome) < 3 or nome.casefold() in nomes_normalizados:
            continue
        fundamentos, fora = validar_fundamentos(n.get("fundamentos"), permitidas)
        descartados += fora
        documentos = [
            {"nome": " ".join(str(d.get("nome") or "").split())[:160], "minimo": bool(d.get("minimo"))}
            for d in (n.get("documentos") or []) if isinstance(d, dict) and str(d.get("nome") or "").strip()
        ][:30]
        novas.append({
            "id": hashlib.sha1(nome.casefold().encode("utf-8")).hexdigest()[:12],
            "nome": nome,
            "descricao": " ".join(str(n.get("descricao") or "").split())[:600],
            "justificativa": " ".join(str(n.get("justificativa") or "").split())[:1200],
            "criterios": _lista_de_textos(n.get("criterios"), 20, 400),
            "documentos": documentos,
            "informacoes_necessarias": _lista_de_textos(n.get("informacoes_necessarias"), 20),
            "fundamentos": fundamentos,
        })
    resultado = {
        "sugestoes": sorted(sugestoes, key=lambda s: -s["confianca"]),
        "novas_acoes": novas[:5],
        "observacoes": " ".join(str(bruto.get("observacoes") or "").split())[:1500],
        "fundamentos_descartados": descartados,
    }
    return conferir_com_triagem(resultado, triagem_local, nomes)


def conferir_com_triagem(resultado: dict[str, Any], triagem_local: dict[str, Any] | None,
                         nomes: dict[str, str]) -> dict[str, Any]:
    """A triagem por termos é independente do modelo: discordar é sinal de dúvida."""
    sugestoes_triagem = [s.get("codigo") for s in (triagem_local or {}).get("sugestoes") or []]
    principal = sugestoes_triagem[0] if sugestoes_triagem else None
    codigos = {s["tipo_codigo"] for s in resultado["sugestoes"]}
    for s in resultado["sugestoes"]:
        s["triagem_concorda"] = s["tipo_codigo"] in sugestoes_triagem[:3]
    resultado["triagem"] = {
        "principal": principal,
        "divergiu": bool(principal and resultado["sugestoes"] and principal != resultado["sugestoes"][0]["tipo_codigo"]),
    }
    if principal and principal in nomes and principal not in codigos:
        resultado["sugestoes"].append({
            "tipo_codigo": principal, "nome": nomes[principal], "confianca": 0.0,
            "justificativa": "Apontada pela triagem por termos, mas não pela análise — confira.",
            "criterios_atendidos": [], "criterios_pendentes": [], "documentos_minimos_faltantes": [],
            "fundamentos": [], "origem": "triagem", "triagem_concorda": True,
        })
    return resultado


def resultado_de_reserva(entrada: dict[str, Any], motivo: str) -> dict[str, Any]:
    """Sem IA: as sugestões da triagem local, para o advogado escolher à mão."""
    from . import categorias, triagem

    try:
        local = triagem.classificar_entrevista(texto_do_atendimento(entrada))
    except Exception:  # noqa: BLE001
        local = {"sugestoes": []}
    nomes = {c.codigo: c.nome for c in categorias.listar()}
    sugestoes = [
        {
            "tipo_codigo": s["codigo"], "nome": nomes.get(s["codigo"], s.get("nome", s["codigo"])),
            "confianca": round(float(s.get("confianca") or 0), 3),
            "justificativa": "; ".join(s.get("evidencias") or [])[:600] or "Sugerida pela triagem por termos.",
            "criterios_atendidos": [], "criterios_pendentes": [], "documentos_minimos_faltantes": [],
            "fundamentos": [], "origem": "triagem", "triagem_concorda": True,
        }
        for s in (local.get("sugestoes") or [])[:3]
        if s.get("codigo") in nomes
    ]
    return {
        "sugestoes": sugestoes, "novas_acoes": [], "fundamentos_descartados": 0,
        "observacoes": f"A análise por IA não concluiu ({motivo}). Sugestões da triagem por termos.",
        "triagem": {"principal": sugestoes[0]["tipo_codigo"] if sugestoes else None, "divergiu": False},
        "reserva": True,
    }


def analisar(entrada: dict[str, Any], *, chamar_llm=None, recuperar=None) -> dict[str, Any]:
    from . import triagem
    from .juridico import autoridades

    texto = texto_do_atendimento(entrada)
    if not texto.strip():
        return resultado_de_reserva(entrada, "atendimento sem transcrição nem respostas")
    try:
        triagem_local = triagem.classificar_entrevista(texto)
    except Exception:  # noqa: BLE001
        triagem_local = None
    catalogo = catalogo_para_analise()
    nomes_triagem = [s.get("nome", "") for s in (triagem_local or {}).get("sugestoes") or []]
    autoridades_lista, erros = (recuperar or recuperar_autoridades)(texto, nomes_triagem)
    bloco = autoridades.bloco_para_prompt(autoridades_lista) if autoridades_lista else (
        "=== BASE JURÍDICA VERIFICADA ===\n(nenhuma autoridade recuperada: deixe 'fundamentos' vazio)"
    )
    bruto = (chamar_llm or chamar_llm_padrao)(INSTRUCAO, _montar_prompt(texto, catalogo, bloco))
    resultado = validar_resultado(bruto if isinstance(bruto, dict) else {}, catalogo, autoridades_lista, triagem_local)
    resultado["autoridades_consultadas"] = len(autoridades_lista)
    resultado["erros_recuperacao"] = erros[:10]
    return resultado
