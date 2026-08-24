"""Panorama do escritório: o painel analítico de todos os casos ao mesmo tempo.

O painel do caso (`app/painel.py`) responde "como **este** caso está andando". Este
responde a pergunta que o gestor faz antes de abrir caso nenhum: **como o escritório
está andando** — quantos casos existem, em que estágio eles estão, onde o tempo é
gasto, quais categorias demoram mais e o que está travado agora. Sem isso, a única
forma de ter o total era abrir caso por caso e somar de cabeça.

Quatro decisões sustentam o que sai daqui:

- **a medição é a mesma do painel do caso.** `marcos_do_caso` e `medir_etapas` são
  importados de `painel.py`, não reescritos. A primeira coisa que qualquer gestor faz
  é abrir um caso e conferir se o número bate com o do panorama; duas medições do
  mesmo marco fariam as duas telas discordarem sobre o mesmo dia;
- **nada é estimado.** Todo número vem de um instante gravado no banco. Onde o
  instante não existe, o campo sai `None` com o motivo, e a seção fica vazia. O que o
  sistema não guarda — prazo, responsável, valor da causa, encerramento — sai em
  `ausencias`, nunca preenchido por dedução;
- **caso em andamento e caso instruído não entram na mesma conta.** O ciclo mediano é
  medido só sobre os casos que chegaram ao fim; a idade dos que ainda correm é outra
  medida, com outro nome. Misturá-los faria a mediana do escritório cair a cada caso
  novo aberto — e a queda seria lida como ganho de velocidade;
- **o agente jurídico fica de fora.** Agregar fatos, pendências e peças custaria uma
  chamada HTTP por caso vinculado (o agente não tem leitura em lote), e o panorama
  passaria a variar conforme o agente estivesse no ar. Está declarado em `ausencias`;
  quem quer isso de um caso abre o dossiê dele.

Custo: uma consulta para listar os casos e quatro para trazer entregas, entrevistas,
assinaturas e vínculos de todos eles (`armazenamento.marcos_por_caso`). Cinco idas ao
banco, independentemente do tamanho da carteira — o agrupamento é feito em memória.
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from . import armazenamento, banco
from . import casos as casos_ocr
from . import painel

log = logging.getLogger("panorama")

__all__ = ["ESTAGIOS", "compor", "estagio_do_caso", "montar"]


# Os utilitários de tempo vêm do painel do caso mesmo sendo privados, e é de propósito:
# as datas do Acervo são `varchar` em três formatos diferentes, e uma segunda conversão
# escrita aqui produziria um segundo valor para o mesmo marco.
_instante = painel._instante
_iso = painel._iso
_horas = painel._horas
_mediana = painel._mediana

OK = painel.OK
ATENCAO = painel.ATENCAO
CRITICO = painel.CRITICO
INFO = painel.INFO
NEUTRO = painel.NEUTRO

#: Mesmo piso do painel do caso: abaixo disso, "mediana" é uma frase sobre dois casos.
_AMOSTRA_MINIMA = painel._AMOSTRA_MINIMA

#: Mesmo limiar de "parado" do painel do caso, pela mesma razão: dois limiares
#: diferentes fariam um caso aparecer parado numa tela e andando na outra.
_DIAS_PARADO = painel._DIAS_PARADO

#: Meses cobertos pela série de movimento. Doze porque é o que responde "estamos
#: recebendo mais ou menos casos do que no ano passado" sem virar rolagem horizontal.
_MESES_DA_SERIE = 12

#: Janela dos indicadores de entrada — "abertos nos últimos 30 dias".
_DIAS_RECENTES = 30

#: Quantos casos parados a lista devolve. É lista de ação, não relatório: passando
#: disso ninguém age, e a carteira já mostra a fila inteira ordenada por risco.
_TETO_PARADOS = 12


# --------------------------------------------------------------------- estágios


#: Onde o caso está, decidido **só** pelo que o Acervo grava. A linha do processo do
#: dossiê tem mais etapas do que estas — as que dependem do agente jurídico —, e por
#: isso as duas telas não mostram a mesma contagem de etapas. A diferença está escrita
#: na descrição de cada uma.
ESTAGIOS = (
    {
        "codigo": "entrevista",
        "titulo": "Aguardando entrevista",
        "descricao": "O caso foi aberto e nenhuma entrevista foi anexada a ele.",
        "tom": ATENCAO,
    },
    {
        "codigo": "coleta",
        "titulo": "Coleta de documentos",
        "descricao": "Falta documento obrigatório no checklist da categoria.",
        "tom": INFO,
    },
    {
        "codigo": "conferencia",
        "titulo": "Documento a conferir",
        "descricao": (
            "Todo obrigatório recebeu arquivo, mas algum deles não passou na "
            "conferência e precisa ser reenviado."
        ),
        "tom": ATENCAO,
    },
    {
        "codigo": "contrato",
        "titulo": "Contrato de honorários",
        "descricao": "Checklist completo; o contrato ainda não está assinado.",
        "tom": INFO,
    },
    {
        "codigo": "instruido",
        "titulo": "Instruído",
        "descricao": "Checklist completo e contrato assinado. É o fim do que o Acervo mede.",
        "tom": OK,
    },
    {
        "codigo": "sem_checklist",
        "titulo": "Sem checklist",
        "descricao": (
            "A categoria gravada no caso não existe mais no sistema, então não há "
            "checklist para dizer em que estágio ele está."
        ),
        "tom": CRITICO,
    },
)

_ESTAGIO_FINAL = "instruido"

_TITULO_DO_ESTAGIO = {e["codigo"]: e["titulo"] for e in ESTAGIOS}


def estagio_do_caso(marcos: dict[str, datetime | None], situacao: dict[str, Any]) -> str:
    """Em que estágio o caso está, na ordem em que o trabalho acontece.

    Ordem determinística e sem sobreposição: um caso que tem obrigatório faltando **e**
    arquivo a conferir conta uma vez só, na coleta — porque é lá que ele está travado.
    Contá-lo nos dois faria a soma do funil ultrapassar o número de casos, e um funil
    que não fecha com o total não é lido como erro: é lido como "temos mais casos".
    """
    if situacao.get("erro") or not situacao.get("categoria"):
        return "sem_checklist"

    progresso = situacao.get("progresso") or {}
    if marcos.get("entrevista_anexada") is None:
        return "entrevista"
    if (progresso.get("obrigatorios_pendentes") or 0) > 0:
        return "coleta"
    if (progresso.get("itens_a_conferir") or 0) > 0:
        return "conferencia"
    if marcos.get("contrato_assinado") is None:
        return "contrato"
    return _ESTAGIO_FINAL


# ------------------------------------------------------------------ ausências


#: O que uma tela de gestão costuma mostrar e este sistema **não guarda**. Herda as do
#: painel do caso — são as mesmas lacunas de cadastro — e acrescenta as que só
#: aparecem quando se olha o escritório inteiro.
AUSENCIAS = painel.AUSENCIAS + (
    {
        "campo": "Caso encerrado ou arquivado",
        "motivo": (
            "O Acervo não tem status de encerramento. O estágio final medido é "
            "'instruído' — checklist completo e contrato assinado —, que é o fim do "
            "trabalho deste sistema, não o fim do processo."
        ),
    },
    {
        "campo": "Situação do caso no agente jurídico",
        "motivo": (
            "Fatos, pendências, estratégia e peças exigiriam uma consulta ao agente "
            "por caso, e o panorama passaria a variar conforme ele estivesse no ar. "
            "Estão no dossiê de cada caso."
        ),
    },
    {
        "campo": "Faturamento e honorários",
        "motivo": "Nenhum valor é registrado no Acervo, nem contratado nem recebido.",
    },
)


# ------------------------------------------------------------------- leitura


def _linha_do_caso(
    caso: dict[str, Any],
    dados: dict[str, Any],
    agora: datetime,
) -> dict[str, Any]:
    """Um caso reduzido ao que o panorama agrega — medido como o painel do caso mede."""
    entregas = dados["entregas"]
    entrevistas = dados["entrevistas"]
    situacao = casos_ocr.situacao_de(caso, entregas)
    marcos = painel.marcos_do_caso(
        caso, entregas, entrevistas, dados["assinaturas"], dados["vinculo"]
    )
    medidas = painel.medir_etapas(marcos, situacao, agora)
    estagio = estagio_do_caso(marcos, situacao)

    parado_horas = _horas(marcos.get("ultima_movimentacao"), agora)
    dias_parado = round(parado_horas / 24, 1) if parado_horas is not None else None
    instruido = estagio == _ESTAGIO_FINAL

    return {
        "id": str(caso.get("id")),
        "cliente": caso.get("cliente"),
        "categoria_codigo": caso.get("categoria"),
        "categoria": (situacao.get("categoria") or {}).get("nome") or caso.get("categoria"),
        "aberto_em": _iso(marcos.get("abertura")),
        "estagio": estagio,
        "estagio_titulo": _TITULO_DO_ESTAGIO.get(estagio, estagio),
        "instruido": instruido,
        "ultima_movimentacao": _iso(marcos.get("ultima_movimentacao")),
        "dias_sem_movimentacao": dias_parado,
        # Caso instruído não fica "parado": não há o que movimentar nele. Contá-lo
        # entre os parados encheria a lista de ação com trabalho já concluído.
        "parado": bool(not instruido and dias_parado is not None and dias_parado >= _DIAS_PARADO),
        "vinculado_ao_agente": dados["vinculo"] is not None,
        "portal_ativo": bool(caso.get("portal_token")),
        "marcos": marcos,
        "medidas": medidas,
        "entregas": entregas,
        "entrevistas": entrevistas,
    }


def _resumo_do_caso(linha: dict[str, Any]) -> dict[str, Any]:
    """O caso reduzido ao que a tela precisa para listá-lo e abri-lo.

    Existe para que clicar num estágio do funil mostre **quais** casos estão nele sem uma
    segunda leitura: pedir a lista de casos de novo por outra rota traria um retrato
    tirado num instante diferente, e a contagem do funil deixaria de bater com a lista
    que ele abre.

    Não carrega marcos, medidas nem entregas — são o material de trabalho das agregações,
    e mandá-los para o navegador multiplicaria o payload por nada.
    """
    return {
        "id": linha["id"],
        "cliente": linha["cliente"],
        "categoria": linha["categoria"],
        "estagio": linha["estagio"],
        "estagio_titulo": linha["estagio_titulo"],
        "aberto_em": linha["aberto_em"],
        "ultima_movimentacao": linha["ultima_movimentacao"],
        "dias_sem_movimentacao": linha["dias_sem_movimentacao"],
        "parado": linha["parado"],
        "instruido": linha["instruido"],
    }


# ---------------------------------------------------------------- indicadores


def _indicador(
    codigo: str,
    rotulo: str,
    valor: float | None,
    unidade: str,
    detalhe: str,
    tom: str,
) -> dict[str, Any]:
    return {
        "codigo": codigo,
        "rotulo": rotulo,
        "valor": valor,
        "unidade": unidade,
        "detalhe": detalhe,
        "tom": tom,
    }


def montar_indicadores(
    linhas: list[dict[str, Any]],
    agora: datetime,
) -> list[dict[str, Any]]:
    """Os números do topo. Cada um diz o que é e sobre quantos casos foi medido."""
    total = len(linhas)
    instruidos = [linha for linha in linhas if linha["instruido"]]
    andando = [linha for linha in linhas if not linha["instruido"]]
    parados = [linha for linha in linhas if linha["parado"]]

    corte = agora - timedelta(days=_DIAS_RECENTES)
    recentes = [
        linha
        for linha in linhas
        if (abertura := _instante(linha["aberto_em"])) is not None and abertura >= corte
    ]

    ciclos = [horas for linha in instruidos if (horas := _ciclo_da_linha(linha)) is not None]
    ciclo = _mediana(ciclos) if len(ciclos) >= _AMOSTRA_MINIMA else None

    idades = [
        horas
        for linha in andando
        if (horas := _horas(_instante(linha["aberto_em"]), agora)) is not None
    ]
    idade = _mediana(idades) if len(idades) >= _AMOSTRA_MINIMA else None

    return [
        _indicador(
            "em_andamento",
            "Casos em andamento",
            len(andando),
            "casos",
            f"De {total} no Acervo. {len(instruidos)} já estão instruídos.",
            INFO if andando else NEUTRO,
        ),
        _indicador(
            "parados",
            "Parados",
            len(parados),
            "casos",
            f"Sem nenhuma movimentação registrada há {_DIAS_PARADO} dias ou mais.",
            CRITICO if parados else OK,
        ),
        _indicador(
            "instruidos",
            "Instruídos",
            len(instruidos),
            "casos",
            "Checklist completo e contrato assinado.",
            OK if instruidos else NEUTRO,
        ),
        _indicador(
            "abertos_recentes",
            f"Abertos em {_DIAS_RECENTES} dias",
            len(recentes),
            "casos",
            "Casos cadastrados no período, incluindo os que já se instruíram.",
            INFO,
        ),
        _indicador(
            "ciclo_mediano",
            "Ciclo mediano",
            round(ciclo / 24, 1) if ciclo is not None else None,
            "dias",
            (
                f"Da abertura ao contrato assinado, em {len(ciclos)} casos instruídos."
                if ciclo is not None
                else (
                    f"Só {len(ciclos)} caso(s) chegaram ao fim — a mediana passa a valer "
                    f"a partir de {_AMOSTRA_MINIMA}."
                )
            ),
            NEUTRO,
        ),
        _indicador(
            "idade_mediana",
            "Idade dos que correm",
            round(idade / 24, 1) if idade is not None else None,
            "dias",
            (
                f"Tempo desde a abertura nos {len(idades)} casos em andamento. Não é "
                "ciclo: eles ainda não terminaram."
                if idade is not None
                else f"Menos de {_AMOSTRA_MINIMA} casos em andamento com data de abertura."
            ),
            NEUTRO,
        ),
    ]


def _ciclo_da_linha(linha: dict[str, Any]) -> float | None:
    """Horas da abertura ao contrato assinado. `None` quando algum marco falta.

    Usa os marcos, e não a etapa `ciclo` de `medir_etapas`: aquela mede até a última
    movimentação — o que num caso instruído é o próprio contrato, mas num caso em
    andamento é "quanto já levou". Aqui só entram casos instruídos, e o fim é o marco
    que define a instrução.
    """
    return _horas(linha["marcos"].get("abertura"), linha["marcos"].get("contrato_assinado"))


# --------------------------------------------------------------------- funil


def montar_funil(linhas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Quantos casos em cada estágio, com os ids para a fila poder ser filtrada.

    Os ids viajam porque o número sozinho termina a leitura no susto: "54 na coleta" só
    vira trabalho quando dá para ver quais são os 54 sem procurá-los na lista.
    """
    total = len(linhas)
    por_estagio: dict[str, list[str]] = defaultdict(list)
    for linha in linhas:
        por_estagio[linha["estagio"]].append(linha["id"])

    return [
        {
            "codigo": estagio["codigo"],
            "titulo": estagio["titulo"],
            "descricao": estagio["descricao"],
            "tom": estagio["tom"],
            "casos": len(por_estagio.get(estagio["codigo"], [])),
            "percentual": (
                round(len(por_estagio.get(estagio["codigo"], [])) / total * 100, 1)
                if total
                else None
            ),
            "ids": por_estagio.get(estagio["codigo"], []),
        }
        for estagio in ESTAGIOS
    ]


