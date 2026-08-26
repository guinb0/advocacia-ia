"""UFs e municípios oficiais, persistidos localmente a partir do IBGE."""

from __future__ import annotations

from datetime import datetime, timezone
import gzip
import json
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fastapi import APIRouter, HTTPException, Query

from . import banco

roteador = APIRouter(prefix="/api/localidades", tags=["localidades"])
IBGE = "https://servicodados.ibge.gov.br/api/v1/localidades"


def _uf_do_municipio(item: dict[str, Any]) -> dict[str, Any] | None:
    micro = item.get("microrregiao") or {}
    uf = (micro.get("mesorregiao") or {}).get("UF")
    if uf:
        return uf
    imediata = item.get("regiao-imediata") or {}
    return (imediata.get("regiao-intermediaria") or {}).get("UF")


def sincronizar() -> dict[str, int]:
    """Atualiza as duas tabelas numa transação, após concluir os downloads."""
    def baixar(recurso: str, timeout: int) -> list[dict[str, Any]]:
        url = f"{IBGE}/{recurso}?{urlencode({'orderBy': 'nome'})}"
        requisicao = Request(url, headers={"Accept-Encoding": "identity", "User-Agent": "AdvocaciaIA/1.0"})
        with urlopen(requisicao, timeout=timeout) as resposta:  # noqa: S310 — domínio fixo do IBGE
            corpo = resposta.read()
            if corpo.startswith(b"\x1f\x8b"):
                corpo = gzip.decompress(corpo)
            return json.loads(corpo.decode("utf-8"))

    estados = baixar("estados", 30)
    municipios = baixar("municipios", 90)
    agora = datetime.now(timezone.utc).isoformat()
    ufs = [
        (int(u["id"]), str(u["sigla"]), str(u["nome"]),
         int((u.get("regiao") or {}).get("id") or 0) or None, agora)
        for u in estados
    ]
    cidades = []
    for item in municipios:
        uf = _uf_do_municipio(item)
        if uf:
            cidades.append((int(item["id"]), int(uf["id"]), str(item["nome"]), agora))

    with banco.conectar() as con:
        con.executemany(
            """MERGE ufs AS alvo USING (SELECT ? id, ? sigla, ? nome, ? regiao_id, ? atualizado_em) AS fonte
            ON alvo.id=fonte.id WHEN MATCHED THEN UPDATE SET sigla=fonte.sigla,nome=fonte.nome,
            regiao_id=fonte.regiao_id,atualizado_em=fonte.atualizado_em WHEN NOT MATCHED THEN
            INSERT (id,sigla,nome,regiao_id,atualizado_em) VALUES
            (fonte.id,fonte.sigla,fonte.nome,fonte.regiao_id,fonte.atualizado_em);""", ufs)
        con.executemany(
            """MERGE municipios AS alvo USING (SELECT ? id, ? uf_id, ? nome, ? atualizado_em) AS fonte
            ON alvo.id=fonte.id WHEN MATCHED THEN UPDATE SET uf_id=fonte.uf_id,nome=fonte.nome,
            atualizado_em=fonte.atualizado_em WHEN NOT MATCHED THEN INSERT (id,uf_id,nome,atualizado_em)
            VALUES (fonte.id,fonte.uf_id,fonte.nome,fonte.atualizado_em);""", cidades)
    return {"ufs": len(ufs), "municipios": len(cidades)}


def inicializar() -> None:
    banco.inicializar_schema()
    with banco.conectar() as con:
        linha = con.execute("SELECT COUNT(*) AS total FROM municipios").fetchone()
    if not linha or int(linha["total"]) < 5500:
        sincronizar()


@roteador.get("/ufs")
def listar_ufs() -> dict[str, list[dict[str, Any]]]:
    with banco.conectar() as con:
        linhas = con.execute("SELECT id, sigla, nome FROM ufs ORDER BY nome").fetchall()
    return {"ufs": [{"id": l["id"], "sigla": l["sigla"], "nome": l["nome"]} for l in linhas]}


@roteador.get("/municipios")
def listar_municipios(uf: str = Query(min_length=2, max_length=2)) -> dict[str, list[dict[str, Any]]]:
    with banco.conectar() as con:
        linhas = con.execute(
            """SELECT m.id,m.nome,u.sigla AS uf FROM municipios m
            INNER JOIN ufs u ON u.id=m.uf_id WHERE u.sigla=? ORDER BY m.nome""", (uf.upper(),)
        ).fetchall()
    if not linhas:
        raise HTTPException(404, "UF não encontrada ou municípios ainda não sincronizados.")
    return {"municipios": [{"id": l["id"], "nome": l["nome"], "uf": l["uf"]} for l in linhas]}
