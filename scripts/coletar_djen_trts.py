"""Coleta decisões recentes de TODOS os TRTs pelo DJEN (Comunica API do PJe).

POR QUE ESTE CAMINHO

Para "insights de decisões de varas" o que importa é a decisão RECENTE com texto,
de qualquer regional. A Comunica API (`comunicaapi.pje.jus.br`) entrega isso
direto: filtra por `siglaTribunal` e por data de disponibilização, e cada item já
traz o texto, o órgão julgador (a vara), o número do processo e a classe. Não
precisa do caminho DataJud→processo→DJEN — que serve à jurimetria de movimentos,
não à leitura semântica da decisão.

O arquivo de saída tem o MESMO formato que `scripts.ingerir_jurimetria_geral` já
lê, então o fluxo é:

    python -m scripts.coletar_djen_trts --meses 6            # coleta -> JSON
    python -m scripts.ingerir_jurimetria_geral --arquivo decisoes_djen_trts.json
    python -m scripts.vetorizar_pendentes                    # gera embeddings

VOLUME E JANELA

A API limita cada consulta a ~10.000 itens, então a coleta anda por JANELAS DE
DIA e pagina dentro de cada dia. Mesmo assim são MUITAS publicações; por padrão
guarda só as que parecem DECISÃO (sentença, acórdão, decisão), não intimação ou
despacho — `--todos` desliga esse filtro. `--limite-por-tribunal` ajuda a fazer
uma amostra antes de soltar a coleta inteira.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

import httpx

BASE = "https://comunicaapi.pje.jus.br/api/v1/comunicacao"
TRIBUNAIS_TRT = [f"TRT{n}" for n in range(1, 25)]

#: O DJEN NÃO tem "Sentença/Acórdão" como tipo — publica AVISOS (edital,
#: intimação, lista de distribuição). Muitos avisos, porém, carregam o teor da
#: decisão (uma intimação de sentença traz o dispositivo; um edital de leilão, a
#: penhora). O que não tem conteúdo é a lista de distribuição — puro roteamento.
#: Então o filtro guarda o que é SUBSTANTIVO: descarta distribuição e texto curto.
TIPOS_SEM_CONTEUDO = ("distribui", "pauta", "expediente")
MIN_CARACTERES = 400


def _sem_acento(texto: str) -> str:
    import unicodedata

    return "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    ).lower()


def _e_substantiva(item: dict[str, Any]) -> bool:
    tipo = _sem_acento(str(item.get("tipoComunicacao") or "") + " " + str(item.get("tipoDocumento") or ""))
    if any(t in tipo for t in TIPOS_SEM_CONTEUDO):
        return False
    return len(str(item.get("texto") or "").strip()) >= MIN_CARACTERES


def _janelas(inicio: date, fim: date) -> Iterator[tuple[str, str]]:
    """Um dia por vez, do MAIS RECENTE ao mais antigo (fim inclusivo).

    Recente primeiro serve ao pedido ("decisões dos últimos meses") e faz a
    amostra com `--limite-por-tribunal` sair na hora, sem varrer o passado antes.
    Um dia por janela cabe no teto de ~10k itens por consulta da API.
    """
    dia = fim
    while dia >= inicio:
        iso = dia.isoformat()
        yield iso, iso
        dia -= timedelta(days=1)


class _JanelaFalhou(Exception):
    """A janela não respondeu depois das tentativas — pula, não derruba a coleta."""


def _pagina(cliente: httpx.Client, tribunal: str, di: str, df: str, pagina: int) -> tuple[int, list[dict]]:
    params = {
        "siglaTribunal": tribunal,
        "dataDisponibilizacaoInicio": di,
        "dataDisponibilizacaoFim": df,
        "itensPorPagina": 100,
        "pagina": pagina,
    }
    # A Comunica devolve 500/503 intermitente. Tenta algumas vezes com espera
    # crescente; persistindo, pula a janela em vez de abortar tudo.
    for tentativa in range(5):
        try:
            resposta = cliente.get(BASE, params=params)
        except httpx.HTTPError:
            time.sleep(3 * (tentativa + 1))
            continue
        if resposta.status_code == 429:
            time.sleep(60)
            continue
        if resposta.status_code >= 500:
            time.sleep(3 * (tentativa + 1))
            continue
        resposta.raise_for_status()
        corpo = resposta.json()
        return int(corpo.get("count") or 0), list(corpo.get("items") or [])
    raise _JanelaFalhou(f"{tribunal} {di}: sem resposta após 5 tentativas")


def _registro(item: dict[str, Any]) -> dict[str, Any]:
    """Formato que `ingerir_jurimetria_geral` lê, com a vara no corpo do texto."""
    orgao = str(item.get("nomeOrgao") or "").strip()
    classe = str(item.get("nomeClasse") or "").strip()
    corpo = str(item.get("texto") or "").strip()
    cabecalho = " — ".join(p for p in (orgao, classe) if p)
    texto = f"{cabecalho}\n\n{corpo}" if cabecalho else corpo
    return {
        "numeroProcesso": item.get("numero_processo") or item.get("numeroProcesso") or "",
        "tribunal": item.get("siglaTribunal") or "",
        "dataDisponibilizacao": item.get("data_disponibilizacao") or item.get("dataDisponibilizacao"),
        "tipoComunicacao": item.get("tipoComunicacao"),
        "tipo_conteudo": "publicacao_djen",
        "texto": texto,
    }


def _coletar_tribunal(
    cliente: httpx.Client,
    tribunal: str,
    inicio: date,
    fim: date,
    *,
    todos: bool,
    limite: int | None,
    intervalo: float,
) -> list[dict[str, Any]]:
    vistos: set[str] = set()
    saida: list[dict[str, Any]] = []
    for di, df in _janelas(inicio, fim):
        pagina = 1
        while True:
            try:
                total, itens = _pagina(cliente, tribunal, di, df, pagina)
            except _JanelaFalhou as erro:
                print(f"  ! pulando {erro}")
                break
            time.sleep(intervalo)
            if not itens:
                break
            for item in itens:
                if not todos and not _e_substantiva(item):
                    continue
                if len(str(item.get("texto") or "").strip()) < 100:
                    continue
                chave = f"{item.get('numero_processo')}:{hash(str(item.get('texto')))}"
                if chave in vistos:
                    continue
                vistos.add(chave)
                saida.append(_registro(item))
            if limite and len(saida) >= limite:
                return saida
            if pagina * 100 >= min(total, 10_000):
                break
            pagina += 1
    return saida


def coletar(
    tribunais: list[str],
    inicio: date,
    fim: date,
    *,
    todos: bool,
    limite_por_tribunal: int | None,
    req_por_segundo: float,
    saida_dir: Path,
    continuar: bool,
) -> int:
    """Coleta por tribunal, gravando UM arquivo por TRT ao terminar cada um.

    Assim uma varredura de horas que caia retoma de onde parou (`--continuar`
    pula os TRTs já gravados) e nunca perde o que já baixou.
    """
    intervalo = 1.0 / max(req_por_segundo, 0.05)
    saida_dir.mkdir(parents=True, exist_ok=True)
    total_geral = 0
    with httpx.Client(timeout=60.0, follow_redirects=True) as cliente:
        for tribunal in tribunais:
            arquivo = saida_dir / f"{tribunal}.json"
            if continuar and arquivo.exists():
                print(f"  {tribunal}: já coletado, pulando")
                continue
            registros = _coletar_tribunal(
                cliente, tribunal, inicio, fim,
                todos=todos, limite=limite_por_tribunal, intervalo=intervalo,
            )
            arquivo.write_text(json.dumps(registros, ensure_ascii=False), encoding="utf-8")
            total_geral += len(registros)
            print(f"  {tribunal}: {len(registros):,} publicações -> {arquivo}")
    return total_geral


def main() -> int:
    hoje = date.today()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--meses", type=int, default=6, help="janela em meses até hoje (padrão 6)")
    p.add_argument("--tribunais", nargs="*", default=TRIBUNAIS_TRT, help="ex.: TRT2 TRT8 (padrão: os 24)")
    p.add_argument("--todos", action="store_true", help="não filtra só decisões; guarda toda publicação")
    p.add_argument("--limite-por-tribunal", type=int, default=None, help="amostra por tribunal")
    p.add_argument("--req-por-segundo", type=float, default=2.0)
    p.add_argument("--saida-dir", default="decisoes_djen", help="pasta; um arquivo por TRT")
    p.add_argument("--continuar", action="store_true", help="pula TRTs já coletados (retoma)")
    args = p.parse_args()

    inicio = hoje - timedelta(days=int(args.meses * 30.44))
    saida_dir = Path(args.saida_dir)
    print(f"DJEN — {len(args.tribunais)} tribunal(is), de {inicio} a {hoje} -> {saida_dir}/")
    total = coletar(
        [t.upper() for t in args.tribunais],
        inicio,
        hoje,
        todos=args.todos,
        limite_por_tribunal=args.limite_por_tribunal,
        req_por_segundo=args.req_por_segundo,
        saida_dir=saida_dir,
        continuar=args.continuar,
    )
    print(f"\n{total:,} registros gravados em {saida_dir}/ (um arquivo por TRT)")
    print("Agora, para cada arquivo:")
    print(f"  for f in {saida_dir}/*.json; do python -m scripts.ingerir_jurimetria_geral --arquivo \"$f\"; done")
    print("  python -m scripts.vetorizar_pendentes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