# ---------------------------------------------------------------------- tempo


def montar_tempo(linhas: list[dict[str, Any]]) -> dict[str, Any]:
    """Onde o tempo do escritório é gasto, etapa a etapa.

    Duas leituras diferentes na mesma tabela, e a distinção é o que impede a conclusão
    errada:

    - **horas acumuladas** somam só etapas **concluídas**. É o retrato do que já custou;
    - **em curso** conta os casos cujo relógio ainda corre naquela etapa, com o mais
      antigo deles. Um gargalo novo aparece aqui antes de aparecer na soma — porque
      etapa que nunca termina nunca entra na conta das concluídas.
    """
    concluidas: dict[str, list[float]] = defaultdict(list)
    em_curso: dict[str, list[float]] = defaultdict(list)

    for linha in linhas:
        for medida in linha["medidas"]:
            if medida["codigo"] == "ciclo" or medida["horas"] is None:
                continue
            if medida["em_curso"]:
                em_curso[medida["codigo"]].append(medida["horas"])
            elif medida["horas"] > 0:
                concluidas[medida["codigo"]].append(medida["horas"])

    total_horas = sum(sum(valores) for valores in concluidas.values())

    etapas = []
    for etapa in painel.ETAPAS:
        if etapa["codigo"] == "ciclo":
            continue
        valores = concluidas.get(etapa["codigo"], [])
        correndo = em_curso.get(etapa["codigo"], [])
        acumulado = round(sum(valores), 1)
        mediana = _mediana(valores) if len(valores) >= _AMOSTRA_MINIMA else None
        etapas.append(
            {
                "codigo": etapa["codigo"],
                "titulo": etapa["titulo"],
                "descricao": etapa["descricao"],
                "horas_totais": acumulado,
                "percentual": round(acumulado / total_horas * 100, 1) if total_horas else None,
                "mediana_horas": mediana,
                "amostra": len(valores),
                "em_curso": len(correndo),
                "mais_antigo_horas": round(max(correndo), 1) if correndo else None,
                "motivo": (
                    None
                    if mediana is not None
                    else (
                        f"{len(valores)} caso(s) concluíram esta etapa — a mediana passa "
                        f"a valer a partir de {_AMOSTRA_MINIMA}."
                    )
                ),
            }
        )

    etapas.sort(key=lambda item: (-item["horas_totais"], item["titulo"]))
    return {
        "total_horas": round(total_horas, 1),
        "etapas": etapas,
        "base": (
            "Percentual = horas somadas da etapa ÷ horas somadas de todas as etapas "
            "concluídas. Etapa ainda em curso não entra na soma — ela sai contada à "
            "parte, com o tempo do caso mais antigo parado nela."
        ),
    }


