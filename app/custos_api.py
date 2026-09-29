"""Telemetria de chamadas pagas, sem registrar conteúdo ou credenciais."""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from .banco import conectar

log = logging.getLogger("custos-api")


def _numero(valor: Any) -> int:
    try:
        return max(0, int(valor or 0))
    except (TypeError, ValueError):
        return 0


def _custo_usd(uso: dict[str, Any]) -> Decimal | None:
    """Extrai o custo efetivo quando o provedor o informa na resposta."""
    valor = uso.get("cost")
    if valor is None:
        return None
    try:
        custo = Decimal(str(valor))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return custo if custo >= 0 else None


def registrar(fornecedor: str, modelo: str, operacao: str, resposta: Any, *, latencia_ms: int | None = None) -> None:
    """Persiste consumo sem deixar uma falha de telemetria afetar a chamada paga."""
    try:
        uso = resposta.json().get("usage") or {}
    except Exception:
        uso = {}
    entrada = _numero(uso.get("prompt_tokens", uso.get("input_tokens", 0)))
    saida = _numero(uso.get("completion_tokens", uso.get("output_tokens", 0)))
    total = _numero(uso.get("total_tokens")) or entrada + saida
    custo = _custo_usd(uso)
    log.info(
        "api_usage fornecedor=%s modelo=%s operacao=%s input_tokens=%s output_tokens=%s total_tokens=%s custo_usd=%s",
        fornecedor, modelo, operacao, entrada, saida, total, custo,
    )
    try:
        with conectar(timeout=3) as con:
            con.execute(
                "INSERT INTO custos_api "
                "(id, criado_em, fornecedor, modelo, operacao, input_tokens, output_tokens, "
                "total_tokens, custo_usd, custo_estimado, status, erro, latencia_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    str(fornecedor)[:64], str(modelo)[:200], str(operacao)[:100],
                    entrada, saida, total, custo, 0, "SUCCESS", None, latencia_ms,
                ),
            )
    except Exception:
        # Observabilidade não pode parar OCR, triagem ou criação de caso.
        log.warning("Não foi possível persistir a telemetria de custo.", exc_info=True)


def registrar_falha(fornecedor: str, modelo: str, operacao: str, erro: Exception | str, *, latencia_ms: int | None = None) -> None:
    """Registra recusa, timeout ou erro de rede sem conteúdo da requisição."""
    try:
        with conectar(timeout=3) as con:
            con.execute(
                "INSERT INTO custos_api (id, criado_em, fornecedor, modelo, operacao, input_tokens, output_tokens, total_tokens, custo_usd, custo_estimado, status, erro, latencia_ms) VALUES (?, ?, ?, ?, ?, 0, 0, 0, NULL, 0, 'ERROR', ?, ?)",
                (str(uuid.uuid4()), datetime.now(timezone.utc).isoformat(timespec="seconds"), str(fornecedor)[:64], str(modelo)[:200], str(operacao)[:100], str(erro)[:800], latencia_ms),
            )
    except Exception:
        log.warning("Não foi possível persistir falha de API.", exc_info=True)


def resumo(*, horas: int = 24) -> dict[str, Any]:
    """Agregação para painel, sem prompt, documento ou credencial."""
    horas = max(1, min(int(horas), 24 * 30))
    with conectar(timeout=5) as con:
        totais = con.execute("SELECT COUNT(*) AS chamadas, SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens, SUM(total_tokens) AS total_tokens, SUM(COALESCE(custo_usd,0)) AS custo_usd, SUM(CASE WHEN status='ERROR' THEN 1 ELSE 0 END) AS erros FROM custos_api WHERE criado_em >= DATEADD(hour, ?, SYSUTCDATETIME())", (-horas,)).fetchone() or {}
        por_modelo = con.execute("SELECT fornecedor, modelo, operacao, status, COUNT(*) AS chamadas, SUM(total_tokens) AS total_tokens, SUM(COALESCE(custo_usd,0)) AS custo_usd, AVG(CAST(latencia_ms AS float)) AS latencia_ms FROM custos_api WHERE criado_em >= DATEADD(hour, ?, SYSUTCDATETIME()) GROUP BY fornecedor, modelo, operacao, status ORDER BY chamadas DESC", (-horas,)).fetchall()
    return {"horas": horas, "totais": dict(totais), "por_modelo": [dict(x) for x in por_modelo]}


