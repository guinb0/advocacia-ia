"""Monta a base de 500 processos de UMA vara, a partir do que o coletor já baixou.

Issue "[Base de Dados - Processos] - Preparar base com 500 processos da última vara".

POR QUE ESTE PASSO EXISTE SEPARADO DO COLETOR

`scripts.coletar_djen_trts` varre o DJEN por tribunal e por dia e guarda tudo o
que é substantivo — é a rede grande. O que a issue pede é o oposto: uma amostra
FECHADA, de uma vara só, com 500 processos distintos, para a jurimetria comparar
o caso novo com decisões do mesmo juízo em vez de com o acervo nacional. Filtrar
por vara na coleta obrigaria a varrer o DJEN de novo a cada mudança de alvo; aqui
o recorte é feito sobre o que já está em disco, em segundos.

COMO A VARA É IDENTIFICADA

Pelo número CNJ do processo, não pelo texto. O formato é
`NNNNNNN-DD.AAAA.J.TR.OOOO`, e `OOOO` é a unidade de origem: `0019` é a 19ª Vara
do Trabalho, `0000` é o próprio tribunal (2º grau). Nos arquivos do coletor o
número vem sem pontuação (`00010527620265080000`), então a vara são os 4 últimos
dígitos. Ler a vara do texto ("19ª VARA DO TRABALHO DE BELEM") pareceria mais
direto e seria pior: a mesma publicação cita outras varas ao narrar o histórico
do processo, e o primeiro acerto da busca nem sempre é o juízo do caso.

QUAL É "A ÚLTIMA VARA"

Sem `--vara`, é a que tem a publicação MAIS RECENTE entre as unidades de 1º grau
do tribunal escolhido — a última vara a se manifestar no que foi coletado. O
número `0000` fica de fora: é o 2º grau, não é vara. Quando o alvo é outro, passe
`--vara 0019` e o palpite sai de cena.

UM PROCESSO, UMA LINHA

A base é de PROCESSOS, e o DJEN publica várias vezes no mesmo processo (intimação,
depois sentença, depois embargos). Guardar as três contaria o mesmo processo três
vezes na estatística de desfechos — o que a issue chama de "duplicidade indevida".
Fica UMA publicação por processo: a mais recente entre as substantivas, que é a
que carrega o estágio mais avançado da decisão.

Uso:
  .venv\\Scripts\\python.exe -m scripts.preparar_base_vara
  .venv\\Scripts\\python.exe -m scripts.preparar_base_vara --tribunal TRT8 --vara 0019
  .venv\\Scripts\\python.exe -m scripts.preparar_base_vara --quantos 500 --saida base_vara.json

Depois: `-m scripts.ingerir_jurimetria_geral --arquivo <saida>` e
`-m scripts.vetorizar_pendentes` (ou a tarefa AdvocaciaIA-SincronizarRAG) —
os dois precisam alcançar o pgvector em `DATABASE_URL`.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parent.parent
PASTA_COLETA = RAIZ / "decisoes_djen"

#: Mesmo critério de `scripts.coletar_djen_trts` — a issue pede que o
#: procedimento corresponda "à estratégia de limpeza definida", e ela é aquela.
TIPOS_SEM_CONTEUDO = ("distribui", "pauta", "expediente")
MIN_CARACTERES = 400

#: `0000` é o tribunal, não uma vara. Entra em `--vara` se alguém pedir de
#: propósito, mas nunca é escolhido como "a última vara".
UNIDADE_DO_TRIBUNAL = "0000"


def _sem_acento(texto: str) -> str:
    import unicodedata

    return "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    ).lower()


def _e_substantiva(item: dict[str, Any]) -> bool:
    tipo = _sem_acento(
        str(item.get("tipoComunicacao") or "") + " " + str(item.get("tipoDocumento") or "")
    )
    if any(t in tipo for t in TIPOS_SEM_CONTEUDO):
        return False
    return len(str(item.get("texto") or "").strip()) >= MIN_CARACTERES


def vara_do_processo(numero: str) -> str:
    """Os 4 dígitos da unidade de origem no número CNJ, ou "" se não der para ler."""
    digitos = re.sub(r"\D", "", str(numero or ""))
    # 20 dígitos é o CNJ completo. Menos que isso é número truncado ou de outro
    # padrão: melhor devolver vazio do que cravar uma vara errada.
    return digitos[-4:] if len(digitos) == 20 else ""


def carregar(tribunal: str, pasta: Path) -> list[dict[str, Any]]:
    arquivo = pasta / f"{tribunal}.json"
    if not arquivo.exists():
        raise SystemExit(
            f"Não achei {arquivo}. Rode antes: "
            f".venv\\Scripts\\python.exe -m scripts.coletar_djen_trts --tribunal {tribunal}"
        )
    dados = json.loads(arquivo.read_text(encoding="utf-8"))
    if not isinstance(dados, list):
        raise SystemExit(f"{arquivo} não tem a lista de publicações que eu esperava.")
    return dados


def escolher_vara(publicacoes: list[dict[str, Any]]) -> tuple[str, str]:
    """A vara de 1º grau com a publicação mais recente. Devolve (vara, data)."""
    melhor: tuple[str, str] = ("", "")
    for item in publicacoes:
        vara = vara_do_processo(item.get("numeroProcesso"))
        if not vara or vara == UNIDADE_DO_TRIBUNAL:
            continue
        data = str(item.get("dataDisponibilizacao") or "")
        if data > melhor[1]:
            melhor = (vara, data)
    return melhor


def montar(
    publicacoes: list[dict[str, Any]], vara: str, quantos: int
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Uma publicação por processo daquela vara, da mais recente para a mais antiga."""
    contagem = Counter()
    por_processo: dict[str, dict[str, Any]] = {}

    for item in publicacoes:
        if vara_do_processo(item.get("numeroProcesso")) != vara:
            continue
        contagem["da_vara"] += 1
        if not _e_substantiva(item):
            contagem["descartadas_pela_limpeza"] += 1
            continue
        numero = re.sub(r"\D", "", str(item.get("numeroProcesso") or ""))
        anterior = por_processo.get(numero)
        if anterior is None:
            por_processo[numero] = item
            continue
        contagem["duplicidades_do_mesmo_processo"] += 1
        # Fica a mais recente; empate mantém a mais longa, que é a que tem mais teor.
        nova_data = str(item.get("dataDisponibilizacao") or "")
        velha_data = str(anterior.get("dataDisponibilizacao") or "")
        if (nova_data, len(str(item.get("texto") or ""))) > (
            velha_data,
            len(str(anterior.get("texto") or "")),
        ):
            por_processo[numero] = item

    escolhidas = sorted(
        por_processo.values(),
        key=lambda i: str(i.get("dataDisponibilizacao") or ""),
        reverse=True,
    )
    contagem["processos_distintos"] = len(escolhidas)
    return escolhidas[:quantos], dict(contagem)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--tribunal", default="TRT8", help="Sigla do tribunal já coletado (padrão: TRT8).")
    p.add_argument("--vara", default="", help="Unidade CNJ de 4 dígitos (ex.: 0019). Vazio = a última a publicar.")
    p.add_argument("--quantos", type=int, default=500, help="Teto de processos (padrão: 500).")
    p.add_argument("--pasta", default=str(PASTA_COLETA), help="Onde estão os JSON do coletor.")
    p.add_argument("--saida", default=str(RAIZ / "decisoes_limpas.json"), help="Arquivo a gravar.")
    p.add_argument(
        "--listar",
        action="store_true",
        help="Só mostra as varas com mais processos no que foi coletado, e sai.",
    )
    args = p.parse_args()

    publicacoes = carregar(args.tribunal, Path(args.pasta))
    print(f"{args.tribunal}: {len(publicacoes)} publicações coletadas")

    if args.listar:
        # Escolher a vara sem saber quanta decisão cada uma rendeu é escolher no
        # escuro: a "última a publicar" pode ser uma vara de movimento pequeno.
        por_vara: dict[str, set[str]] = {}
        datas = sorted(
            {str(i.get("dataDisponibilizacao") or "") for i in publicacoes if i.get("dataDisponibilizacao")}
        )
        for item in publicacoes:
            unidade = vara_do_processo(item.get("numeroProcesso"))
            if not unidade or unidade == UNIDADE_DO_TRIBUNAL or not _e_substantiva(item):
                continue
            por_vara.setdefault(unidade, set()).add(
                re.sub(r"\D", "", str(item.get("numeroProcesso") or ""))
            )
        if datas:
            print(f"janela coletada: {datas[0]} a {datas[-1]} ({len(datas)} dias com publicação)")
        print("")
        print("varas com mais processos distintos:")
        for unidade, processos in sorted(por_vara.items(), key=lambda kv: -len(kv[1]))[:15]:
            print(f"  vara {unidade}: {len(processos)} processos")
        print("")
        print(
            "Se a maior não alcança o que a base pede, o gargalo é a JANELA do "
            "coletor, e não este recorte: rode `-m scripts.coletar_djen_trts "
            f"--tribunal {args.tribunal} --dias 365` e prepare de novo."
        )
        return 0

    vara = re.sub(r"\D", "", args.vara).zfill(4) if args.vara else ""
    if not vara:
        vara, data = escolher_vara(publicacoes)
        if not vara:
            print("Nenhuma publicação de 1º grau com número CNJ legível — nada a preparar.")
            return 1
        print(f"Última vara a publicar: {vara} (publicação de {data})")
    else:
        print(f"Vara pedida: {vara}")

    escolhidas, contagem = montar(publicacoes, vara, args.quantos)
    if not escolhidas:
        print(f"A vara {vara} não tem publicação substantiva no que foi coletado.")
        return 1

    saida = Path(args.saida)
    saida.write_text(
        json.dumps(escolhidas, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    print(
        f"\npublicações da vara .............. {contagem.get('da_vara', 0)}"
        f"\ndescartadas pela limpeza ........ {contagem.get('descartadas_pela_limpeza', 0)}"
        f"  (distribuição/pauta/expediente, ou < {MIN_CARACTERES} caracteres)"
        f"\npublicações do mesmo processo .... {contagem.get('duplicidades_do_mesmo_processo', 0)}"
        f"  (fica a mais recente de cada)"
        f"\nprocessos distintos ............. {contagem.get('processos_distintos', 0)}"
        f"\ngravados em {saida} ............. {len(escolhidas)}"
    )
    if len(escolhidas) < args.quantos:
        print(
            f"\nATENÇÃO: a vara {vara} rendeu {len(escolhidas)} processos, menos que os "
            f"{args.quantos} pedidos. Amplie a janela do coletor (--dias) ou escolha "
            f"outra vara — completar com processos de outro juízo desmontaria o "
            f"recorte, que é a razão de a base existir."
        )
    print(
        "\nPróximo passo (precisa alcançar o pgvector em DATABASE_URL):"
        f"\n  .venv\\Scripts\\python.exe -m scripts.ingerir_jurimetria_geral --arquivo {saida}"
        "\n  .venv\\Scripts\\python.exe -m scripts.vetorizar_pendentes"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