# ----------------------------------------------------------------- categorias


def montar_categorias(linhas: list[dict[str, Any]], agora: datetime) -> list[dict[str, Any]]:
    """Uma linha por categoria: volume, o que travou e quanto tempo levou.

    Ciclo e idade são colunas separadas de propósito — ver `_ciclo_da_linha`.
    """
    agrupado: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for linha in linhas:
        agrupado[str(linha["categoria_codigo"])].append(linha)

    resultado = []
    for codigo, casos_da_categoria in agrupado.items():
        instruidos = [linha for linha in casos_da_categoria if linha["instruido"]]
        andando = [linha for linha in casos_da_categoria if not linha["instruido"]]
        ciclos = [horas for linha in instruidos if (horas := _ciclo_da_linha(linha)) is not None]
        idades = [
            horas
            for linha in andando
            if (horas := _horas(_instante(linha["aberto_em"]), agora)) is not None
        ]
        ciclo = _mediana(ciclos) if len(ciclos) >= _AMOSTRA_MINIMA else None
        idade = _mediana(idades) if len(idades) >= _AMOSTRA_MINIMA else None
        resultado.append(
            {
                "codigo": codigo,
                "nome": casos_da_categoria[0]["categoria"],
                "casos": len(casos_da_categoria),
                "em_andamento": len(andando),
                "instruidos": len(instruidos),
                "parados": sum(1 for linha in casos_da_categoria if linha["parado"]),
                "ciclo_mediano_horas": ciclo,
                "ciclo_amostra": len(ciclos),
                "idade_mediana_horas": idade,
                "idade_amostra": len(idades),
                "motivo": (
                    None
                    if ciclo is not None
                    else (
                        f"{len(ciclos)} caso(s) instruído(s) nesta categoria — o ciclo "
                        f"mediano passa a valer a partir de {_AMOSTRA_MINIMA}."
                    )
                ),
            }
        )

    resultado.sort(key=lambda item: (-item["casos"], item["nome"] or ""))
    return resultado