#: APIs pagas que o escritório recarrega. O saldo vem do próprio provedor; o gasto
#: local vem de `custos_api` e não substitui o saldo quando o provedor não o informa.
PROVEDORES = (
    {"id": "openrouter", "nome": "OpenRouter", "env": "OPENROUTER_API_KEY"},
    {"id": "deepseek", "nome": "DeepSeek", "env": "DEEPSEEK_API_KEY"},
    {"id": "mistral", "nome": "Mistral", "env": "MISTRAL_API_KEY"},
)


def classificar_saldo(restante: Decimal | None, teto: Decimal | None, *, moeda: str = "USD") -> tuple[str, str]:
    """Diz se dá para seguir ou se é hora de recarregar.

    Sem saldo consultado, o sinal fica desconhecido: inventar um restante seria
    pior do que dizer que o provedor não informou.
    """
    if restante is None:
        return "desconhecido", "O provedor não informou quanto ainda resta."
    if restante <= 0:
        return "critico", "Saldo esgotado. Recarregue esta API agora."
    if teto is not None and teto > 0:
        fracao = restante / teto
        if fracao <= Decimal("0.10"):
            return "critico", "Resta menos de 10% do crédito. Recarregue agora."
        if fracao <= Decimal("0.25"):
            return "atencao", "Resta menos de 25% do crédito. Recarregue em breve."
        return "ok", "Crédito suficiente."
    piso_critico = Decimal("5") if moeda.upper() == "CNY" else Decimal("1")
    piso_atencao = Decimal("20") if moeda.upper() == "CNY" else Decimal("5")
    if restante <= piso_critico:
        return "critico", "O saldo está no fim. Recarregue agora."
    if restante <= piso_atencao:
        return "atencao", "O saldo está baixo. Recarregue em breve."
    return "ok", "Crédito suficiente."


def _decimal(valor: Any) -> Decimal | None:
    if valor is None or valor == "":
        return None
    try:
        return Decimal(str(valor))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _consultar_openrouter(chave: str) -> dict[str, Any]:
    import httpx

    resposta = httpx.get(
        "https://openrouter.ai/api/v1/credits",
        headers={"Authorization": f"Bearer {chave}"},
        timeout=8,
    )
    resposta.raise_for_status()
    dados = (resposta.json() or {}).get("data") or {}
    teto = _decimal(dados.get("total_credits"))
    uso = _decimal(dados.get("total_usage")) or Decimal(0)
    restante = None if teto is None else teto - uso
    return {"moeda": "USD", "saldo": restante, "teto": teto, "consultado": True}


def _consultar_deepseek(chave: str) -> dict[str, Any]:
    import httpx

    base = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    resposta = httpx.get(
        f"{base}/user/balance",
        headers={"Authorization": f"Bearer {chave}"},
        timeout=8,
    )
    resposta.raise_for_status()
    corpo = resposta.json() or {}
    infos = corpo.get("balance_infos") or []
    info = infos[0] if infos else {}
    restante = _decimal(info.get("total_balance"))
    if corpo.get("is_available") is False:
        restante = Decimal(0)
    return {"moeda": str(info.get("currency") or "USD"), "saldo": restante, "teto": None, "consultado": True}


def _saldo_do_provedor(provedor_id: str, chave: str) -> dict[str, Any]:
    try:
        if provedor_id == "openrouter":
            return _consultar_openrouter(chave)
        if provedor_id == "deepseek":
            return _consultar_deepseek(chave)
    except Exception as erro:
        log.warning("saldo de %s indisponível: %s", provedor_id, type(erro).__name__)
        return {"moeda": "USD", "saldo": None, "teto": None, "consultado": False, "falha": "Não foi possível consultar o saldo agora."}
    return {"moeda": "USD", "saldo": None, "teto": None, "consultado": False}


