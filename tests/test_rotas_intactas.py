"""Guarda o mapa de rotas da API: caminho, métodos, ordem, parâmetros e permissões.

O `app/main.py` foi repartido em routers (`app/rotas/`). Mover uma rota de
arquivo não pode mudar nada para quem chama: nem o endereço, nem a ordem em que
o FastAPI tenta casar os caminhos, nem a permissão exigida. Este teste compara
o app montado com o retrato gravado em `tests/rotas_esperadas.json`.

Não precisa de banco: os três efeitos de importação que tocam o SQL Server são
neutralizados antes de importar o `main`.

Rodar:   python -m tests.test_rotas_intactas
Regravar (só quando a mudança de rota for intencional):
         python -m tests.test_rotas_intactas --gravar
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

RETRATO = Path(__file__).with_name("rotas_esperadas.json")


def _importar_app():
    from app import armazenamento, google_drive, skills_juridicas

    armazenamento.inicializar = lambda *a, **k: None
    skills_juridicas.importar_embutida = lambda *a, **k: None
    google_drive.inicializar = lambda *a, **k: None

    from app import main

    return main.app


def _descrever_dependencia(dependant: Any) -> dict[str, Any]:
    chamada = dependant.call
    fechamento = []
    for celula in getattr(chamada, "__closure__", None) or ():
        try:
            valor = celula.cell_contents
        except ValueError:
            continue
        if isinstance(valor, (str, int, bool, tuple)):
            fechamento.append(valor if not isinstance(valor, tuple) else list(valor))
    return {
        "chamada": f"{getattr(chamada, '__module__', '')}.{getattr(chamada, '__qualname__', repr(chamada))}",
        "fechamento": fechamento,
        "dependencias": [_descrever_dependencia(d) for d in dependant.dependencies],
    }


def _parametros(dependant: Any) -> dict[str, list[str]]:
    return {
        "caminho": sorted(p.name for p in dependant.path_params),
        "consulta": sorted(p.name for p in dependant.query_params),
        "cabecalho": sorted(p.name for p in dependant.header_params),
        "cookie": sorted(p.name for p in dependant.cookie_params),
        "corpo": sorted(p.name for p in dependant.body_params),
    }


def _achatar(rotas) -> list[Any]:
    """Nesta versão do FastAPI, `include_router` guarda o router inteiro como um
    nó só; as rotas efetivas (com prefixo e dependências somados) saem de
    `effective_candidates()`."""
    saida = []
    for rota in rotas:
        if hasattr(rota, "effective_candidates"):
            saida.extend(_achatar(rota.effective_candidates()))
        else:
            saida.append(rota)
    return saida


def retrato(app) -> list[dict[str, Any]]:
    rotas = []
    for rota in _achatar(app.routes):
        original = getattr(rota, "original_route", rota)
        # WebSocket incluído por router guarda o que vale na rota Starlette.
        if not getattr(rota, "path", "") and getattr(rota, "starlette_route", None):
            rota = rota.starlette_route
        item: dict[str, Any] = {
            "caminho": getattr(rota, "path", ""),
            "tipo": type(original).__name__,
            "metodos": sorted(getattr(rota, "methods", None) or []),
            "nome": getattr(rota, "name", ""),
        }
        dependant = getattr(rota, "dependant", None)
        if dependant is not None:
            item["parametros"] = _parametros(dependant)
            item["dependencias"] = [
                _descrever_dependencia(d) for d in dependant.dependencies
            ]
            item["status_code"] = getattr(rota, "status_code", None)
        rotas.append(item)
    return rotas


def _chave(rota: dict[str, Any]) -> tuple:
    return (rota["caminho"], tuple(rota["metodos"]), rota["tipo"])


def _segmento_livre(segmento: str) -> bool:
    return segmento.startswith("{") and segmento.endswith("}")


def _podem_colidir(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Duas rotas que casariam o MESMO endereço: aí a ordem decide quem atende."""
    if a["tipo"] != b["tipo"]:
        return False
    if a["metodos"] and b["metodos"] and not set(a["metodos"]) & set(b["metodos"]):
        return False
    sa, sb = a["caminho"].split("/"), b["caminho"].split("/")
    if any(":path}" in s for s in sa + sb):
        return True
    if len(sa) != len(sb):
        return False
    return all(x == y or _segmento_livre(x) or _segmento_livre(y) for x, y in zip(sa, sb))


def comparar(atual: list[dict[str, Any]], esperado: list[dict[str, Any]]) -> list[str]:
    """A ordem global pode mudar (as rotas foram agrupadas por área); o que não
    pode mudar é o conteúdo de cada rota nem a ordem entre rotas que colidem."""
    problemas = []
    por_chave_atual = {_chave(r): r for r in atual}
    por_chave_esperado = {_chave(r): r for r in esperado}
    if len(por_chave_atual) != len(atual):
        problemas.append("Há rota registrada duas vezes.")
    for c in sorted(set(por_chave_esperado) - set(por_chave_atual)):
        problemas.append(f"FALTA {c}")
    for c in sorted(set(por_chave_atual) - set(por_chave_esperado)):
        problemas.append(f"SOBRA {c}")
    for c in sorted(set(por_chave_atual) & set(por_chave_esperado)):
        if por_chave_atual[c] != por_chave_esperado[c]:
            problemas.append(
                f"DIFERENTE {c}\n  esperado: {json.dumps(por_chave_esperado[c], ensure_ascii=False)}"
                f"\n  atual:    {json.dumps(por_chave_atual[c], ensure_ascii=False)}"
            )

    posicao = {_chave(r): i for i, r in enumerate(atual)}
    for i, a in enumerate(esperado):
        for b in esperado[i + 1 :]:
            if not _podem_colidir(a, b):
                continue
            pa, pb = posicao.get(_chave(a)), posicao.get(_chave(b))
            if pa is not None and pb is not None and pa > pb:
                problemas.append(
                    f"ORDEM: {_chave(a)} precisa vir antes de {_chave(b)}"
                )
    return problemas


def main() -> int:
    atual = retrato(_importar_app())
    if "--gravar" in sys.argv:
        RETRATO.write_text(
            json.dumps(atual, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
        print(f"Retrato gravado: {len(atual)} rotas em {RETRATO.name}")
        return 0

    esperado = json.loads(RETRATO.read_text(encoding="utf-8"))
    problemas = comparar(atual, esperado)
    if not problemas:
        print(f"OK: {len(atual)} rotas iguais ao retrato.")
        return 0
    for p in problemas:
        print(p)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