# -------------------------------------------------------------------- parados


def montar_parados(linhas: list[dict[str, Any]]) -> dict[str, Any]:
    """Os casos sem movimentação, do mais antigo para o mais recente.

    É a única parte do panorama que aponta para um caso específico: o resto descreve o
    escritório, este diz onde ir agora.
    """
    parados = sorted(
        (linha for linha in linhas if linha["parado"]),
        key=lambda linha: -(linha["dias_sem_movimentacao"] or 0),
    )
    itens = [
        {
            "id": linha["id"],
            "cliente": linha["cliente"],
            "categoria": linha["categoria"],
            "estagio": linha["estagio"],
            "estagio_titulo": linha["estagio_titulo"],
            "dias": linha["dias_sem_movimentacao"],
            "ultima_movimentacao": linha["ultima_movimentacao"],
            "tom": (
                CRITICO if (linha["dias_sem_movimentacao"] or 0) >= _DIAS_PARADO * 2 else ATENCAO
            ),
        }
        for linha in parados[:_TETO_PARADOS]
    ]
    return {
        "total": len(parados),
        "mostrando": len(itens),
        "limiar_dias": _DIAS_PARADO,
        "itens": itens,
    }


# ------------------------------------------------------------------ movimento


def _mes(instante: datetime) -> str:
    return f"{instante.year:04d}-{instante.month:02d}"