def _numero_linha(valor: Any) -> float:
    if valor is None:
        return 0.0
    try:
        return float(valor)
    except (TypeError, ValueError):
        return 0.0


def _gastos_por_fornecedor() -> dict[str, dict[str, float]]:
    """Gasto registrado aqui, por fornecedor, em 24h, 7 dias e 30 dias."""
    vazio = {"gasto_24h": 0.0, "gasto_7d": 0.0, "gasto_30d": 0.0, "chamadas_30d": 0.0, "erros_30d": 0.0, "tokens_30d": 0.0}
    try:
        with conectar(timeout=5) as con:
            linhas = con.execute(
                """
                SELECT fornecedor,
                       SUM(CASE WHEN criado_em >= DATEADD(hour, -24, SYSUTCDATETIME()) THEN COALESCE(custo_usd, 0) ELSE 0 END) AS gasto_24h,
                       SUM(CASE WHEN criado_em >= DATEADD(day, -7, SYSUTCDATETIME()) THEN COALESCE(custo_usd, 0) ELSE 0 END) AS gasto_7d,
                       SUM(COALESCE(custo_usd, 0)) AS gasto_30d,
                       COUNT(*) AS chamadas_30d,
                       SUM(CASE WHEN status = 'ERROR' THEN 1 ELSE 0 END) AS erros_30d,
                       SUM(total_tokens) AS tokens_30d
                FROM custos_api
                WHERE criado_em >= DATEADD(day, -30, SYSUTCDATETIME())
                GROUP BY fornecedor
                """
            ).fetchall()
    except Exception:
        log.warning("gastos locais indisponíveis", exc_info=True)
        return {}
    saida: dict[str, dict[str, float]] = {}
    for linha in linhas:
        item = dict(linha)
        fornecedor = str(item.get("fornecedor") or "").strip().lower()
        if not fornecedor:
            continue
        base = dict(vazio)
        for chave in vazio:
            if chave in item:
                base[chave] = _numero_linha(item[chave])
        saida[fornecedor] = base
    return saida


#: Brasília, sem horário de verão desde 2019. O dia do gráfico é o dia do escritório, não o de UTC.
FUSO_DO_ESCRITORIO = timezone(timedelta(hours=-3))

#: Hoje acima destas vezes a média dos 7 dias anteriores vira alerta.
PICO_ATENCAO = 1.8
PICO_CRITICO = 3.0


def _linhas_por_hora(desde: datetime) -> list[dict[str, Any]]:
    """Consumo agrupado por hora UTC. `criado_em` é texto ISO em UTC: comparar e cortar o texto
    é exato e não depende de conversão de data pelo banco."""
    with conectar(timeout=5) as con:
        linhas = con.execute(
            """
            SELECT LEFT(criado_em, 13) AS hora, fornecedor, operacao, status,
                   COUNT(*) AS chamadas, SUM(total_tokens) AS tokens, SUM(COALESCE(custo_usd, 0)) AS custo_usd
            FROM custos_api
            WHERE criado_em >= ?
            GROUP BY LEFT(criado_em, 13), fornecedor, operacao, status
            """,
            (desde.isoformat(timespec="seconds"),),
        ).fetchall()
    return [dict(linha) for linha in linhas]


