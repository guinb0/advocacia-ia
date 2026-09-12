"""Trava que impede um teste de escrever no banco de produção.

O QUE ACONTECIA

Oito testes abrem com três linhas parecidas com estas:

    armazenamento.DIR_DADOS = _TEMP
    armazenamento.CAMINHO_BANCO = _TEMP / "casos.db"   # "não encosta no banco real"

Isso funcionava no tempo do SQLite, quando `CAMINHO_BANCO` era de fato o banco.
Depois da migração para o SQL Server (`app/banco.py`), a conexão passou a vir de
`SQLSERVER_*` e `CAMINHO_BANCO` virou uma constante que ninguém lê — a linha
continuou ali, dizendo que redirecionava, sem redirecionar nada.

Resultado: quem rodasse `tests/test_casos.py` numa máquina com `.env` de verdade
criava e apagava casos no banco de PRODUÇÃO. E quando o teste quebrava no meio,
o que ele tinha criado ficava lá: "Vinculo Morto Confirmado", "Jose Orfao",
"Maria dos Uploads", "Ana da CIN" e companhia, misturados aos casos do
escritório, contando nos totais do painel.

O QUE ESTA TRAVA FAZ

Chamada no topo do teste, ela recusa rodar quando o banco configurado não é
reconhecidamente de teste — em vez de descobrir o estrago depois, pela listagem
de casos. Não adivinha nada: o nome do banco tem de dizer que é de teste.

COMO RODAR ESSES TESTES

Aponte para um banco descartável (o nome precisa conter "teste" ou "test"):

    SQLSERVER_DATABASE=advocacia_teste .venv/Scripts/python.exe tests/test_casos.py

E, se for realmente a intenção usar o banco de verdade — por exemplo para
reproduzir um defeito que só aparece com os dados dele —, é preciso dizer isso em
voz alta:

    ACERVO_TESTE_BANCO_REAL=1 .venv/Scripts/python.exe tests/test_casos.py
"""

from __future__ import annotations

import os
import sys

__all__ = ["exigir_banco_de_teste"]

#: O nome do banco precisa conter um destes para ser aceito como descartável.
_MARCAS_DE_TESTE = ("teste", "test", "sandbox", "local")


def exigir_banco_de_teste() -> None:
    """Interrompe o teste se o banco configurado não for de teste."""
    if os.getenv("ACERVO_TESTE_BANCO_REAL", "").strip() == "1":
        print(
            "AVISO: rodando contra o banco REAL a pedido (ACERVO_TESTE_BANCO_REAL=1).\n"
            "       O que este teste criar e não apagar fica lá.",
            file=sys.stderr,
        )
        return

    # `app.banco` é quem carrega o `.env` da raiz; sem isto o nome do banco viria
    # vazio numa máquina que não exporta as variáveis à mão.
    try:
        from app import banco

        banco._carregar_env()
    except Exception:  # pragma: no cover - sem .env, segue com o ambiente cru
        pass

    nome = (os.getenv("SQLSERVER_DATABASE") or "").strip()
    if nome and any(marca in nome.casefold() for marca in _MARCAS_DE_TESTE):
        return

    print(
        "\n"
        "Este teste ESCREVE no banco, e o banco configurado não é de teste\n"
        f"  SQLSERVER_DATABASE = {nome or '(vazio — usaria o padrão `advocacia`)'}\n"
        "\n"
        "Rodá-lo assim cria e apaga casos no banco de produção, e o que ele criar\n"
        "antes de uma falha fica lá. Aponte para um banco descartável:\n"
        "\n"
        "  SQLSERVER_DATABASE=advocacia_teste .venv/Scripts/python.exe " + " ".join(sys.argv) + "\n"
        "\n"
        "Ou, se o banco real for mesmo a intenção, diga isso explicitamente:\n"
        "\n"
        "  ACERVO_TESTE_BANCO_REAL=1 .venv/Scripts/python.exe " + " ".join(sys.argv) + "\n",
        file=sys.stderr,
    )
    raise SystemExit(2)