_ABREVIACAO_DO_MES = (
    "jan",
    "fev",
    "mar",
    "abr",
    "mai",
    "jun",
    "jul",
    "ago",
    "set",
    "out",
    "nov",
    "dez",
)


def montar_movimento(linhas: list[dict[str, Any]], agora: datetime) -> dict[str, Any]:
    """Entradas e desfechos mês a mês, nos últimos doze meses.

    Três marcos reais, nenhum derivado: caso aberto, entrevista anexada e contrato
    assinado. "Casos encerrados" não existe aqui porque o Acervo não grava encerramento
    (ver `ausencias`) — e o contrato assinado é o marco mais próximo do fim que é
    gravado de verdade.

    O mês corrente sai marcado como parcial. Sem isso a última coluna desenha uma queda
    todo dia 1º, e a queda é lida como perda de movimento.
    """
    abertos: Counter[str] = Counter()
    entrevistas: Counter[str] = Counter()
    contratos: Counter[str] = Counter()

    for linha in linhas:
        marcos = linha["marcos"]
        if (abertura := marcos.get("abertura")) is not None:
            abertos[_mes(abertura)] += 1
        if (anexada := marcos.get("entrevista_anexada")) is not None:
            entrevistas[_mes(anexada)] += 1
        if (assinado := marcos.get("contrato_assinado")) is not None:
            contratos[_mes(assinado)] += 1

    # A série é montada a partir de hoje para trás, e não a partir do que existe nos
    # dados: um mês sem nenhum caso é informação, e ele sumiria da série se os meses
    # saíssem das chaves do contador.
    meses: list[dict[str, Any]] = []
    ano, mes = agora.year, agora.month
    for _ in range(_MESES_DA_SERIE):
        chave = f"{ano:04d}-{mes:02d}"
        meses.append(
            {
                "mes": chave,
                "rotulo": f"{_ABREVIACAO_DO_MES[mes - 1]}/{ano % 100:02d}",
                "abertos": abertos.get(chave, 0),
                "entrevistas": entrevistas.get(chave, 0),
                "contratos_assinados": contratos.get(chave, 0),
                "parcial": ano == agora.year and mes == agora.month,
            }
        )
        mes -= 1
        if mes == 0:
            ano, mes = ano - 1, 12

    meses.reverse()
    return {
        "meses": meses,
        "base": (
            "Cada coluna conta marcos gravados no mês: cadastro do caso, entrevista "
            "anexada e contrato assinado. O mês corrente está incompleto."
        ),
    }