def _alerta(hoje: dict[str, float], anteriores: list[dict[str, float]]) -> dict[str, Any]:
    """Hoje contra a média dos dias anteriores, em custo quando há custo, senão em tokens."""
    media_custo = sum(d["custo_usd"] for d in anteriores) / len(anteriores) if anteriores else 0.0
    media_tokens = sum(d["tokens"] for d in anteriores) / len(anteriores) if anteriores else 0.0
    if media_custo > 0:
        medida, atual, media = "custo", hoje["custo_usd"], media_custo
    else:
        medida, atual, media = "tokens", hoje["tokens"], media_tokens
    base = {"medida": medida, "hoje": atual, "media": media, "vezes": (atual / media) if media > 0 else None}
    if media <= 0:
        return {**base, "nivel": "ok", "mensagem": "Ainda não há histórico suficiente para comparar o gasto de hoje."}
    vezes = atual / media
    texto_vezes = f"{vezes:.1f}".replace(".", ",")
    if vezes >= PICO_CRITICO:
        return {**base, "nivel": "critico",
                "mensagem": f"Hoje já se gastou {texto_vezes} vezes a média dos últimos 7 dias. Veja abaixo qual parte do sistema puxou o gasto."}
    if vezes >= PICO_ATENCAO:
        return {**base, "nivel": "atencao",
                "mensagem": f"Hoje já se gastou {texto_vezes} vezes a média dos últimos 7 dias."}
    return {**base, "nivel": "ok", "mensagem": "O gasto de hoje está dentro do normal."}


def agregar_uso(linhas: list[dict[str, Any]], *, dias: int, agora: datetime) -> dict[str, Any]:
    """Séries para os gráficos: por dia (com os dias sem uso zerados), últimas 24 horas e por operação."""
    local_agora = agora.astimezone(FUSO_DO_ESCRITORIO)
    hoje = local_agora.date()
    dias_do_periodo = [hoje - timedelta(days=n) for n in range(dias - 1, -1, -1)]

    def vazio() -> dict[str, Any]:
        return {"custo_usd": 0.0, "tokens": 0.0, "chamadas": 0.0, "erros": 0.0}

    por_dia: dict[str, dict[str, Any]] = {d.isoformat(): {**vazio(), "por_fornecedor": {}} for d in dias_do_periodo}
    horas_do_periodo = [(local_agora - timedelta(hours=n)).strftime("%Y-%m-%dT%H") for n in range(23, -1, -1)]
    por_hora: dict[str, dict[str, Any]] = {h: vazio() for h in horas_do_periodo}
    por_operacao: dict[tuple[str, str], dict[str, Any]] = {}
    inicio_do_periodo = dias_do_periodo[0].isoformat()

    for linha in linhas:
        try:
            hora_utc = datetime.strptime(str(linha.get("hora") or ""), "%Y-%m-%dT%H").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        local = hora_utc.astimezone(FUSO_DO_ESCRITORIO)
        dia, hora = local.date().isoformat(), local.strftime("%Y-%m-%dT%H")
        custo = _numero_linha(linha.get("custo_usd"))
        tokens = _numero_linha(linha.get("tokens"))
        chamadas = _numero_linha(linha.get("chamadas"))
        erros = chamadas if str(linha.get("status") or "").upper() == "ERROR" else 0.0
        fornecedor = str(linha.get("fornecedor") or "").strip().lower() or "outro"
        operacao = str(linha.get("operacao") or "").strip() or "outra"
        if dia in por_dia:
            item = por_dia[dia]
            item["custo_usd"] += custo
            item["tokens"] += tokens
            item["chamadas"] += chamadas
            item["erros"] += erros
            f = item["por_fornecedor"].setdefault(fornecedor, {"custo_usd": 0.0, "tokens": 0.0})
            f["custo_usd"] += custo
            f["tokens"] += tokens
        if hora in por_hora:
            h = por_hora[hora]
            h["custo_usd"] += custo
            h["tokens"] += tokens
            h["chamadas"] += chamadas
            h["erros"] += erros
        if dia >= inicio_do_periodo:
            o = por_operacao.setdefault((operacao, fornecedor), {**vazio(), "hoje_custo_usd": 0.0, "hoje_tokens": 0.0})
            o["custo_usd"] += custo
            o["tokens"] += tokens
            o["chamadas"] += chamadas
            o["erros"] += erros
            if dia == hoje.isoformat():
                o["hoje_custo_usd"] += custo
                o["hoje_tokens"] += tokens

    serie_dias = [{"dia": d, **v} for d, v in por_dia.items()]
    anteriores = serie_dias[-8:-1]
    fornecedores_sem_custo = sorted({
        f for d in serie_dias for f, v in d["por_fornecedor"].items() if v["tokens"] > 0 and v["custo_usd"] == 0
    } - {f for d in serie_dias for f, v in d["por_fornecedor"].items() if v["custo_usd"] > 0})
    operacoes = sorted(
        ({"operacao": op, "fornecedor": forn, **v} for (op, forn), v in por_operacao.items()),
        key=lambda o: (o["custo_usd"], o["tokens"]), reverse=True,
    )
    alerta = _alerta(serie_dias[-1], anteriores)
    chave_hoje = "hoje_custo_usd" if alerta["medida"] == "custo" else "hoje_tokens"
    de_hoje = max(operacoes, key=lambda o: o[chave_hoje], default=None)
    alerta["principal_hoje"] = (
        {"operacao": de_hoje["operacao"], "fornecedor": de_hoje["fornecedor"], "valor": de_hoje[chave_hoje]}
        if de_hoje and de_hoje[chave_hoje] > 0 else None
    )
    return {
        "dias": dias,
        "fuso": "UTC-3",
        "por_dia": serie_dias,
        "por_hora": [{"hora": h, **v} for h, v in por_hora.items()],
        "por_operacao": operacoes,
        "totais": {k: sum(d[k] for d in serie_dias) for k in ("custo_usd", "tokens", "chamadas", "erros")},
        "fornecedores_sem_custo": fornecedores_sem_custo,
        "alerta": alerta,
        "atualizado_em": agora.astimezone(timezone.utc).isoformat(timespec="seconds"),
    }


