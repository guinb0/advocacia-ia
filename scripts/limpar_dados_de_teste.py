"""Tira do banco o que as execuções de teste deixaram para trás.

POR QUE ISTO EXISTE

Oito testes acreditavam redirecionar o banco mexendo em
`armazenamento.CAMINHO_BANCO` — o que valia no tempo do SQLite e deixou de valer
na migração para o SQL Server (ver `tests/banco_de_teste.py`, que hoje impede
isso). Até a trava existir, cada execução criava casos de verdade no banco de
verdade, e quando um teste quebrava no meio o que ele tinha criado ficava lá.

Medido em 12/09/2026: **276 dos 348 casos** do banco eram fixtures de teste, com
376 entregas e 47 entrevistas penduradas neles. Eles contam nos totais do painel,
aparecem na carteira e poluem qualquer medição do escritório.

COMO ESTE SCRIPT DECIDE O QUE É TESTE

Não por heurística: cada nome da lista abaixo está escrito LITERALMENTE em um
arquivo de `tests/`. Foi assim que a lista foi montada, e é assim que ela deve
crescer — nome que não aparece num teste não entra aqui. Nada de "parece nome de
teste": um cliente de verdade pode se chamar Marcos Costa.

SEGURANÇA

- Por padrão ele NÃO apaga nada: lista o que faria e sai. Só com `--confirmar`.
- Antes de apagar, grava um JSON com as linhas removidas, para dar para voltar.
- Apaga pelo `armazenamento.excluir_caso`, que é o caminho que o próprio sistema
  usa: leva as entregas e a pasta de arquivos do caso junto.

Uso:
  .venv\\Scripts\\python.exe -m scripts.limpar_dados_de_teste            # só lista
  .venv\\Scripts\\python.exe -m scripts.limpar_dados_de_teste --confirmar
  .venv\\Scripts\\python.exe -m scripts.limpar_dados_de_teste --confirmar --glossario
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import armazenamento, tipos_documento  # noqa: E402
from app.banco import conectar  # noqa: E402

#: Cada nome está escrito num arquivo de `tests/` — conferido um por um.
#: A coluna da direita é onde ele aparece, para o próximo leitor poder checar.
CLIENTES_DE_TESTE: tuple[tuple[str, str], ...] = (
    ("Maria Aparecida", "test_agente.py, test_assinatura.py, test_casos.py"),
    ("Maria Santos", "test_agente.py, test_conversas.py"),
    ("Jose Orfao", "test_agente.py"),
    ("José Orfao", "test_agente.py"),
    ("Vinculo Morto Confirmado", "test_agente.py"),
    ("Vinculo Antigo", "test_agente.py"),
    ("Vinculo Orfao", "test_agente.py"),
    ("Jose da Silva", "test_casos.py"),
    ("José da Silva", "test_casos.py"),
    ("Joao Carteiro", "test_casos.py"),
    ("João Carteiro", "test_casos.py"),
    ("Maria Segurada", "test_casos.py"),
    ("Joao da CIN", "test_casos.py"),
    ("João da CIN", "test_casos.py"),
    ("Ana da CIN", "test_casos.py"),
    ("Marcos Costa", "test_entrevista.py"),
    ("Maria dos Uploads", "test_uploads_api.py"),
    ("Joana do Roteamento", "test_roteamento_documentos.py"),
    ("Ana / Zíper", "test_zip_selecao.py"),
    ("Ana / Ziper", "test_zip_selecao.py"),
)

#: Tipos de documento criados enquanto alguém experimentava a tela do glossário.
#:
#: Diferente dos casos, um tipo de documento aparece no CHECKLIST DO CLIENTE: o
#: "teste2" estava marcado em três categorias, então o cliente via "teste2" na
#: lista do que precisa enviar.
#:
#: O código aqui é o do TIPO (`teste2`), não o do item de checklist
#: (`GLOS.teste2`) — o prefixo é acrescentado por `categorias.codigo_item_do_glossario`
#: quando o tipo entra no checklist.
CODIGOS_DE_TESTE_NO_GLOSSARIO: tuple[str, ...] = ("teste2",)


def _nomes() -> list[str]:
    return [nome for nome, _onde in CLIENTES_DE_TESTE]


def levantar_casos() -> list[dict[str, Any]]:
    nomes = _nomes()
    with conectar() as con:
        marcas = ",".join("?" * len(nomes))
        return [
            dict(linha)
            for linha in con.execute(
                f"SELECT * FROM casos WHERE cliente IN ({marcas}) ORDER BY cliente, criado_em",
                nomes,
            ).fetchall()
        ]


def contar_dependentes(ids: list[str]) -> dict[str, int]:
    """Quantas linhas penduradas nesses casos — o tamanho real do estrago."""
    if not ids:
        return {}
    contagem: dict[str, int] = {}
    with conectar() as con:
        marcas = ",".join("?" * len(ids))
        for tabela in ("entregas", "entrevistas", "peticoes_locais", "peticoes_anexas", "assinaturas"):
            try:
                linha = con.execute(
                    f"SELECT COUNT(*) AS n FROM {tabela} WHERE caso_id IN ({marcas})", ids
                ).fetchone()
                contagem[tabela] = int(linha["n"]) if linha else 0
            except Exception:  # noqa: BLE001 - tabela que ainda não existe neste banco
                continue
    return contagem


def levantar_glossario() -> list[dict[str, Any]]:
    achados = []
    for codigo in CODIGOS_DE_TESTE_NO_GLOSSARIO:
        tipo = tipos_documento.obter(codigo)
        if tipo:
            achados.append(tipo)
    return achados


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--confirmar",
        action="store_true",
        help="apaga de verdade. Sem isto, apenas lista o que seria apagado.",
    )
    p.add_argument(
        "--glossario",
        action="store_true",
        help="também desativa os tipos de documento de teste (ex.: GLOS.teste2).",
    )
    p.add_argument("--backup", default="", help="onde gravar o JSON do que for apagado.")
    args = p.parse_args()

    casos = levantar_casos()
    ids = [str(c["id"]) for c in casos]
    dependentes = contar_dependentes(ids)
    with conectar() as con:
        total = int(con.execute("SELECT COUNT(*) AS n FROM casos").fetchone()["n"])

    print(f"casos no banco: {total}")
    print(f"casos de teste encontrados: {len(casos)}\n")
    for nome, quantos in Counter(str(c["cliente"]) for c in casos).most_common():
        onde = next((o for n, o in CLIENTES_DE_TESTE if n == nome), "")
        print(f"  {quantos:4}x  {nome:28} ({onde})")
    if dependentes:
        print("\n  penduradas neles: " + ", ".join(f"{n} em {t}" for t, n in dependentes.items()))
    print(f"\ncasos que sobrariam: {total - len(casos)}")

    tipos = levantar_glossario() if args.glossario else []
    if args.glossario:
        print(f"\ntipos de documento de teste: {len(tipos)}")
        for tipo in tipos:
            print(f"  {tipo.get('codigo')} — {tipo.get('nome')} (ativo={tipo.get('ativo')})")

    if not args.confirmar:
        print("\n--- NADA FOI APAGADO ---")
        print("Rode de novo com --confirmar (e --glossario, se quiser os tipos) para apagar.")
        return 0

    if not casos and not tipos:
        print("\nNada a apagar.")
        return 0

    destino = Path(
        args.backup
        or f"backup-dados-de-teste-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.json"
    )
    destino.write_text(
        json.dumps(
            {"casos": casos, "tipos_documento": tipos, "dependentes": dependentes},
            ensure_ascii=False,
            indent=1,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"\nbackup gravado em {destino}")

    inicio = time.time()
    apagados = 0
    for caso in casos:
        if armazenamento.excluir_caso(str(caso["id"])):
            apagados += 1
        if apagados % 25 == 0 and apagados:
            print(f"  {apagados}/{len(casos)}…")
    print(f"casos apagados: {apagados} em {time.time() - inicio:.0f}s")

    # O tipo de documento é DESATIVADO, não excluído: `editar` recusa apagar tipo
    # com documento classificado nele, e desativar já o tira do checklist do
    # cliente, que é o que importa. O histórico da edição fica registrado.
    for tipo in tipos:
        try:
            tipos_documento.editar(
                str(tipo["codigo"]),
                nome=str(tipo["nome"]),
                descricao=str(tipo.get("descricao") or ""),
                sinonimos=tipo.get("sinonimos") or [],
                ativo=False,
                versao=int(tipo.get("versao") or 1),
                usuario="limpeza de dados de teste",
                motivo="tipo criado em teste; não pertence ao checklist do cliente",
            )
            print(f"tipo desativado: {tipo['codigo']}")
        except Exception as erro:  # noqa: BLE001 - um tipo travado não impede os outros
            print(f"tipo {tipo['codigo']} NÃO foi desativado: {str(erro)[:160]}")

    with conectar() as con:
        restantes = int(con.execute("SELECT COUNT(*) AS n FROM casos").fetchone()["n"])
    print(f"\ncasos restantes no banco: {restantes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
