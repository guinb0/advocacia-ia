r"""Os filtros da carteira agem no servidor, sobre a carteira INTEIRA.

O problema que resolvem: a lista vinha paginada de 10 em 10 e o filtro só olhava a
página aberta — buscar um cliente que estava na página 4 não achava nada. Aqui a
busca, a categoria e a situação recortam antes de paginar; os contadores do topo
seguem medindo o escritório todo.

    .venv\Scripts\python.exe -m tests.test_carteira_filtros
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import carteira, categorias  # noqa: E402

falhas = 0
AGORA = datetime.now(timezone.utc)
CAT_A = "doenca_ocupacional"
CAT_B = "acidente_trabalho_correios"
OBRIG_A = [i.codigo for i in categorias.obter(CAT_A).itens if i.obrigatorio]


def checar(condicao: bool, descricao: str, detalhe: str = "") -> None:
    global falhas
    if condicao:
        print(f"  PASS  {descricao}")
    else:
        falhas += 1
        print(f"  FALHA {descricao}" + (f"\n          {detalhe}" if detalhe else ""))


def caso(indice: int, categoria: str, cliente: str, dias: float = 0) -> dict:
    quando = (AGORA - timedelta(days=dias)).isoformat()
    return {
        "id": f"caso-{indice:02d}",
        "cliente": cliente,
        "categoria": categoria,
        "observacao": "",
        "criado_em": quando,
        "atualizado_em": quando,
    }


def entrega_ok(caso_id: str, item: str) -> dict:
    return {
        "id": f"{caso_id}-{item}", "caso_id": caso_id, "item_codigo": item,
        "arquivo": f"{item}.pdf", "itens_atendidos": [item], "tipo_confere": True,
        "dados_utilizaveis": True, "confirmado_manual": False, "score_legibilidade": 90,
        "veredito": None, "status_proc": "pronto", "erro_proc": None,
        "criado_em": (AGORA - timedelta(hours=1)).isoformat(),
    }


# 12 casos da categoria A + 3 da B. Um cliente com nome fácil de buscar. Os 5
# primeiros de A estão completos; o resto, sem documento.
cadastro = [caso(i, CAT_A, f"Cliente {i:02d}") for i in range(12)]
cadastro += [caso(100 + j, CAT_B, f"Carteiro {j:02d}") for j in range(3)]
cadastro[7] = caso(7, CAT_A, "Maria das Graças Souza")
entregas = {f"caso-{i:02d}": [entrega_ok(f"caso-{i:02d}", it) for it in OBRIG_A] for i in range(5)}

base = carteira.compor(cadastro, entregas, pagina=1, tamanho=10)

print("\nBusca por nome — acha em qualquer página, ignorando acento e caixa")
r = carteira.compor(cadastro, entregas, busca="gracas", tamanho=10)
ids = [s["caso"]["id"] for s in r["situacoes"]]
checar(r["total"] == 1 and ids == ["caso-07"], "'gracas' acha 'Maria das Graças'", str(ids))
checar(r["triagem"] == base["triagem"], "os contadores do topo não mudam com a busca")

print("\nFiltro por categoria")
r = carteira.compor(cadastro, entregas, categoria=CAT_B, tamanho=50)
checar(r["total"] == 3, "só os 3 casos da categoria B", str(r["total"]))
checar(all(s["caso"]["categoria"] == CAT_B for s in r["situacoes"]), "todos são da B")

print("\nFiltro por situação (mesmo vocabulário dos chips)")
r = carteira.compor(cadastro, entregas, situacao="pronto", tamanho=50)
checar(r["total"] == 5, "5 casos completos", str(r["total"]))

print("\nOrdenação por nome")
r = carteira.compor(cadastro, entregas, ordenar="nome", tamanho=50)
primeiro = r["situacoes"][0]["caso"]["cliente"]
checar(primeiro.startswith("Carteiro 00"), "A-Z começa em 'Carteiro 00'", primeiro)

print("\nCategorias oferecidas à tela")
codigos = {c["codigo"] for c in base["categorias"]}
checar({CAT_A, CAT_B} <= codigos, "a lista traz as categorias presentes", str(codigos))

print(f"\n{'FALHAS: ' + str(falhas) if falhas else 'Tudo verde.'}")
sys.exit(1 if falhas else 0)
