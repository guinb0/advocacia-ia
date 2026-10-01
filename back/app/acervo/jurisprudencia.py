"""Súmulas, OJs e súmulas vinculantes → `autoridades_juridicas`, por importação de arquivo JSON.

Não há raspagem de site de tribunal aqui: as páginas de súmulas do TST e do STF mudam de formato e
não trazem status estruturado. O escritório exporta da fonte oficial para um JSON (lista de objetos)
e a importação faz o resto. Formato de cada item:

    {"tipo": "sumula" | "oj" | "sumula_vinculante" | "tema" | "controle_concentrado",
     "tribunal": "TST", "orgao": "SDI-1" (OJ), "classe": "ADC" (controle concentrado), "numero": "331", "titulo": "Súmula 331 do TST",
     "texto": "...", "status": "vigente" | "superado" | "cancelado" | "revogado" | "suspenso",
     "superado_por": "id ou chave da sucessora", "vigencia_inicio": "AAAA-MM-DD", "vigencia_fim": "AAAA-MM-DD",
     "fonte_oficial": "TST", "url": "https://...", "vinculante": false, "marcadores": ["..."]}

Tudo entra como AGUARDANDO_VERIFICACAO (`verificada=false`): quem confere na fonte é uma pessoa.
Se o texto ou o status mudar numa importação seguinte, volta para AGUARDANDO_VERIFICACAO e gera
alerta. Status "superado/cancelado/revogado" vale para o Citation Gate mesmo sem verificação —
bloquear por cautela é o lado seguro.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from ..juridico import autoridades as aut
from . import parser
from . import status as st
from .armazenamento import Armazenamento

PASTA_PADRAO = Path(__file__).with_name("jurisprudencia")
TIPOS = {"sumula", "sumula_vinculante", "oj", "tema", "controle_concentrado", "precedente"}
STATUS = {"vigente", "revogado", "superado", "cancelado", "suspenso"}
INATIVOS = {"revogado", "superado", "cancelado"}


class ItemInvalido(ValueError):
    pass


def _hash(item: dict[str, Any]) -> str:
    return parser.sha256(json.dumps({k: item.get(k) or "" for k in ("texto", "status", "superado_por", "vigencia_inicio", "vigencia_fim", "tese")},
                                    ensure_ascii=False, sort_keys=True))


def normalizar(bruto: dict[str, Any]) -> dict[str, Any]:
    tipo = str(bruto.get("tipo") or "").strip().lower()
    if tipo not in TIPOS:
        raise ItemInvalido(f"tipo inválido: {tipo!r}")
    numero = str(bruto.get("numero") or "").strip()
    tribunal = str(bruto.get("tribunal") or ("STF" if tipo == "sumula_vinculante" else "")).strip()
    if not numero or not tribunal:
        raise ItemInvalido("número e tribunal são obrigatórios")
    status = str(bruto.get("status") or "vigente").strip().lower()
    if status not in STATUS:
        raise ItemInvalido(f"status inválido: {status!r}")
    if not str(bruto.get("fonte_oficial") or "").strip() or not str(bruto.get("url") or "").strip():
        raise ItemInvalido("fonte_oficial e url são obrigatórios (só entra o que tem fonte oficial)")
    texto = str(bruto.get("texto") or bruto.get("tese") or "").strip()
    if not texto:
        raise ItemInvalido("texto vazio")
    orgao = str(bruto.get("orgao") or "").strip()
    classe = str(bruto.get("classe") or "").strip().upper()
    if tipo == "controle_concentrado" and classe not in {"ADC", "ADI", "ADPF", "ADO"}:
        raise ItemInvalido("controle concentrado exige classe ADC, ADI, ADPF ou ADO")
    a = aut.Autoridade(id="", tipo=tipo, chave="", tribunal=tribunal, orgao=orgao, numero=numero, classe=classe)
    chave = aut.chave_de(a)
    item = {
        "id": str(bruto.get("id") or f"acervo:{chave}"), "organization_id": "", "tipo": tipo, "chave": chave,
        "titulo": str(bruto.get("titulo") or f"{tipo.replace('_', ' ').title()} {numero} do {tribunal}"), "texto": texto,
        "tribunal": tribunal, "orgao": orgao, "classe": classe, "numero": numero, "tema": str(bruto.get("tema") or ""), "assunto": str(bruto.get("assunto") or ""),
        "tese": str(bruto.get("tese") or ""), "vigencia_inicio": bruto.get("vigencia_inicio") or None, "vigencia_fim": bruto.get("vigencia_fim") or None,
        "status": status, "superado_por": str(bruto.get("superado_por") or ""), "vinculante": bool(bruto.get("vinculante") or tipo == "sumula_vinculante"),
        "fonte_oficial": str(bruto["fonte_oficial"]), "url": str(bruto["url"]), "marcadores": list(bruto.get("marcadores") or []),
    }
    item["content_hash"] = _hash(item)
    return item


def carregar_arquivo(caminho: Path) -> list[dict[str, Any]]:
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    if not isinstance(dados, list):
        raise ItemInvalido(f"{caminho.name}: o arquivo deve ser uma lista de objetos")
    return dados


def importar(linhas: list[dict[str, Any]], *, armazenamento: Armazenamento, agora: datetime, origem: str = "importacao") -> dict[str, Any]:
    existentes = {a["id"]: a for a in armazenamento.autoridades()}
    gravar, invalidos = [], []
    rel = {"novas": 0, "alteradas": 0, "inalteradas": 0, "superadas": 0, "invalidas": 0, "erros": invalidos}
    for i, bruto in enumerate(linhas):
        try:
            item = normalizar(bruto)
        except ItemInvalido as erro:
            rel["invalidas"] += 1
            invalidos.append(f"item {i + 1}: {erro}")
            continue
        antes = existentes.get(item["id"])
        if antes and antes.get("content_hash") == item["content_hash"]:
            gravar.append({"id": item["id"], "ultima_verificacao": agora})
            rel["inalteradas"] += 1
            continue
        item.update(verificada=False, sync_status=st.AGUARDANDO_VERIFICACAO, verificado_em=agora, ultima_verificacao=agora)
        gravar.append(item)
        if antes:
            rel["alteradas"] += 1
            armazenamento.alertar({"tipo": "AUTORIDADE_ALTERADA", "severidade": "media", "authority_id": item["id"],
                                   "titulo": f"{item['titulo']}: texto ou status mudou na importação",
                                   "detalhe": "Voltou para 'aguardando verificação' até alguém conferir na fonte oficial."}, agora=agora)
        else:
            rel["novas"] += 1
        if item["status"] in INATIVOS and (not antes or antes.get("status") not in INATIVOS):
            rel["superadas"] += 1
            armazenamento.alertar({"tipo": "AUTORIDADE_SUPERADA", "severidade": "alta", "authority_id": item["id"],
                                   "titulo": f"{item['titulo']} está {item['status']}" + (f" (sucessora: {item['superado_por']})" if item["superado_por"] else ""),
                                   "dados": {"origem": origem}}, agora=agora)
    if gravar:
        armazenamento.salvar_autoridades(gravar, agora=agora)
    return rel


def importar_pasta(pasta: Path | None = None, *, armazenamento: Armazenamento, agora: datetime) -> dict[str, Any]:
    pasta = pasta or Path(os.getenv("ACERVO_JURISPRUDENCIA_DIR", "").strip() or PASTA_PADRAO)
    saida: dict[str, Any] = {}
    for arquivo in sorted(pasta.glob("*.json")) if pasta.is_dir() else []:
        try:
            saida[arquivo.name] = importar(carregar_arquivo(arquivo), armazenamento=armazenamento, agora=agora, origem=arquivo.name)
        except (ItemInvalido, json.JSONDecodeError) as erro:
            saida[arquivo.name] = {"erro": str(erro)}
    return saida