def uso(*, dias: int = 30) -> dict[str, Any]:
    """Uso das APIs ao longo do tempo, para ver quando e onde o gasto sobe."""
    dias = max(7, min(int(dias), 90))
    agora = datetime.now(timezone.utc)
    # Um dia a mais cobre a diferença entre o dia de UTC e o dia do escritório.
    return agregar_uso(_linhas_por_hora(agora - timedelta(days=dias + 1)), dias=dias, agora=agora)


def painel() -> dict[str, Any]:
    """Gasto local e saldo restante de cada API, com o sinal de recarga."""
    gastos = _gastos_por_fornecedor()
    apis: list[dict[str, Any]] = []
    vistos: set[str] = set()
    for provedor in PROVEDORES:
        chave = os.getenv(provedor["env"], "").strip()
        saldo = _saldo_do_provedor(provedor["id"], chave) if chave else {"moeda": "USD", "saldo": None, "teto": None, "consultado": False}
        if not chave:
            sinal, mensagem = "ausente", "Esta API não está configurada."
        elif saldo.get("falha"):
            sinal, mensagem = "desconhecido", str(saldo["falha"])
        else:
            sinal, mensagem = classificar_saldo(saldo.get("saldo"), saldo.get("teto"), moeda=str(saldo.get("moeda") or "USD"))
        apis.append({
            "id": provedor["id"],
            "nome": provedor["nome"],
            "configurada": bool(chave),
            "moeda": saldo.get("moeda") or "USD",
            "saldo": None if saldo.get("saldo") is None else float(saldo["saldo"]),
            "teto": None if saldo.get("teto") is None else float(saldo["teto"]),
            "sinal": sinal,
            "mensagem": mensagem,
            **gastos.get(provedor["id"], {"gasto_24h": 0.0, "gasto_7d": 0.0, "gasto_30d": 0.0, "chamadas_30d": 0.0, "erros_30d": 0.0, "tokens_30d": 0.0}),
        })
        vistos.add(provedor["id"])
    for fornecedor, gasto in gastos.items():
        if fornecedor in vistos:
            continue
        apis.append({
            "id": fornecedor,
            "nome": fornecedor,
            "configurada": True,
            "moeda": "USD",
            "saldo": None,
            "teto": None,
            "sinal": "desconhecido",
            "mensagem": "Há gasto registrado, mas este provedor não informa o saldo restante.",
            **gasto,
        })
    return {"apis": apis, "atualizado_em": datetime.now(timezone.utc).isoformat(timespec="seconds")}
