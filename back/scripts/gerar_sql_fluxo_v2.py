"""Gera `sql/012_fluxo_atendimento_v2.sql` a partir das definições portáveis.

O app cria estas tabelas sozinho no startup; o arquivo existe para o DBA que
prefere aplicar antes (ou conferir o que será criado). Rode de `back/`:

    python -m scripts.gerar_sql_fluxo_v2
"""

from __future__ import annotations

from pathlib import Path

from app import alertas, analise_acoes, atendimentos, banco, criterios_caso, whatsapp_modelos
from app.esquema_portavel import ddl_sqlserver

DESTINO = Path(__file__).resolve().parent.parent / "sql" / "012_fluxo_atendimento_v2.sql"

CABECALHO = """-- Fluxo de atendimento v2: agenda, presença, alertas, modelos de WhatsApp,
-- critérios dos tipos de caso, análise pós-entrevista.
-- Executar no SQL Server do app (schema dbo).
--
-- ADITIVA E IDEMPOTENTE: só cria o que não existe (IF OBJECT_ID / COL_LENGTH).
-- Nenhuma coluna existente muda, nenhum dado é apagado. O app também cria tudo
-- isto no startup; aplicar antes só adianta o trabalho.
-- Gerado por scripts/gerar_sql_fluxo_v2.py — edite as definições em Python, não aqui.
"""


def gerar() -> str:
    partes = [CABECALHO]
    for modulo in (atendimentos, alertas, whatsapp_modelos, criterios_caso, analise_acoes):
        for tabela in modulo.TABELAS:
            partes.append(f"\n-- {tabela.nome}")
            partes.extend(f"{instrucao}\nGO" for instrucao in ddl_sqlserver(tabela))
    partes.append(f"\n-- {banco.SCHEMA}.{banco.PREFIXO}automacoes_whatsapp: ciclo de entrega")
    for tabela, coluna, definicao in banco.COLUNAS_NOVAS:
        if tabela == f"{banco.PREFIXO}automacoes_whatsapp" and coluna in (
            "status_entrega", "mensagem_id", "atendimento_id", "texto_resumo", "entregue_em", "lido_em",
        ):
            nome = f"{banco.SCHEMA}.{tabela}"
            partes.append(
                f"IF COL_LENGTH('{nome}', '{coluna}') IS NULL ALTER TABLE {nome} ADD {coluna} {definicao}\nGO"
            )
    return "\n".join(partes) + "\n"


if __name__ == "__main__":
    DESTINO.write_text(gerar(), encoding="utf-8")
    print(f"Gravado: {DESTINO}")
