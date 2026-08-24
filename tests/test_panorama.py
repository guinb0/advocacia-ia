"""Panorama do escritório: o que ele soma e o que ele se recusa a inventar.

Exercita `panorama.compor`, que é pura — recebe os casos e o lote já lidos e devolve o
payload. Nada de banco e nada de rede: o que precisa de prova aqui é a regra.

O que está sob teste, e por quê:

- **o funil fecha com o total.** Um caso entra em um estágio só. Funil que soma mais que
  o número de casos não é lido como erro, é lido como "temos mais casos";
- **caso em andamento não entra no ciclo.** A mediana do escritório cairia a cada caso
  novo aberto, e a queda seria comemorada como ganho de velocidade;
- **caso instruído não fica parado.** Senão a lista de ação enche de trabalho concluído;
- **caso fora da leitura não vira caso vazio.** Ele somaria zero hora e puxaria todas as
  medianas para baixo — sai contado em `cobertura`;
- **amostra pequena não vira tendência.** Abaixo do piso, a mediana sai `None` com o
  motivo, e não um número que ninguém sabe que veio de dois casos.

    .venv\\Scripts\\python.exe -m tests.test_panorama
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import categorias, painel, panorama  # noqa: E402

falhas = 0

AGORA = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)

#: Categoria real do catálogo — `situacao_de` consulta `app/categorias.py` de verdade, e
#: um código inventado cairia sempre em "sem checklist".
CATEGORIA = "doenca_ocupacional"

#: Os obrigatórios da categoria, lidos do catálogo real. Fixá-los à mão aqui faria o
#: teste passar a medir uma lista congelada: o dia em que o escritório acrescentasse um
#: documento obrigatório, o caso "completo" do teste continuaria completo e o estágio
#: `instruido` deixaria de ser exercitado sem ninguém notar.
OBRIGATORIOS = [item.codigo for item in categorias.obter(CATEGORIA).itens if item.obrigatorio]


def checar(condicao: bool, descricao: str, detalhe: str = "") -> None:
    global falhas
    if condicao:
        print(f"  PASS  {descricao}")
    else:
        falhas += 1
        print(f"  FALHA {descricao}" + (f"\n          {detalhe}" if detalhe else ""))


def iso(instante: datetime) -> str:
    return instante.isoformat()


def ha(dias: float) -> datetime:
    return AGORA - timedelta(days=dias)


# ------------------------------------------------------------------ fixtures


def caso(caso_id: str, *, aberto_ha: float, categoria: str = CATEGORIA) -> dict:
    return {
        "id": caso_id,
        "cliente": f"Cliente {caso_id}",
        "categoria": categoria,
        "observacao": "",
        "criado_em": iso(ha(aberto_ha)),
        "atualizado_em": iso(ha(aberto_ha)),
        "portal_token": None,
        "portal_criado_em": None,
    }


def entrega(
    caso_id: str,
    item: str,
    *,
    ha_dias: float,
    utilizaveis: bool = True,
    confere: bool | None = True,
    status_proc: str = "pronto",
    score: int | None = 90,
) -> dict:
    return {
        "id": f"{caso_id}-{item}",
        "caso_id": caso_id,
        "item_codigo": item,
        "itens_atendidos": [item],
        "arquivo": f"{item}.jpg",
        "caminho": f"/tmp/{item}.jpg",
        "tipo_detectado": "rg",
        "tipo_confere": confere,
        "veredito": "APROVADO" if utilizaveis else "REPROVADO",
        "dados_utilizaveis": utilizaveis,
        "confirmado_manual": False,
        "score_legibilidade": score,
        "status_proc": status_proc,
        "erro_proc": None,
        "criado_em": iso(ha(ha_dias)),
    }


def checklist_completo(caso_id: str, *, ha_dias: float) -> list[dict]:
    """Uma entrega boa para cada obrigatório da categoria."""
    return [entrega(caso_id, item, ha_dias=ha_dias) for item in OBRIGATORIOS]


def entrevista(
    caso_id: str,
    *,
    ha_dias: float,
    entrevistador: str = "Ana",
    lida: bool = True,
    fatos: int = 12,
) -> dict:
    return {
        "id": f"{caso_id}-entrevista",
        "caso_id": caso_id,
        "arquivo": "entrevista.txt",
        "entrevistador": entrevistador,
        "fatos_gerados": fatos,
        "enviada_em": iso(ha(ha_dias - 0.1)) if lida else None,
        "criado_em": iso(ha(ha_dias)),
    }


def assinatura(caso_id: str, *, enviada_ha: float, assinada_ha: float | None) -> dict:
    """Um contrato enviado para assinatura, e assinado ou não.

    O instante da assinatura mora em `signatarios[].assinou_em` (o `signed_at` da
    ZapSign), não no `atualizado_em` do registro — essa coluna é tocada a cada
    sincronização. O fixture segue o formato real de `_normalizar_assinatura`, senão
    testaria uma forma que o banco não produz.
    """
    return {
        "id": f"{caso_id}-contrato",
        "caso_id": caso_id,
        "estado": "assinado" if assinada_ha is not None else "pendente",
        "signatarios": (
            [
                {
                    "nome": "Cliente",
                    "estado": "assinou",
                    "assinou_em": iso(ha(assinada_ha)),
                }
            ]
            if assinada_ha is not None
            else [{"nome": "Cliente", "estado": "pendente", "assinou_em": None}]
        ),
        "criado_em": iso(ha(enviada_ha)),
        "atualizado_em": iso(ha(assinada_ha if assinada_ha is not None else enviada_ha)),
    }


def lote(
    *,
    entregas: list[dict] | None = None,
    entrevistas: list[dict] | None = None,
    assinaturas: list[dict] | None = None,
    vinculo: dict | None = None,
) -> dict:
    return {
        "entregas": entregas or [],
        "entrevistas": entrevistas or [],
        "assinaturas": assinaturas or [],
        "vinculo": vinculo,
    }


def carteira() -> tuple[list[dict], dict[str, dict]]:
    """Um escritório com um caso em cada estágio e três já instruídos.

    Os três instruídos existem para que a mediana de ciclo tenha amostra: com dois, ela
    tem de sair nula, e é isso que o teste do piso verifica.
    """
    casos = [
        caso("c1", aberto_ha=20),  # sem entrevista
        caso("c2", aberto_ha=14),  # entrevista anexada, nada entregue
        caso("c3", aberto_ha=9),  # tudo entregue, um arquivo a conferir
        caso("c4", aberto_ha=30),  # instruído em 5 dias
        caso("c5", aberto_ha=40),  # instruído em 10 dias
        caso("c6", aberto_ha=50),  # instruído em 15 dias
        caso("c7", aberto_ha=8),  # checklist pronto, contrato pendente
        caso("c8", aberto_ha=6, categoria="categoria_que_saiu_do_codigo"),
        caso("c9", aberto_ha=3),  # fora do lote de propósito
    ]

    a_conferir = checklist_completo("c3", ha_dias=7)
    a_conferir[-1] = entrega("c3", OBRIGATORIOS[-1], ha_dias=7, utilizaveis=False, score=31)

    em_lote = {
        "c1": lote(),
        "c2": lote(entrevistas=[entrevista("c2", ha_dias=12)]),
        "c3": lote(entrevistas=[entrevista("c3", ha_dias=8)], entregas=a_conferir),
        "c4": lote(
            entrevistas=[entrevista("c4", ha_dias=29)],
            entregas=checklist_completo("c4", ha_dias=27),
            assinaturas=[assinatura("c4", enviada_ha=26, assinada_ha=25)],
        ),
        "c5": lote(
            entrevistas=[entrevista("c5", ha_dias=39, entrevistador="Bruno")],
            entregas=checklist_completo("c5", ha_dias=35),
            assinaturas=[assinatura("c5", enviada_ha=31, assinada_ha=30)],
        ),
        "c6": lote(
            entrevistas=[entrevista("c6", ha_dias=49, entrevistador="")],
            entregas=checklist_completo("c6", ha_dias=40),
            assinaturas=[assinatura("c6", enviada_ha=36, assinada_ha=35)],
        ),
        "c7": lote(
            entrevistas=[entrevista("c7", ha_dias=7)],
            entregas=checklist_completo("c7", ha_dias=5),
            assinaturas=[assinatura("c7", enviada_ha=4, assinada_ha=None)],
        ),
        "c8": lote(entrevistas=[entrevista("c8", ha_dias=5)]),
        # "c9" não entra: é o caso que o lote não trouxe.
    }
    return casos, em_lote


def estagio_de(montado: dict, caso_id: str) -> str | None:
    for faixa in montado["funil"]:
        if caso_id in faixa["ids"]:
            return faixa["codigo"]
    return None


# --------------------------------------------------------------------- testes


def main() -> int:
    casos, em_lote = carteira()
    montado = panorama.compor(casos=casos, em_lote=em_lote, agora=AGORA)

    print("== cobertura ==")
    checar(
        montado["cobertura"]["casos_no_acervo"] == 9,
        "a cobertura declara os nove casos do Acervo",
        str(montado["cobertura"]),
    )
    checar(
        montado["cobertura"]["casos_medidos"] == 8
        and montado["cobertura"]["fora_da_leitura"] == 1,
        "o caso que não veio no lote é declarado, não medido como caso vazio",
        str(montado["cobertura"]),
    )
    checar(
        bool(montado["cobertura"]["motivo"]),
        "quando alguém fica de fora, a tela recebe o motivo escrito",
    )

    print("\n== funil ==")
    soma = sum(faixa["casos"] for faixa in montado["funil"])
    checar(soma == 8, "a soma dos estágios fecha com os casos medidos", f"soma={soma}")
    checar(estagio_de(montado, "c1") == "entrevista", "caso sem entrevista aguarda entrevista")
    checar(estagio_de(montado, "c2") == "coleta", "entrevista anexada e sem documento é coleta")
    checar(
        estagio_de(montado, "c3") == "conferencia",
        "obrigatório com arquivo ilegível é conferência, não coleta",
        f"estágio={estagio_de(montado, 'c3')}",
    )
    checar(estagio_de(montado, "c7") == "contrato", "checklist pronto sem assinatura é contrato")
    checar(estagio_de(montado, "c4") == "instruido", "checklist pronto e assinado é instruído")
    checar(
        estagio_de(montado, "c8") == "sem_checklist",
        "categoria que saiu do código não vira estágio inventado",
    )
    aparicoes = sum(1 for faixa in montado["funil"] if "c3" in faixa["ids"])
    checar(aparicoes == 1, "cada caso aparece em um estágio só", f"aparições={aparicoes}")

    print("\n== lista de casos ==")
    por_id = {caso["id"]: caso for caso in montado["casos"]}
    checar(
        len(montado["casos"]) == montado["cobertura"]["casos_medidos"],
        "a lista traz exatamente os casos medidos",
        f"lista={len(montado['casos'])}",
    )
    checar(
        all(faixa_id in por_id for faixa in montado["funil"] for faixa_id in faixa["ids"]),
        "todo id do funil tem um caso na lista — o estágio abre sem segunda leitura",
    )
    checar(
        por_id["c3"]["estagio"] == estagio_de(montado, "c3"),
        "o estágio da lista é o mesmo do funil",
    )
    checar(
        "marcos" not in por_id["c3"] and "entregas" not in por_id["c3"],
        "o material de trabalho das agregações não viaja para a tela",
        str(sorted(por_id["c3"])),
    )

    print("\n== indicadores ==")
    por_codigo = {ind["codigo"]: ind for ind in montado["indicadores"]}
    checar(
        por_codigo["instruidos"]["valor"] == 3,
        "três casos instruídos",
        str(por_codigo["instruidos"]),
    )
    checar(
        por_codigo["em_andamento"]["valor"] == 5,
        "os cinco restantes contam como em andamento",
        str(por_codigo["em_andamento"]),
    )
    ciclo = por_codigo["ciclo_mediano"]
    checar(
        ciclo["valor"] == 10.0,
        "o ciclo mediano é o do meio dos instruídos (5, 10 e 15 dias)",
        str(ciclo),
    )
    checar(
        "instruídos" in ciclo["detalhe"],
        "o ciclo diz sobre quantos casos foi medido",
        ciclo["detalhe"],
    )
    idade = por_codigo["idade_mediana"]
    checar(
        idade["valor"] is not None and idade["valor"] != ciclo["valor"],
        "a idade dos casos em andamento é outra medida, com outro número",
        f"idade={idade['valor']} ciclo={ciclo['valor']}",
    )

    print("\n== ciclo não mistura andamento com conclusão ==")
    poucos_casos, poucos_lotes = casos[:5], {k: v for k, v in em_lote.items() if k in {"c1", "c2", "c3", "c4", "c5"}}
    parcial = panorama.compor(casos=poucos_casos, em_lote=poucos_lotes, agora=AGORA)
    ciclo_parcial = {ind["codigo"]: ind for ind in parcial["indicadores"]}["ciclo_mediano"]
    checar(
        ciclo_parcial["valor"] is None,
        "com dois casos instruídos, a mediana sai nula em vez de virar referência",
        str(ciclo_parcial),
    )
    checar(
        str(panorama._AMOSTRA_MINIMA) in ciclo_parcial["detalhe"],
        "e o motivo diz a partir de quantos casos ela passa a valer",
        ciclo_parcial["detalhe"],
    )

    print("\n== parados ==")
    parados = montado["parados"]
    ids_parados = {item["id"] for item in parados["itens"]}
    checar("c1" in ids_parados, "caso aberto há 20 dias sem movimento aparece como parado")
    checar(
        not {"c4", "c5", "c6"} & ids_parados,
        "caso instruído não entra na lista de parados — não há o que movimentar nele",
        str(ids_parados),
    )
    checar(
        parados["limiar_dias"] == panorama._DIAS_PARADO,
        "o limiar viaja no payload, para a tela poder dizer de onde saiu",
    )
    ordenado = [item["dias"] for item in parados["itens"]]
    checar(ordenado == sorted(ordenado, reverse=True), "os mais antigos vêm primeiro", str(ordenado))

    print("\n== tempo ==")
    tempo = montado["tempo"]
    percentuais = [e["percentual"] for e in tempo["etapas"] if e["percentual"]]
    checar(
        99.0 <= sum(percentuais) <= 101.0,
        "os percentuais das etapas concluídas somam 100",
        f"soma={sum(percentuais)}",
    )
    checar(
        all(e["codigo"] != "ciclo" for e in tempo["etapas"]),
        "o ciclo total fica fora da distribuição — ele contém as outras etapas",
    )
    coleta = next(e for e in tempo["etapas"] if e["codigo"] == "coleta")
    checar(
        coleta["em_curso"] >= 1 and coleta["mais_antigo_horas"] is not None,
        "a coleta que ainda corre é contada à parte, com o caso mais antigo nela",
        str(coleta),
    )
    checar(
        all(
            e["mediana_horas"] is None or e["amostra"] >= panorama._AMOSTRA_MINIMA
            for e in tempo["etapas"]
        ),
        "nenhuma mediana sai sem amostra que a sustente",
        str([(e["codigo"], e["amostra"], e["mediana_horas"]) for e in tempo["etapas"]]),
    )
    checar(
        all(e["motivo"] for e in tempo["etapas"] if e["mediana_horas"] is None),
        "etapa sem mediana explica por quê",
    )

    print("\n== categorias ==")
    categorias = montado["categorias"]
    principal = next(c for c in categorias if c["codigo"] == CATEGORIA)
    checar(
        principal["casos"] == principal["em_andamento"] + principal["instruidos"],
        "dentro da categoria, andamento e instruídos fecham com o total",
        str(principal),
    )
    checar(
        sum(c["casos"] for c in categorias) == 8,
        "a soma das categorias fecha com os casos medidos",
    )
    orfa = next(c for c in categorias if c["codigo"] == "categoria_que_saiu_do_codigo")
    checar(
        orfa["casos"] == 1,
        "o caso de categoria removida continua contado, sob o código gravado nele",
        str(orfa),
    )

    print("\n== movimento ==")
    meses = montado["movimento"]["meses"]
    checar(len(meses) == panorama._MESES_DA_SERIE, "a série cobre doze meses", str(len(meses)))
    checar(
        meses[-1]["mes"] == "2026-08" and meses[-1]["parcial"],
        "o mês corrente é o último e está marcado como incompleto",
        str(meses[-1]),
    )
    checar(
        sum(m["parcial"] for m in meses) == 1,
        "só o mês corrente é parcial",
    )
    checar(
        sum(m["abertos"] for m in meses) == 8,
        "todo caso medido aparece no mês em que foi aberto",
        str([(m["mes"], m["abertos"]) for m in meses]),
    )
    checar(
        sum(m["contratos_assinados"] for m in meses) == 3,
        "os três contratos assinados aparecem no mês da assinatura",
    )

    print("\n== equipe ==")
    equipe = montado["equipe"]
    nomes = {pessoa["nome"] for pessoa in equipe["pessoas"]}
    checar("não informado" in nomes, "entrevista sem entrevistador é agrupada, não escondida")
    checar(
        equipe["total_entrevistas"] == sum(p["entrevistas"] for p in equipe["pessoas"]),
        "a soma por pessoa fecha com o total",
    )
    checar(equipe["sem_atribuicao"] == 1, "e o que está sem atribuição sai contado à parte")

    print("\n== qualidade ==")
    qualidade = montado["qualidade"]
    total_entregas = sum(len(dados["entregas"]) for dados in em_lote.values())
    somado = (
        qualidade["aproveitadas"]
        + qualidade["a_conferir"]
        + qualidade["com_erro"]
        + qualidade["em_leitura"]
    )
    checar(
        qualidade["entregas"] == total_entregas == somado,
        "todo documento recebido cai em exatamente uma classificação",
        f"entregas={qualidade['entregas']} somado={somado} esperado={total_entregas}",
    )
    checar(
        qualidade["a_conferir"] == 1,
        "o único arquivo ilegível da carteira é contado como a conferir",
        str(qualidade),
    )

    print("\n== escritório vazio ==")
    vazio = panorama.compor(casos=[], em_lote={}, agora=AGORA)
    checar(
        all(faixa["casos"] == 0 and faixa["percentual"] is None for faixa in vazio["funil"]),
        "sem caso nenhum, o funil sai zerado sem fatiar o nada",
    )
    checar(
        vazio["tempo"]["total_horas"] == 0
        and all(e["mediana_horas"] is None for e in vazio["tempo"]["etapas"]),
        "e nenhuma mediana é inventada a partir de amostra vazia",
    )
    checar(
        vazio["qualidade"]["percentual_aproveitado"] is None,
        "percentual sem documento nenhum sai nulo, não 0% nem 100%",
    )
    checar(len(vazio["movimento"]["meses"]) == panorama._MESES_DA_SERIE, "a série continua desenhável")

    print("\n== ausências ==")
    campos = {item["campo"] for item in montado["ausencias"]}
    # Comparado contra o próprio `painel.AUSENCIAS`, e não contra uma lista escrita aqui:
    # o painel do caso é mexido com frequência, e um rótulo renomeado lá quebraria este
    # teste sem que nada tivesse deixado de ser declarado.
    checar(
        {item["campo"] for item in painel.AUSENCIAS} <= campos,
        "as ausências do painel do caso continuam declaradas aqui",
        str(campos),
    )
    checar(
        "Caso encerrado ou arquivado" in campos and "Situação do caso no agente jurídico" in campos,
        "e as que só aparecem no panorama entram junto",
        str(campos),
    )
    checar(
        all(item["motivo"] for item in montado["ausencias"]),
        "toda ausência traz o motivo — campo vazio sem motivo é lido como zero",
    )

    print()
    if falhas:
        print(f"{falhas} FALHA(S)")
    else:
        print("Tudo certo.")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
