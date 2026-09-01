r"""A fila da carteira paginada: o que muda de página e o que não pode mudar.

Exercita `carteira.compor`, que é pura — recebe o cadastro e as entregas já lidos e
devolve a página. Nada de banco.

O que precisa de prova aqui:

- **a página tem o tamanho pedido** e a última traz só o resto;
- **a ordem por risco é global.** O caso crítico da carteira aparece na página 1 mesmo
  tendo sido cadastrado por último — senão "o que pode travar aparece primeiro" viraria
  "o que pode travar aparece primeiro dentro da página que você abriu";
- **a triagem não é paginada.** Os contadores do topo são os mesmos na página 1 e na
  página 3; se mudassem, o número lido dependeria de onde o usuário parou;
- **página além do fim não devolve lista vazia** — é presa à última.

    .venv\Scripts\python.exe -m tests.test_carteira_paginacao
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import carteira, categorias  # noqa: E402

falhas = 0

AGORA = datetime.now(timezone.utc)
CATEGORIA = "doenca_ocupacional"
OBRIGATORIOS = [item.codigo for item in categorias.obter(CATEGORIA).itens if item.obrigatorio]


def checar(condicao: bool, descricao: str, detalhe: str = "") -> None:
    global falhas
    if condicao:
        print(f"  PASS  {descricao}")
    else:
        falhas += 1
        print(f"  FALHA {descricao}" + (f"\n          {detalhe}" if detalhe else ""))


def caso(indice: int, dias_parado: float) -> dict:
    quando = (AGORA - timedelta(days=dias_parado)).isoformat()
    return {
        "id": f"caso-{indice:02d}",
        "cliente": f"Cliente {indice:02d}",
        "categoria": CATEGORIA,
        "criado_em": quando,
        "atualizado_em": quando,
    }


def entrega_ok(caso_id: str, item: str) -> dict:
    return {
        "id": f"{caso_id}-{item}",
        "caso_id": caso_id,
        "item_codigo": item,
        "arquivo": f"{item}.pdf",
        "itens_atendidos": [item],
        "tipo_confere": True,
        "dados_utilizaveis": True,
        "confirmado_manual": False,
        "score_legibilidade": 90,
        "veredito": None,
        "status_proc": "pronto",
        "erro_proc": None,
        "criado_em": (AGORA - timedelta(hours=1)).isoformat(),
    }


# 25 casos: os 5 primeiros completos (severidade "pronto"), o resto sem documento
# nenhum. Só o último cadastrado está parado há tempo de virar cobrança.
cadastro = [caso(i, dias_parado=0) for i in range(25)]
cadastro[24] = caso(24, dias_parado=30)
entregas = {
    f"caso-{i:02d}": [entrega_ok(f"caso-{i:02d}", item) for item in OBRIGATORIOS]
    for i in range(5)
}

pagina1 = carteira.compor(cadastro, entregas, pagina=1, tamanho=10)
pagina3 = carteira.compor(cadastro, entregas, pagina=3, tamanho=10)
alem = carteira.compor(cadastro, entregas, pagina=99, tamanho=10)

print("\nPaginação")
checar(len(pagina1["situacoes"]) == 10, "página 1 traz 10 casos", str(len(pagina1["situacoes"])))
checar(pagina1["paginas"] == 3 and pagina1["total"] == 25, "3 páginas para 25 casos")
checar(len(pagina3["situacoes"]) == 5, "a última página traz o resto (5)", str(len(pagina3["situacoes"])))
checar(alem["pagina"] == 3 and len(alem["situacoes"]) == 5, "página além do fim cai na última")

vistos = [s["caso"]["id"] for p in (pagina1, pagina3) for s in p["situacoes"]]
checar(len(set(vistos)) == len(vistos), "nenhum caso aparece em duas páginas")

print("\nOrdem por risco, medida na carteira inteira")
primeiro = pagina1["situacoes"][0]["caso"]["id"]
checar(primeiro == "caso-24", "o caso a cobrar (último cadastrado) abre a página 1", primeiro)

print("\nTriagem — a mesma em qualquer página")
checar(pagina1["triagem"] == pagina3["triagem"], "contadores não mudam ao virar de página")
checar(pagina1["triagem"]["ativos"] == 25, "ativos conta a carteira toda", str(pagina1["triagem"]["ativos"]))
checar(pagina1["triagem"]["completos"] == 5, "completos conta a carteira toda", str(pagina1["triagem"]["completos"]))
checar(pagina1["triagem"]["travados"] == 1, "travados conta a carteira toda", str(pagina1["triagem"]["travados"]))
checar(
    pagina1["triagem"]["pedidosProntos"] == 20,
    "pedidos pendentes contam a carteira toda",
    str(pagina1["triagem"]["pedidosProntos"]),
)

print("\nPainéis laterais — também da carteira toda")
checar(len(pagina1["chegando_agora"]) == 4, "chegando agora traz as 4 últimas entregas")
checar(pagina1["chegando_agora"] == pagina3["chegando_agora"], "chegando agora não muda com a página")
checar(len(pagina1["pedidos"]) == 4, "pedidos traz 4")
checar(pagina1["pedidos"][0]["casoId"] == "caso-24", "o primeiro pedido é o caso a cobrar")

print(f"\n{'FALHAS: ' + str(falhas) if falhas else 'Tudo verde.'}")
sys.exit(1 if falhas else 0)