# --------------------------------------------------------------------- equipe


def montar_equipe(linhas: list[dict[str, Any]]) -> dict[str, Any]:
    """Entrevistas por quem as conduziu.

    O nome vem da coluna `entrevistador`, que já foi texto livre e ficava vazia — as
    entrevistas antigas aparecem agrupadas como "não informado" em vez de sumirem, pela
    mesma razão que a supervisão as mantém: sumir com elas faria a soma da tela não
    bater com a realidade.

    Não é ranking de produtividade e não sai ordenado por desempenho: quem entrevista
    mais pode estar atendendo os casos mais simples, e o sistema não guarda nada que
    permita afirmar o contrário.
    """
    por_pessoa: dict[str, dict[str, Any]] = {}
    for linha in linhas:
        for entrevista in linha["entrevistas"]:
            nome = (entrevista.get("entrevistador") or "").strip()
            chave = nome or "não informado"
            registro = por_pessoa.setdefault(
                chave,
                {
                    "nome": chave,
                    "informado": bool(nome),
                    "entrevistas": 0,
                    "lidas": 0,
                    "fatos_gerados": 0,
                    "casos": set(),
                },
            )
            registro["entrevistas"] += 1
            registro["lidas"] += 1 if entrevista.get("enviada_em") else 0
            registro["fatos_gerados"] += int(entrevista.get("fatos_gerados") or 0)
            registro["casos"].add(linha["id"])

    pessoas = [{**registro, "casos": len(registro["casos"])} for registro in por_pessoa.values()]
    pessoas.sort(key=lambda item: (-item["entrevistas"], item["nome"]))
    return {
        "pessoas": pessoas,
        "total_entrevistas": sum(pessoa["entrevistas"] for pessoa in pessoas),
        "sem_atribuicao": sum(
            pessoa["entrevistas"] for pessoa in pessoas if not pessoa["informado"]
        ),
    }


