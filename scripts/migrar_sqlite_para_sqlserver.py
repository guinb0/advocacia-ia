"""Leva o conteúdo do `dados/casos.db` para o SQL Server.

Roda uma vez, na virada. Depois disso o SQLite fica como estava — não é apagado, e é o
que permite conferir depois se algo não bateu, ou voltar atrás enquanto a confiança no
destino não estiver formada.

    python scripts/migrar_sqlite_para_sqlserver.py --conferir   # só compara as contagens
    python scripts/migrar_sqlite_para_sqlserver.py --migrar

Idempotente: registro já presente no destino é pulado pelo `id`, então rodar de novo
não duplica nada. As tabelas vão na ordem da dependência — caso antes de entrega, senão
a chave estrangeira recusa.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app import banco  # noqa: E402

ORIGEM = RAIZ / "dados" / "casos.db"

# Ordem de dependência: `casos` primeiro; o resto aponta para ele.
TABELAS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "casos",
        (
            "id",
            "cliente",
            "categoria",
            "observacao",
            "criado_em",
            "atualizado_em",
            "portal_token",
            "portal_senha_hash",
            "portal_sal",
            "portal_criado_em",
        ),
    ),
    (
        "entregas",
        (
            "id",
            "caso_id",
            "item_codigo",
            "arquivo",
            "caminho",
            "tipo_detectado",
            "tipo_confere",
            "veredito",
            "dados_utilizaveis",
            "confirmado_manual",
            "score_legibilidade",
            "itens_atendidos",
            "extracao_json",
            "criado_em",
            "status_proc",
            "erro_proc",
        ),
    ),
    (
        "entrevistas",
        (
            "id",
            "caso_id",
            "arquivo",
            "caminho",
            "texto",
            "realizada_em",
            "entrevistador",
            "resumo",
            "perguntas",
            "fatos_gerados",
            "enviada_em",
            "criado_em",
        ),
    ),
    (
        "assinaturas",
        (
            "id",
            "doc_token",
            "nome",
            "cliente",
            "caso_id",
            "estado",
            "signatarios",
            "arquivo",
            "criado_em",
            "atualizado_em",
            "cpf",
        ),
    ),
    (
        "vinculos_agente",
        (
            "caso_id",
            "caso_ref",
            "cliente_ref",
            "enviados",
            "ultimo_erro",
            "criado_em",
            "atualizado_em",
        ),
    ),
)

CHAVE = {"vinculos_agente": "caso_id"}


def _origem() -> sqlite3.Connection:
    if not ORIGEM.exists():
        sys.exit(f"não encontrei o banco de origem: {ORIGEM}")
    conexao = sqlite3.connect(ORIGEM)
    conexao.row_factory = sqlite3.Row
    return conexao


def conferir() -> int:
    origem = _origem()
    print(f"{'tabela':<18} {'SQLite':>8} {'SQL Server':>12}")
    print("-" * 40)
    with banco.conectar() as destino:
        for tabela, _ in TABELAS:
            antes = origem.execute(f'SELECT count(*) FROM "{tabela}"').fetchone()[0]
            depois = destino.execute(f"SELECT count(*) FROM {tabela}").fetchone()[0]
            marca = "" if antes == depois else "  <-- diferente"
            print(f"{tabela:<18} {antes:>8} {depois:>12}{marca}")
    origem.close()
    return 0


def migrar() -> int:
    origem = _origem()
    total = 0

    with banco.conectar() as destino:
        for tabela, colunas in TABELAS:
            chave = CHAVE.get(tabela, "id")
            existentes = {
                linha[chave] for linha in destino.execute(f"SELECT {chave} FROM {tabela}")
            }

            linhas = origem.execute(f'SELECT * FROM "{tabela}"').fetchall()
            novas = [linha for linha in linhas if linha[chave] not in existentes]
            if not novas:
                print(f"  {tabela:<18} nada a levar ({len(linhas)} já no destino)")
                continue

            marcadores = ", ".join("?" for _ in colunas)
            sql = f"INSERT INTO {tabela} ({', '.join(colunas)}) VALUES ({marcadores})"
            for linha in novas:
                # `linha.keys()` porque o SQLite antigo pode não ter todas as colunas —
                # o destino tem default para elas, então o ausente vira o padrão.
                presentes = set(linha.keys())
                valores = [linha[c] if c in presentes else None for c in colunas]
                destino.execute(sql, valores)

            print(f"  {tabela:<18} {len(novas)} registros migrados")
            total += len(novas)

    origem.close()
    print(f"\n{total} registros levados para o SQL Server")
    return 0


def main() -> int:
    if "--conferir" in sys.argv:
        return conferir()
    if "--migrar" in sys.argv:
        return migrar()
    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
