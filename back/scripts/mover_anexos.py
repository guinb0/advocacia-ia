"""Move anexos que estão no caso errado para o caso da pessoa certa.

O CASO QUE PEDIU ISTO

No caso `da5a030b` (cliente GUILHERME NUNES BEZERRA) estavam 46 anexos de OUTRA
pessoa — HILDEBRANDO ALMEIDA DE ANDRADE, com acidente, hospital e notas fiscais
próprios. A análise dos documentos percebeu e disse com todas as letras
("incompatibilidade total entre o relato e a prova documental"), mas enquanto os
arquivos ficam ali toda leitura do caso mistura duas histórias: a cronologia soma
fatos de dois acidentes, a petição herda lesões que não são do cliente, e a
jurimetria busca precedentes pelo estado errado.

POR QUE MOVER E NÃO APAGAR

O documento é de alguém: apagar joga fora prova que talvez pertença a um caso que
ainda vai existir. E não há risco de perder o arquivo no caminho — o binário mora
no BANCO (`entregas.conteudo`, com `conteudo_sha256` conferido antes e depois, ver
`armazenamento.caminho_duravel_da_entrega`), não apenas na pasta local. Trocar o
`caso_id` leva o documento inteiro junto.

O QUE ELE NÃO FAZ

Não mexe na petição nem na análise já gravadas no caso de origem. Elas foram
escritas a partir dos documentos que estão saindo, então depois de mover é preciso
gerar de novo — a versão antiga fica no histórico.

Uso:
  .venv\\Scripts\\python.exe -m scripts.mover_anexos --caso da5a030b-... --prefixo HILDEBRANDO
  .venv\\Scripts\\python.exe -m scripts.mover_anexos --caso da5a030b-... --prefixo HILDEBRANDO \\
      --para "HILDEBRANDO ALMEIDA DE ANDRADE" --confirmar
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import armazenamento  # noqa: E402
from app.banco import conectar  # noqa: E402


def anexos_com_prefixo(caso_id: str, prefixo: str) -> list[dict[str, Any]]:
    """Os anexos daquele caso cujo nome de arquivo começa com o prefixo."""
    prefixo = prefixo.strip()
    with conectar() as con:
        linhas = con.execute(
            "SELECT id, arquivo, item_codigo, criado_em FROM entregas"
            " WHERE caso_id = ? ORDER BY arquivo",
            (caso_id,),
        ).fetchall()
    return [
        dict(linha)
        for linha in linhas
        if str(linha["arquivo"] or "").upper().startswith(prefixo.upper())
    ]


def caso_por_nome(nome: str, categoria: str) -> dict[str, Any] | None:
    """Um caso já existente para aquele cliente na mesma categoria, se houver."""
    with conectar() as con:
        linha = con.execute(
            "SELECT TOP 1 id, cliente, categoria FROM casos"
            " WHERE cliente = ? AND categoria = ? ORDER BY criado_em",
            (nome, categoria),
        ).fetchone()
    return dict(linha) if linha else None


def mover(entrega_ids: list[str], destino_id: str) -> int:
    """Troca o caso de cada anexo. O binário vai junto: ele mora no banco."""
    if not entrega_ids:
        return 0
    with conectar() as con:
        marcas = ",".join("?" * len(entrega_ids))
        cursor = con.execute(
            f"UPDATE entregas SET caso_id = ? WHERE id IN ({marcas})",
            [destino_id, *entrega_ids],
        )
        movidos = cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else len(entrega_ids)
        # Os dois casos mudaram de conteúdo: o `atualizado_em` é o que invalida o
        # cache da análise de documentos (ver `analise_documentos.analisar`).
        agora = armazenamento.agora()
        con.execute(
            "UPDATE casos SET atualizado_em = ? WHERE id = ?", (agora, destino_id)
        )
    return movidos


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--caso", required=True, help="id do caso de ONDE os anexos saem.")
    p.add_argument(
        "--prefixo",
        required=True,
        help="começo do nome do arquivo que identifica os anexos (ex.: HILDEBRANDO).",
    )
    p.add_argument(
        "--para",
        default="",
        help="nome do cliente do caso de DESTINO. Vazio = usa o prefixo como nome.",
    )
    p.add_argument("--confirmar", action="store_true", help="move de verdade.")
    args = p.parse_args()

    origem = armazenamento.obter_caso(args.caso)
    if origem is None:
        print(f"Caso {args.caso} não encontrado.")
        return 1

    achados = anexos_com_prefixo(args.caso, args.prefixo)
    total = len(armazenamento.listar_entregas(args.caso))
    print(f"caso de origem: {origem.get('cliente')} ({origem.get('categoria')})")
    print(f"anexos no caso: {total} | com o prefixo {args.prefixo!r}: {len(achados)}\n")
    for anexo in achados[:12]:
        print(f"  {str(anexo['arquivo'])[:88]}")
    if len(achados) > 12:
        print(f"  … e outros {len(achados) - 12}")

    if not achados:
        print("\nNada a mover.")
        return 0

    nome_destino = (args.para or args.prefixo).strip()
    categoria = str(origem.get("categoria") or "")
    destino = caso_por_nome(nome_destino, categoria)
    print(
        f"\ndestino: {nome_destino!r} — "
        + (f"caso existente {destino['id']}" if destino else "será CRIADO")
    )
    print(f"o caso de origem ficaria com {total - len(achados)} anexos")

    if not args.confirmar:
        print("\n--- NADA FOI MOVIDO ---")
        print("Rode de novo com --confirmar para mover.")
        return 0

    if destino is None:
        destino = armazenamento.criar_caso(
            nome_destino,
            categoria,
            f"Anexos separados do caso {args.caso} ({origem.get('cliente')}).",
        )
        print(f"caso criado: {destino['id']}")

    movidos = mover([str(a["id"]) for a in achados], str(destino["id"]))
    print(f"anexos movidos: {movidos}")
    print(
        "\nA petição e a análise do caso de origem foram escritas com estes documentos:"
        "\ngere de novo para elas refletirem o que sobrou. A versão anterior fica no"
        "\nhistórico."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