# ------------------------------------------------------------------ qualidade


def montar_qualidade(linhas: list[dict[str, Any]]) -> dict[str, Any]:
    """O que aconteceu com os documentos recebidos, no vocabulário do painel do caso.

    Classificação por `painel._tom_da_entrega` — a mesma que decide o que é ocorrência
    dentro de um caso. Reclassificar aqui faria um documento aparecer aproveitado no
    panorama e reprovado no caso.
    """
    total = 0
    por_tom: Counter[str] = Counter()
    scores: list[float] = []

    for linha in linhas:
        for entrega in linha["entregas"]:
            total += 1
            tom, _ = painel._tom_da_entrega(entrega)
            por_tom[tom] += 1
            if entrega.get("score_legibilidade") is not None:
                scores.append(float(entrega["score_legibilidade"]))

    aproveitadas = por_tom.get(OK, 0)
    return {
        "entregas": total,
        "aproveitadas": aproveitadas,
        "a_conferir": por_tom.get(ATENCAO, 0),
        "com_erro": por_tom.get(CRITICO, 0),
        "em_leitura": por_tom.get(INFO, 0),
        "percentual_aproveitado": round(aproveitadas / total * 100, 1) if total else None,
        # Legibilidade sem score não vira zero: um PDF nativo não tem foto para avaliar,
        # e contá-lo como zero rebaixaria a leitura do escritório inteiro.
        "legibilidade_media": round(sum(scores) / len(scores), 1) if scores else None,
        "legibilidade_amostra": len(scores),
        "base": (
            "Cada documento é classificado pela mesma regra do painel do caso: falha de "
            "leitura, arquivo de outro tipo, dados ilegíveis ou aproveitado."
        ),
    }


# ------------------------------------------------------------------- montagem


def compor(
    *,
    casos: list[dict[str, Any]],
    em_lote: dict[str, dict[str, Any]],
    agora: datetime,
) -> dict[str, Any]:
    """Monta o panorama a partir de dados já lidos. Sem banco e sem rede — é testável.

    Separada de `montar` pela mesma razão que no painel do caso: a leitura é I/O e a
    composição é regra, e é a regra que precisa ser exercitada com escritório vazio,
    com um caso só e com carteira cheia.
    """
    linhas: list[dict[str, Any]] = []
    fora_do_lote = 0
    for caso in casos:
        dados = em_lote.get(str(caso.get("id")))
        if dados is None:
            # Não veio no lote: contado e declarado, nunca tratado como caso sem nada —
            # um caso ausente somaria zero hora e puxaria todas as medianas para baixo.
            fora_do_lote += 1
            log.warning("panorama: caso %s fora da leitura — não veio no lote", caso.get("id"))
            continue
        linhas.append(_linha_do_caso(caso, dados, agora))

    return {
        "cobertura": {
            "casos_no_acervo": len(casos),
            "casos_medidos": len(linhas),
            "fora_da_leitura": fora_do_lote,
            "motivo": (
                None
                if not fora_do_lote
                else (
                    f"{fora_do_lote} caso(s) não puderam ser lidos e ficaram fora de "
                    "todos os números desta tela."
                )
            ),
        },
        "casos": [_resumo_do_caso(linha) for linha in linhas],
        "indicadores": montar_indicadores(linhas, agora),
        "funil": montar_funil(linhas),
        "tempo": montar_tempo(linhas),
        "categorias": montar_categorias(linhas, agora),
        "parados": montar_parados(linhas),
        "movimento": montar_movimento(linhas, agora),
        "equipe": montar_equipe(linhas),
        "qualidade": montar_qualidade(linhas),
        "ausencias": list(AUSENCIAS),
        "gerado_em": _iso(agora),
    }


def montar() -> dict[str, Any]:
    """O panorama do escritório inteiro, em cinco consultas.

    Uma conexão só para tudo: são cinco leituras e o banco é remoto — abrir uma conexão
    por consulta custava mais que as consultas (ver `banco.sessao`).
    """
    with banco.sessao():
        casos = armazenamento.listar_casos()
        em_lote = armazenamento.marcos_por_caso([str(caso["id"]) for caso in casos])
        agora = datetime.now(timezone.utc)

    return compor(casos=casos, em_lote=em_lote, agora=agora)
