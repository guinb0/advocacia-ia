"""Painel analítico do caso: o histórico medido, não o histórico narrado.

O dossiê (`app/agente/dossie.py`) responde "em que pé está o caso". Este módulo responde
as perguntas que só aparecem quando se olha o caso ao longo do tempo: quanto tempo cada
etapa levou, como isso se compara com os outros casos da mesma categoria, há quantos dias
nada acontece, onde o tempo foi gasto e o que já deu errado.

Três decisões sustentam tudo o que sai daqui:

- **nada é estimado.** Cada número vem de um instante gravado no banco — abertura do
  caso, chegada de cada documento, leitura da entrevista, envio ao agente, assinatura.
  Onde o instante não existe, o campo sai `None` com o motivo ao lado, e a tela desenha
  estado vazio. O sistema não guarda prazo, SLA contratual, prioridade nem responsável
  formal: esses campos saem em `ausencias`, nunca preenchidos por dedução;
- **referência é medida, não arbitrada.** "Previsto" aqui é a **mediana dos casos
  anteriores da mesma categoria** — e vem sempre acompanhada do tamanho da amostra, que
  é o que permite ao advogado decidir se aquilo significa alguma coisa. Com menos de
  `_AMOSTRA_MINIMA` casos comparáveis, a referência sai nula e a seção fica vazia;
- **toda escala declarada.** Os poucos lugares em que uma nota de 0 a 100 é composta
  (saúde, radar) carregam no próprio payload a fórmula de cada componente, em `base`. A
  tela mostra essa frase no tooltip. Nota sem fórmula visível é chute com aparência de
  medida.

O agente jurídico entra como bloco opcional: quando ele não responde, os indicadores que
dependem dele saem como `indisponivel` com o motivo — nunca como zero, que se pareceria
com "não há pendência nenhuma".
"""

from __future__ import annotations

import logging
import statistics
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from . import armazenamento, casos as casos_ocr
from . import banco
from .agente import dossie

log = logging.getLogger("painel")

__all__ = ["compor", "montar"]

# Tons do guia visual: a tela nunca usa cor sozinha, mas o tom decide qual símbolo e
# qual palavra ela imprime ao lado do número.
OK = "ok"
ATENCAO = "atencao"
CRITICO = "critico"
INFO = "info"
NEUTRO = "neutro"

#: Abaixo disso, "mediana da categoria" é uma frase sobre um ou dois casos — e mostrar
#: isso como referência faria o advogado comparar o caso com o acaso.
_AMOSTRA_MINIMA = 3

#: Teto de casos lidos para montar a referência histórica. Cada caso comparado custa
#: duas consultas de entregas mais a montagem do checklist; sem teto, um escritório com
#: mil casos na categoria transformaria a abertura do painel em varredura de tabela.
_TETO_HISTORICO = 60

#: A partir de quantos dias sem nenhuma movimentação o caso é considerado parado. Não é
#: prazo contratual (o sistema não guarda nenhum): é o limiar do indicador de ritmo, e
#: viaja declarado no payload para a tela poder dizer de onde saiu.
_DIAS_PARADO = 5

#: Dias sem movimentação em que o componente de ritmo da saúde chega a zero.
_DIAS_RITMO_ZERO = 14


# --------------------------------------------------------------------------- tempo


def _instante(valor: Any) -> datetime | None:
    """Converte o que está gravado em `datetime` com fuso. `None` quando não dá.

    As colunas de data são `varchar` — herança do SQLite — e chegam em três formatos:
    ISO com fuso (`2026-08-15T00:05:55+00:00`), ISO sem fuso (registros antigos) e
    `dd/mm/aaaa`, que é como a entrevista grava a data informada pela atendente. Um
    `fromisoformat` seco em cima do terceiro caso derrubaria o painel inteiro por causa
    de um campo digitado à mão.
    """
    if isinstance(valor, datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)
    texto = str(valor or "").strip()
    if not texto:
        return None
    try:
        instante = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except ValueError:
        try:
            instante = datetime.strptime(texto, "%d/%m/%Y")
        except ValueError:
            return None
    return instante if instante.tzinfo else instante.replace(tzinfo=timezone.utc)


def _iso(instante: datetime | None) -> str | None:
    return instante.isoformat() if instante else None


def _horas(inicio: datetime | None, fim: datetime | None) -> float | None:
    """Duração em horas, com uma casa. `None` quando falta uma das pontas."""
    if inicio is None or fim is None:
        return None
    return round((fim - inicio).total_seconds() / 3600, 1)


def _mediana(valores: list[float]) -> float | None:
    return round(statistics.median(valores), 1) if valores else None


def _limitar(valor: float, minimo: float = 0.0, maximo: float = 100.0) -> float:
    return max(minimo, min(maximo, valor))


# ------------------------------------------------------------------------- marcos


#: Os instantes que o Acervo grava por conta própria — os que existem para **todo** caso
#: e por isso servem de base de comparação entre casos. O que depende do agente jurídico
#: fica fora daqui de propósito: comparar contra ele exigiria uma chamada HTTP por caso
#: histórico, e a referência passaria a variar conforme o agente esteja no ar.
MARCOS = (
    "abertura",
    "portal",
    "primeira_entrega",
    "ultima_entrega",
    "entrevista_anexada",
    "entrevista_lida",
    "contrato_enviado",
    "contrato_assinado",
    "agente_vinculado",
    "ultima_movimentacao",
)


def marcos_do_caso(
    caso: dict[str, Any],
    entregas: list[dict[str, Any]],
    entrevistas: list[dict[str, Any]],
    assinaturas: list[dict[str, Any]],
    vinculo: dict[str, Any] | None,
) -> dict[str, datetime | None]:
    """Os instantes-chave do caso, todos lidos do banco.

    É a mesma função usada para o caso aberto e para cada caso da amostra histórica —
    duas medições diferentes do mesmo marco produziriam uma comparação que não compara.
    """
    criacoes = [_instante(e.get("criado_em")) for e in entregas]
    criacoes = [i for i in criacoes if i]
    leituras = [_instante(e.get("enviada_em")) for e in entrevistas]
    leituras = [i for i in leituras if i]
    anexos = [_instante(e.get("criado_em")) for e in entrevistas]
    anexos = [i for i in anexos if i]
    envios = [_instante(a.get("criado_em")) for a in assinaturas]
    envios = [i for i in envios if i]
    assinados = [
        _instante(a.get("atualizado_em")) for a in assinaturas if a.get("estado") == "assinado"
    ]
    assinados = [i for i in assinados if i]

    marcos: dict[str, datetime | None] = {
        "abertura": _instante(caso.get("criado_em")),
        "portal": _instante(caso.get("portal_criado_em")),
        "primeira_entrega": min(criacoes) if criacoes else None,
        "ultima_entrega": max(criacoes) if criacoes else None,
        "entrevista_anexada": min(anexos) if anexos else None,
        "entrevista_lida": max(leituras) if leituras else None,
        "contrato_enviado": min(envios) if envios else None,
        "contrato_assinado": max(assinados) if assinados else None,
        "agente_vinculado": _instante(vinculo.get("criado_em")) if vinculo else None,
    }
    conhecidos = [i for i in marcos.values() if i]
    # `atualizado_em` do caso não serve como última movimentação: ele é tocado por
    # edição de observação e por criação de portal, mas NÃO por documento que chega
    # (a entrega grava na tabela dela). Usar o maior marco conhecido é o que faz
    # "sem movimentações há N dias" corresponder ao que se vê na linha do tempo.
    marcos["ultima_movimentacao"] = max(conhecidos) if conhecidos else None
    return marcos


#: Etapas com duração medida. Cada uma é um par de marcos; a etapa só existe quando o
#: marco de início existe. `comparavel` marca as que entram na referência histórica —
#: são as que dependem apenas do que o Acervo grava.
ETAPAS = (
    {
        "codigo": "atendimento",
        "titulo": "Abertura até a entrevista",
        "inicio": "abertura",
        "fim": "entrevista_anexada",
        "comparavel": True,
        "descricao": "Do cadastro do caso até a entrevista ser anexada ao Acervo.",
    },
    {
        "codigo": "leitura_entrevista",
        "titulo": "Leitura da entrevista",
        "inicio": "entrevista_anexada",
        "fim": "entrevista_lida",
        "comparavel": True,
        "descricao": "Da entrevista anexada até o agente extrair os fatos dela.",
    },
    {
        "codigo": "coleta",
        "titulo": "Coleta de documentos",
        "inicio": "primeira_entrega",
        "fim": "ultima_entrega",
        "comparavel": True,
        "descricao": "Do primeiro documento recebido ao último. Segue em curso enquanto "
        "faltar item obrigatório.",
    },
    {
        "codigo": "contrato",
        "titulo": "Contrato de honorários",
        "inicio": "contrato_enviado",
        "fim": "contrato_assinado",
        "comparavel": True,
        "descricao": "Do envio para assinatura até a última assinatura.",
    },
    {
        "codigo": "ciclo",
        "titulo": "Ciclo total do caso",
        "inicio": "abertura",
        "fim": "ultima_movimentacao",
        "comparavel": True,
        "descricao": "Da abertura até a movimentação mais recente registrada.",
    },
)


def _etapa_em_curso(codigo: str, situacao: dict[str, Any]) -> bool:
    """A etapa ainda está correndo? Só então o relógio conta até agora.

    A coleta é a única que o checklist sabe fechar: enquanto faltar obrigatório, a última
    entrega não é o fim da etapa — é só o último documento que chegou.
    """
    if codigo == "coleta":
        return not (situacao.get("progresso") or {}).get("pronto", False)
    return False


def medir_etapas(
    marcos: dict[str, datetime | None],
    situacao: dict[str, Any],
    agora: datetime,
) -> list[dict[str, Any]]:
    """Duração de cada etapa, em horas. Etapa sem início sai como não iniciada."""
    medidas = []
    for etapa in ETAPAS:
        inicio = marcos.get(etapa["inicio"])
        fim = marcos.get(etapa["fim"])
        em_curso = inicio is not None and (fim is None or _etapa_em_curso(etapa["codigo"], situacao))
        # Etapa em curso mede até agora, e o payload diz que mediu — sem isso, um caso
        # parado há um mês na coleta apareceria com a duração do dia em que o último
        # documento chegou, que é a leitura mais otimista possível do mesmo dado.
        ate = agora if em_curso else fim
        medidas.append(
            {
                "codigo": etapa["codigo"],
                "titulo": etapa["titulo"],
                "descricao": etapa["descricao"],
                "inicio": _iso(inicio),
                "fim": _iso(None if em_curso else fim),
                "horas": _horas(inicio, ate),
                "em_curso": em_curso,
                "iniciada": inicio is not None,
                "comparavel": etapa["comparavel"],
            }
        )
    return medidas


# -------------------------------------------------------------------- histórico


def referencia_historica(
    categoria: str,
    caso_atual: str,
    agora: datetime,
) -> dict[str, Any]:
    """A mediana de cada etapa nos outros casos da mesma categoria.

    É o que o painel chama de "previsto": não há prazo contratado no sistema, então o
    único parâmetro honesto é o que o próprio escritório levou nos casos anteriores. Sai
    junto o tamanho da amostra — comparar contra dois casos não é comparar contra nada,
    mas é quase, e quem lê precisa saber disso.
    """
    try:
        todos = armazenamento.listar_casos()
    except Exception as erro:  # pragma: no cover - depende do banco
        log.warning("painel: referência histórica indisponível — %s", erro)
        return {
            "amostra": 0,
            "suficiente": False,
            "motivo": f"Não foi possível ler os casos anteriores: {erro}",
            "etapas": {},
            "categoria": categoria,
        }

    comparaveis = [
        c for c in todos if c.get("categoria") == categoria and c.get("id") != caso_atual
    ][:_TETO_HISTORICO]

    # A amostra inteira em quatro consultas. Antes eram seis por caso: com a categoria
    # cheia (`_TETO_HISTORICO`), abrir o painel disparava trezentas e sessenta idas ao
    # banco remoto — a tela ficava mais lenta a cada caso novo que o escritório abria.
    try:
        em_lote = armazenamento.marcos_por_caso([str(c["id"]) for c in comparaveis])
    except Exception as erro:  # pragma: no cover - depende do banco
        log.warning("painel: amostra histórica indisponível — %s", erro)
        em_lote = {}

    duracoes: dict[str, list[float]] = {etapa["codigo"]: [] for etapa in ETAPAS}
    considerados = 0
    for outro in comparaveis:
        dados = em_lote.get(str(outro["id"]))
        if dados is None:
            log.warning("painel: caso %s fora da amostra — não veio no lote", outro.get("id"))
            continue

        entregas = dados["entregas"]
        situacao = casos_ocr.situacao_de(outro, entregas)
        marcos = marcos_do_caso(
            outro,
            entregas,
            dados["entrevistas"],
            dados["assinaturas"],
            dados["vinculo"],
        )
        considerados += 1
        for medida in medir_etapas(marcos, situacao, agora):
            # Etapa em curso não entra na mediana: ela mede "quanto já levou", e
            # misturá-la com etapas concluídas puxaria a referência para baixo
            # exatamente nos casos que estão demorando.
            if medida["comparavel"] and medida["horas"] is not None and not medida["em_curso"]:
                duracoes[medida["codigo"]].append(medida["horas"])

    etapas = {
        codigo: {
            "mediana_horas": _mediana(valores),
            "amostra": len(valores),
            "minimo_horas": round(min(valores), 1) if valores else None,
            "maximo_horas": round(max(valores), 1) if valores else None,
        }
        for codigo, valores in duracoes.items()
    }
    return {
        "categoria": categoria,
        "amostra": considerados,
        "suficiente": considerados >= _AMOSTRA_MINIMA,
        "motivo": (
            None
            if considerados >= _AMOSTRA_MINIMA
            else (
                f"Só {considerados} caso(s) anterior(es) nesta categoria — a mediana passa "
                f"a valer como referência a partir de {_AMOSTRA_MINIMA}."
            )
        ),
        "etapas": etapas,
    }


def comparar(
    medidas: list[dict[str, Any]],
    referencia: dict[str, Any],
) -> list[dict[str, Any]]:
    """Previsto (mediana da categoria) x realizado (este caso), etapa a etapa."""
    linhas = []
    for medida in medidas:
        base = (referencia.get("etapas") or {}).get(medida["codigo"]) or {}
        mediana = base.get("mediana_horas") if referencia.get("suficiente") else None
        # Amostra por etapa: um caso anterior pode ter chegado até a coleta e nunca ter
        # tido contrato, então cada etapa tem o seu próprio tamanho de amostra.
        amostra_etapa = base.get("amostra") or 0
        if amostra_etapa < _AMOSTRA_MINIMA:
            mediana = None
        realizado = medida["horas"]
        desvio = None
        desvio_percentual = None
        if mediana is not None and realizado is not None:
            desvio = round(realizado - mediana, 1)
            # Percentual exige base positiva. Mediana zero acontece de verdade (casos
            # abertos e trabalhados no mesmo minuto): dividir por ela produziria
            # "infinito por cento", e a tela cai para a diferença em horas.
            if mediana > 0:
                desvio_percentual = round((realizado - mediana) / mediana * 100)
        linhas.append(
            {
                "codigo": medida["codigo"],
                "titulo": medida["titulo"],
                "realizado_horas": realizado,
                "previsto_horas": mediana,
                "amostra": amostra_etapa,
                "em_curso": medida["em_curso"],
                "desvio_horas": desvio,
                "desvio_percentual": desvio_percentual,
                "motivo": (
                    None
                    if mediana is not None
                    else f"Sem amostra suficiente ({amostra_etapa} caso(s) concluíram esta etapa)."
                ),
            }
        )
    return linhas


# --------------------------------------------------------------------- eventos


def _tom_da_entrega(entrega: dict[str, Any]) -> tuple[str, str]:
    """Tom e leitura de uma entrega, no vocabulário da tela."""
    estado = entrega.get("status_proc", "pronto")
    if estado == "processando":
        return INFO, "leitura em andamento"
    if estado == "erro":
        return CRITICO, f"falha na leitura: {entrega.get('erro_proc') or 'motivo não registrado'}"
    if entrega.get("tipo_confere") is False:
        return ATENCAO, "o arquivo parece ser de outro documento"
    if not entrega.get("dados_utilizaveis") and not entrega.get("confirmado_manual"):
        score = entrega.get("score_legibilidade")
        sufixo = f" (legibilidade {score}%)" if score is not None else ""
        return ATENCAO, f"não foi possível extrair os dados com segurança{sufixo}"
    return OK, "lido e aproveitado"


def _evento(quando: datetime | None, tipo: str, titulo: str, detalhe: str, tom: str) -> dict | None:
    if quando is None:
        return None
    return {
        "quando": _iso(quando),
        "tipo": tipo,
        "titulo": titulo,
        "detalhe": detalhe,
        "tom": tom,
    }


def montar_eventos(
    caso: dict[str, Any],
    entregas: list[dict[str, Any]],
    entrevistas: list[dict[str, Any]],
    assinaturas: list[dict[str, Any]],
    vinculo: dict[str, Any] | None,
    agente: dict[str, Any],
) -> list[dict[str, Any]]:
    """A linha do tempo completa, em ordem cronológica.

    Cada linha é um instante gravado por alguém: cadastro, documento recebido, entrevista
    lida, contrato assinado, análise do agente. Nada aqui é reconstruído — evento sem
    instante gravado simplesmente não aparece, porque colocá-lo "por volta de" faria a
    linha do tempo mentir sobre a ordem dos fatos.
    """
    brutos: list[dict[str, Any] | None] = [
        _evento(
            _instante(caso.get("criado_em")),
            "caso",
            "Caso aberto",
            f"Cliente {caso.get('cliente')} · categoria {caso.get('categoria')}.",
            INFO,
        ),
        _evento(
            _instante(caso.get("portal_criado_em")),
            "caso",
            "Portal do cliente criado",
            "O cliente passou a poder enviar documentos sozinho.",
            INFO,
        ),
    ]

    for entrega in entregas:
        tom, leitura = _tom_da_entrega(entrega)
        itens = ", ".join(entrega.get("itens_atendidos") or [entrega.get("item_codigo", "")])
        brutos.append(
            _evento(
                _instante(entrega.get("criado_em")),
                "documento",
                f"Documento recebido — {itens}",
                f"{entrega.get('arquivo')}: {leitura}.",
                tom,
            )
        )

    for entrevista in entrevistas:
        brutos.append(
            _evento(
                _instante(entrevista.get("criado_em")),
                "entrevista",
                "Entrevista anexada",
                f"{entrevista.get('arquivo')}"
                + (
                    f" · entrevistador {entrevista['entrevistador']}"
                    if entrevista.get("entrevistador")
                    else ""
                ),
                INFO,
            )
        )
        fatos = entrevista.get("fatos_gerados") or 0
        brutos.append(
            _evento(
                _instante(entrevista.get("enviada_em")),
                "entrevista",
                "Entrevista lida pelo agente",
                f"{fatos} fato(s) relatado(s) extraído(s) de {entrevista.get('arquivo')}.",
                OK if fatos else ATENCAO,
            )
        )

    for assinatura in assinaturas:
        brutos.append(
            _evento(
                _instante(assinatura.get("criado_em")),
                "contrato",
                "Contrato enviado para assinatura",
                f"{assinatura.get('nome')} · {assinatura.get('total')} signatário(s).",
                INFO,
            )
        )
        for signatario in assinatura.get("signatarios") or []:
            brutos.append(
                _evento(
                    _instante(signatario.get("visualizado_em")),
                    "contrato",
                    "Contrato aberto pelo signatário",
                    f"{signatario.get('nome')} abriu o documento.",
                    INFO,
                )
            )
            brutos.append(
                _evento(
                    _instante(signatario.get("assinou_em")),
                    "contrato",
                    "Contrato assinado",
                    f"{signatario.get('nome')} assinou.",
                    OK,
                )
            )

    if vinculo:
        brutos.append(
            _evento(
                _instante(vinculo.get("criado_em")),
                "agente",
                "Caso enviado ao agente jurídico",
                f"Vinculado como {vinculo.get('caso_ref')}.",
                INFO,
            )
        )
        if vinculo.get("ultimo_erro"):
            brutos.append(
                _evento(
                    _instante(vinculo.get("atualizado_em")),
                    "agente",
                    "Falha na sincronização com o agente",
                    str(vinculo["ultimo_erro"]),
                    CRITICO,
                )
            )

    brutos.extend(_eventos_do_agente(agente))

    eventos = [e for e in brutos if e]
    eventos.sort(key=lambda e: e["quando"])
    return eventos


def _eventos_do_agente(agente: dict[str, Any]) -> list[dict[str, Any] | None]:
    """Movimentações do lado do agente jurídico.

    Fatos vêm agrupados por minuto de extração: uma leitura de CTPS produz vinte fatos no
    mesmo segundo, e vinte linhas iguais na linha do tempo escondem as outras etapas.
    """
    if not agente.get("disponivel"):
        return []

    eventos: list[dict[str, Any] | None] = []

    lotes: Counter[str] = Counter()
    for fato in agente.get("fatos") or []:
        instante = _instante(fato.get("created_at"))
        if instante:
            lotes[instante.replace(second=0, microsecond=0).isoformat()] += 1
    for chave, quantidade in lotes.items():
        eventos.append(
            _evento(
                _instante(chave),
                "agente",
                "Fatos apurados",
                f"{quantidade} fato(s) apurado(s) nesta leitura.",
                OK,
            )
        )

    for classificacao in agente.get("classificacoes") or []:
        eventos.append(
            _evento(
                _instante(classificacao.get("created_at")),
                "agente",
                "Classificação jurídica",
                f"{classificacao.get('label')} "
                f"(confiança {round((classificacao.get('confidence') or 0) * 100)}%).",
                OK,
            )
        )

    for contradicao in agente.get("contradicoes") or []:
        aberta = contradicao.get("status") == "OPEN"
        eventos.append(
            _evento(
                _instante(contradicao.get("created_at")),
                "ocorrencia",
                "Contradição entre fatos",
                str(contradicao.get("description") or contradicao.get("kind") or "")
                + ("" if aberta else " — resolvida."),
                ATENCAO if aberta else OK,
            )
        )

    for pesquisa in agente.get("pesquisas") or []:
        estado = pesquisa.get("status")
        eventos.append(
            _evento(
                _instante(pesquisa.get("created_at")),
                "agente",
                "Pesquisa de jurisprudência",
                {
                    "COMPLETED": "Pesquisa concluída.",
                    "RUNNING": "Pesquisa em andamento.",
                    "FAILED": f"Pesquisa falhou: {pesquisa.get('failure_reason')}",
                }.get(str(estado), f"Estado {estado}."),
                {"COMPLETED": OK, "RUNNING": INFO}.get(str(estado), CRITICO),
            )
        )

    estrategia = agente.get("estrategia") or {}
    if estrategia:
        eventos.append(
            _evento(
                _instante(estrategia.get("created_at")),
                "agente",
                "Estratégia proposta",
                f"Versão {estrategia.get('version')} com "
                f"{len(estrategia.get('hypotheses') or [])} tese(s).",
                INFO,
            )
        )
        eventos.append(
            _evento(
                _instante(estrategia.get("reviewed_at")),
                "agente",
                f"Estratégia {'aprovada' if estrategia.get('status') == 'APPROVED' else 'decidida'}",
                f"Versão {estrategia.get('version')} · {estrategia.get('status')}.",
                OK if estrategia.get("status") == "APPROVED" else ATENCAO,
            )
        )

    for peticao in agente.get("peticoes") or []:
        bloqueantes = int(peticao.get("blocking_findings") or 0)
        eventos.append(
            _evento(
                _instante(peticao.get("created_at")),
                "agente",
                "Minuta de petição gerada",
                f"Versão {peticao.get('version')}"
                + (f" · {bloqueantes} achado(s) bloqueante(s)." if bloqueantes else "."),
                ATENCAO if bloqueantes else INFO,
            )
        )
        eventos.append(
            _evento(
                _instante(peticao.get("reviewed_at")),
                "agente",
                "Minuta revisada pelo advogado",
                f"Versão {peticao.get('version')} · {peticao.get('status')}.",
                OK if peticao.get("status") == "APPROVED" else ATENCAO,
            )
        )

    return eventos


# ------------------------------------------------------------------ ocorrências


def montar_ocorrencias(
    entregas: list[dict[str, Any]],
    situacao: dict[str, Any],
    vinculo: dict[str, Any] | None,
    agente: dict[str, Any],
) -> dict[str, Any]:
    """Tudo que já deu errado no caso, com estado de aberto ou resolvido.

    Documento ilegível cujo item foi atendido depois por outro arquivo conta como
    ocorrência **resolvida**: ela aconteceu, custou tempo e continua explicando o
    histórico, mas não é pendência de hoje.
    """
    itens_ok = {
        item["codigo"] for item in situacao.get("itens", []) if item.get("status") == "entregue"
    }
    ocorrencias: list[dict[str, Any]] = []

    for entrega in entregas:
        tom, leitura = _tom_da_entrega(entrega)
        if tom == OK or tom == INFO:
            continue
        atendidos = entrega.get("itens_atendidos") or [entrega.get("item_codigo")]
        resolvida = all(codigo in itens_ok for codigo in atendidos)
        ocorrencias.append(
            {
                "quando": entrega.get("criado_em"),
                "tipo": "documento",
                "titulo": f"{entrega.get('arquivo')}",
                "detalhe": leitura.capitalize() + ".",
                "gravidade": tom,
                "estado": "resolvida" if resolvida else "aberta",
                "referencia": ", ".join(str(c) for c in atendidos),
            }
        )

    for item in situacao.get("itens", []):
        if item.get("status") == "conferir":
            ocorrencias.append(
                {
                    "quando": None,
                    "tipo": "checklist",
                    "titulo": f"{item.get('nome')} precisa ser reenviado",
                    "detalhe": "O item recebeu arquivo, mas nenhum deles passou na conferência.",
                    "gravidade": ATENCAO,
                    "estado": "aberta",
                    "referencia": str(item.get("codigo")),
                }
            )

    if vinculo and vinculo.get("ultimo_erro"):
        ocorrencias.append(
            {
                "quando": vinculo.get("atualizado_em"),
                "tipo": "agente",
                "titulo": "Falha na sincronização com o agente jurídico",
                "detalhe": str(vinculo["ultimo_erro"]),
                "gravidade": CRITICO,
                "estado": "aberta",
                "referencia": str(vinculo.get("caso_ref") or ""),
            }
        )

    for contradicao in agente.get("contradicoes") or []:
        aberta = contradicao.get("status") == "OPEN"
        ocorrencias.append(
            {
                "quando": contradicao.get("created_at"),
                "tipo": "contradicao",
                "titulo": "Contradição entre fatos",
                "detalhe": str(contradicao.get("description") or contradicao.get("kind") or ""),
                "gravidade": ATENCAO if aberta else OK,
                "estado": "aberta" if aberta else "resolvida",
                "referencia": str(contradicao.get("id") or ""),
            }
        )

    for pesquisa in agente.get("pesquisas") or []:
        if pesquisa.get("status") == "FAILED":
            ocorrencias.append(
                {
                    "quando": pesquisa.get("created_at"),
                    "tipo": "agente",
                    "titulo": "Pesquisa de jurisprudência não concluiu",
                    "detalhe": str(pesquisa.get("failure_reason") or "Motivo não informado."),
                    "gravidade": CRITICO,
                    "estado": "aberta",
                    "referencia": str(pesquisa.get("id") or ""),
                }
            )

    por_tipo = Counter(o["tipo"] for o in ocorrencias)
    return {
        "itens": ocorrencias,
        "abertas": sum(1 for o in ocorrencias if o["estado"] == "aberta"),
        "resolvidas": sum(1 for o in ocorrencias if o["estado"] == "resolvida"),
        "por_tipo": [{"tipo": tipo, "quantidade": q} for tipo, q in por_tipo.most_common()],
    }


#: Estados de fato que já não valem como afirmação do caso. Contá-los junto com os
#: vigentes inflaria o "quanto o caso já apurou" com material descartado.
_FATOS_DESCARTADOS = {"REJECTED", "SUPERSEDED"}


def montar_fatos(agente: dict[str, Any]) -> dict[str, Any]:
    """Todos os fatos do caso, com valor, estado e a origem de cada um.

    O painel mostrava só a contagem, e contagem esconde a distinção que mais importa
    numa peça: **relatado** (`ALLEGED`, saiu da entrevista) não é **extraído**
    (`EXTRACTED`, lido de um documento). Os dois entram na petição de formas diferentes,
    e um caso com vinte fatos só relatados está muito menos instruído do que o número
    sugere.

    A lista sai como o agente a devolve — tipo, valor, confiança, relevância e fontes.
    Nada é reclassificado aqui: se um fato chega sem origem, ele aparece contado como
    sem origem, e não some da tela.
    """
    if not agente.get("disponivel"):
        return {
            "disponivel": False,
            "motivo": agente.get("motivo") or "Agente jurídico indisponível.",
            "itens": [],
            "total": 0,
            "por_tipo": [],
            "por_status": [],
            "por_origem": [],
            "sem_origem": 0,
            "apenas_relatados": 0,
            "vigentes": 0,
        }

    itens: list[dict[str, Any]] = []
    for fato in agente.get("fatos") or []:
        fontes = fato.get("sources") or []
        itens.append(
            {
                "id": fato.get("id"),
                "tipo": fato.get("type"),
                "valor": fato.get("value") or {},
                "status": fato.get("status"),
                "confianca": fato.get("confidence"),
                "relevancia": fato.get("legal_relevance"),
                "origens": dossie.origens_do_fato(fato),
                "tipos_de_origem": sorted(
                    {str(f.get("source_type") or "").upper() for f in fontes if f.get("source_type")}
                ),
                "criado_em": fato.get("created_at"),
                "vigente": str(fato.get("status")) not in _FATOS_DESCARTADOS,
            }
        )

    vigentes = [i for i in itens if i["vigente"]]
    por_tipo = Counter(i["tipo"] for i in vigentes)
    por_status = Counter(i["status"] for i in itens)
    por_origem: Counter[str] = Counter()
    for item in vigentes:
        for origem in item["tipos_de_origem"] or ["SEM_ORIGEM"]:
            por_origem[origem] += 1

    return {
        "disponivel": True,
        "motivo": None,
        "itens": itens,
        "total": len(itens),
        "vigentes": len(vigentes),
        "por_tipo": [{"tipo": t, "quantidade": q} for t, q in por_tipo.most_common()],
        "por_status": [{"status": s, "quantidade": q} for s, q in por_status.most_common()],
        "por_origem": [{"origem": o, "quantidade": q} for o, q in por_origem.most_common()],
        "sem_origem": sum(1 for i in vigentes if not i["origens"]),
        # Relatado na entrevista e sem nenhum documento que o sustente: é a fila de
        # prova a produzir, e o número que o advogado procura antes de peticionar.
        "apenas_relatados": sum(
            1
            for i in vigentes
            if i["status"] == "ALLEGED" and "OCR_DOCUMENT" not in (i["tipos_de_origem"] or [])
        ),
    }


def montar_pendencias(agente: dict[str, Any]) -> dict[str, Any]:
    """Pendências do playbook — a lista do agente, não uma releitura nossa."""
    if not agente.get("disponivel"):
        return {
            "disponivel": False,
            "motivo": agente.get("motivo") or "Agente jurídico indisponível.",
            "itens": [],
            "abertas": 0,
            "bloqueantes": 0,
        }

    itens = [
        {
            "codigo": p.get("code"),
            "rotulo": p.get("label"),
            "tipo": p.get("kind"),
            "severidade": p.get("severity"),
            "estado": p.get("status"),
            "pergunta": p.get("question"),
            "exigido_por": p.get("required_by") or [],
            "satisfeita_em": p.get("satisfied_at"),
        }
        for p in agente.get("pendencias") or []
    ]
    abertas = [i for i in itens if i["estado"] == "OPEN"]
    return {
        "disponivel": True,
        "motivo": None,
        "itens": itens,
        "abertas": len(abertas),
        "bloqueantes": sum(1 for i in abertas if i["severidade"] == "BLOCKING"),
    }


# ------------------------------------------------------------------ indicadores


def _legibilidade(entregas: list[dict[str, Any]]) -> tuple[float | None, int]:
    """Média dos scores de legibilidade e quantas leituras entraram nela.

    Entrega sem score não vira zero: ela sai da média. Um PDF nativo (sem foto para
    avaliar) rebaixaria a leitura do caso inteiro por não ter nota nenhuma.
    """
    scores = [
        float(e["score_legibilidade"])
        for e in entregas
        if e.get("score_legibilidade") is not None
    ]
    if not scores:
        return None, 0
    return round(sum(scores) / len(scores), 1), len(scores)


def montar_indicadores(
    caso: dict[str, Any],
    situacao: dict[str, Any],
    entregas: list[dict[str, Any]],
    entrevistas: list[dict[str, Any]],
    marcos: dict[str, datetime | None],
    ocorrencias: dict[str, Any],
    pendencias: dict[str, Any],
    agente: dict[str, Any],
    comparacoes: list[dict[str, Any]],
    agora: datetime,
) -> list[dict[str, Any]]:
    """Os números do topo da tela. Cada um traz o que é e de onde saiu."""
    progresso = situacao.get("progresso") or {}
    abertura = marcos.get("abertura")
    ultima = marcos.get("ultima_movimentacao")
    media_score, lidas_com_score = _legibilidade(entregas)
    ciclo = next((c for c in comparacoes if c["codigo"] == "ciclo"), None)

    dias_aberto = _horas(abertura, agora)
    dias_parado = _horas(ultima, agora)

    indicadores: list[dict[str, Any]] = [
        {
            "codigo": "tempo_em_aberto",
            "rotulo": "Tempo em aberto",
            "valor": round(dias_aberto / 24, 1) if dias_aberto is not None else None,
            "unidade": "dias",
            "detalhe": (
                f"Desde {abertura.strftime('%d/%m/%Y %H:%M')}." if abertura else "Sem data de abertura."
            ),
            "tom": NEUTRO,
            "comparacao": (
                {
                    "rotulo": "mediana da categoria",
                    "valor": round((ciclo["previsto_horas"] or 0) / 24, 1),
                    "desvio_percentual": ciclo["desvio_percentual"],
                }
                if ciclo and ciclo.get("previsto_horas") is not None
                else None
            ),
        },
        {
            "codigo": "sem_movimentacao",
            "rotulo": "Sem movimentações há",
            "valor": round(dias_parado / 24, 1) if dias_parado is not None else None,
            "unidade": "dias",
            "detalhe": (
                f"Última: {ultima.strftime('%d/%m/%Y %H:%M')}."
                if ultima
                else "Nenhuma movimentação registrada."
            ),
            "tom": (
                ATENCAO
                if dias_parado is not None and dias_parado / 24 >= _DIAS_PARADO
                else OK
                if dias_parado is not None
                else NEUTRO
            ),
            "comparacao": None,
        },
        {
            "codigo": "progresso",
            "rotulo": "Documentos obrigatórios",
            "valor": progresso.get("percentual_obrigatorios"),
            "unidade": "%",
            "detalhe": (
                f"{progresso.get('obrigatorios_entregues', 0)} de "
                f"{progresso.get('obrigatorios_total', 0)} itens entregues."
            ),
            "tom": OK if progresso.get("pronto") else INFO,
            "comparacao": None,
        },
        {
            "codigo": "ocorrencias",
            "rotulo": "Ocorrências abertas",
            "valor": ocorrencias["abertas"],
            "unidade": "",
            "detalhe": f"{ocorrencias['resolvidas']} já resolvida(s) no histórico.",
            "tom": ATENCAO if ocorrencias["abertas"] else OK,
            "comparacao": None,
        },
        {
            "codigo": "pendencias",
            "rotulo": "Pendências do playbook",
            "valor": pendencias["abertas"] if pendencias["disponivel"] else None,
            "unidade": "",
            "detalhe": (
                f"{pendencias['bloqueantes']} bloqueante(s)."
                if pendencias["disponivel"]
                else str(pendencias["motivo"])
            ),
            "tom": (
                CRITICO
                if pendencias["disponivel"] and pendencias["bloqueantes"]
                else ATENCAO
                if pendencias["disponivel"] and pendencias["abertas"]
                else OK
                if pendencias["disponivel"]
                else NEUTRO
            ),
            "comparacao": None,
        },
        {
            "codigo": "legibilidade",
            "rotulo": "Legibilidade média",
            "valor": media_score,
            "unidade": "%",
            "detalhe": (
                f"Média de {lidas_com_score} leitura(s) com nota."
                if lidas_com_score
                else "Nenhuma leitura produziu nota de legibilidade."
            ),
            "tom": NEUTRO if media_score is None else OK if media_score >= 75 else ATENCAO,
            "comparacao": None,
        },
        {
            "codigo": "fatos",
            "rotulo": "Fatos apurados",
            "valor": len(agente.get("fatos") or []) if agente.get("disponivel") else None,
            "unidade": "",
            "detalhe": (
                "Fatos com origem registrada no agente."
                if agente.get("disponivel")
                else str(agente.get("motivo") or "Agente jurídico indisponível.")
            ),
            "tom": NEUTRO,
            "comparacao": None,
        },
        {
            "codigo": "movimentacoes",
            "rotulo": "Movimentações registradas",
            "valor": None,  # preenchido em `compor`, que já tem a lista pronta
            "unidade": "",
            "detalhe": "Eventos com instante gravado na linha do tempo.",
            "tom": NEUTRO,
            "comparacao": None,
        },
        {
            "codigo": "entrevistas",
            "rotulo": "Entrevistas",
            "valor": len(entrevistas),
            "unidade": "",
            "detalhe": (
                f"{sum(1 for e in entrevistas if e.get('enviada_em'))} lida(s) pelo agente."
                if entrevistas
                else "Nenhuma entrevista anexada."
            ),
            "tom": NEUTRO,
            "comparacao": None,
        },
    ]
    return indicadores


# ------------------------------------------------------------- saúde e radar


def montar_saude(
    situacao: dict[str, Any],
    ocorrencias: dict[str, Any],
    pendencias: dict[str, Any],
    agente: dict[str, Any],
    marcos: dict[str, datetime | None],
    agora: datetime,
) -> dict[str, Any]:
    """Nota de 0 a 100 composta por partes declaradas.

    A nota não é um julgamento sobre o caso: é a soma ponderada de cinco medidas que já
    estão na tela, publicada com a fórmula de cada uma em `base` para que o advogado
    possa discordar do peso sabendo exatamente o que ele fez. Componente sem dado (o
    agente fora do ar, por exemplo) sai como `indisponivel` e o peso dele é redistribuído
    entre os demais — zerar o componente puniria o caso por uma falha de infraestrutura.
    """
    progresso = situacao.get("progresso") or {}
    componentes: list[dict[str, Any]] = []

    percentual = progresso.get("percentual_obrigatorios")
    componentes.append(
        {
            "codigo": "documentacao",
            "rotulo": "Documentação",
            "peso": 30,
            "valor": float(percentual) if percentual is not None else None,
            "base": "Percentual de itens obrigatórios do checklist já entregues.",
        }
    )

    total_itens = len(situacao.get("itens") or [])
    abertas = ocorrencias["abertas"]
    componentes.append(
        {
            "codigo": "ocorrencias",
            "rotulo": "Ausência de ocorrências",
            "peso": 20,
            "valor": (
                _limitar(100 - (abertas / total_itens * 100) * 2) if total_itens else None
            ),
            "base": (
                "100 menos o dobro do percentual de itens do checklist com ocorrência aberta."
            ),
        }
    )

    if pendencias["disponivel"]:
        total_pend = len(pendencias["itens"]) or 1
        valor_pend = _limitar(
            100 - (pendencias["abertas"] / total_pend * 100) - pendencias["bloqueantes"] * 10
        )
        base_pend = (
            "100 menos o percentual de pendências do playbook em aberto, menos 10 por "
            "pendência bloqueante."
        )
    else:
        valor_pend, base_pend = None, str(pendencias["motivo"])
    componentes.append(
        {
            "codigo": "playbook",
            "rotulo": "Playbook atendido",
            "peso": 20,
            "valor": valor_pend,
            "base": base_pend,
        }
    )

    if agente.get("disponivel"):
        fatos = agente.get("fatos") or []
        contradicoes_abertas = sum(
            1 for c in agente.get("contradicoes") or [] if c.get("status") == "OPEN"
        )
        valor_cons = (
            _limitar(100 - contradicoes_abertas / len(fatos) * 100 * 3) if fatos else None
        )
        base_cons = (
            "100 menos o triplo do percentual de fatos envolvidos em contradição aberta."
            if fatos
            else "Nenhum fato apurado ainda."
        )
    else:
        valor_cons = None
        base_cons = str(agente.get("motivo") or "Agente jurídico indisponível.")
    componentes.append(
        {
            "codigo": "consistencia",
            "rotulo": "Consistência dos fatos",
            "peso": 15,
            "valor": valor_cons,
            "base": base_cons,
        }
    )

    parado_horas = _horas(marcos.get("ultima_movimentacao"), agora)
    dias_parado = parado_horas / 24 if parado_horas is not None else None
    componentes.append(
        {
            "codigo": "ritmo",
            "rotulo": "Ritmo",
            "peso": 15,
            "valor": (
                None
                if dias_parado is None
                else _limitar(100 - max(0.0, dias_parado - _DIAS_PARADO) / (_DIAS_RITMO_ZERO - _DIAS_PARADO) * 100)
            ),
            "base": (
                f"100 até {_DIAS_PARADO} dias sem movimentação, caindo a zero em "
                f"{_DIAS_RITMO_ZERO} dias."
            ),
        }
    )

    medidos = [c for c in componentes if c["valor"] is not None]
    peso_total = sum(c["peso"] for c in medidos)
    pontuacao = (
        round(sum(c["valor"] * c["peso"] for c in medidos) / peso_total) if peso_total else None
    )

    if pontuacao is None:
        faixa, tom = "sem medida", NEUTRO
    elif pontuacao >= 75:
        faixa, tom = "saudável", OK
    elif pontuacao >= 50:
        faixa, tom = "atenção", ATENCAO
    else:
        faixa, tom = "crítico", CRITICO

    return {
        "pontuacao": pontuacao,
        "faixa": faixa,
        "tom": tom,
        "componentes": componentes,
        "peso_medido": peso_total,
        "base": (
            "Média ponderada dos componentes medidos. Componente sem dado não entra na "
            "conta e o peso dele é redistribuído."
        ),
    }


def montar_radar(
    situacao: dict[str, Any],
    entregas: list[dict[str, Any]],
    agente: dict[str, Any],
    pendencias: dict[str, Any],
    comparacoes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Cinco eixos de 0 a 100. Eixo sem dado sai nulo — e a tela desenha o vazio."""
    progresso = situacao.get("progresso") or {}
    media_score, quantas = _legibilidade(entregas)

    fatos = agente.get("fatos") or []
    com_origem = sum(1 for f in fatos if f.get("sources"))
    ciclo = next((c for c in comparacoes if c["codigo"] == "ciclo"), None)

    ritmo = None
    base_ritmo = "Sem amostra histórica suficiente na categoria."
    if ciclo and ciclo.get("previsto_horas") == 0:
        base_ritmo = "A mediana da categoria é de zero hora — não há proporção a calcular."
    if ciclo and ciclo.get("previsto_horas") and ciclo.get("realizado_horas") is not None:
        # 100 quando o caso está no tempo da mediana ou abaixo; cai proporcionalmente à
        # medida que ultrapassa, chegando a zero no dobro da mediana.
        razao = ciclo["realizado_horas"] / ciclo["previsto_horas"]
        ritmo = _limitar(100 - max(0.0, razao - 1) * 100)
        base_ritmo = (
            f"Ciclo do caso ({ciclo['realizado_horas']}h) contra a mediana da categoria "
            f"({ciclo['previsto_horas']}h): 100 no tempo da mediana, zero no dobro dela."
        )

    return [
        {
            "eixo": "Documentação",
            "valor": float(progresso["percentual_obrigatorios"])
            if progresso.get("percentual_obrigatorios") is not None
            else None,
            "base": "Itens obrigatórios entregues sobre o total do checklist.",
        },
        {
            "eixo": "Qualidade da leitura",
            "valor": media_score,
            "base": (
                f"Média do score de legibilidade de {quantas} leitura(s)."
                if quantas
                else "Nenhuma leitura com nota de legibilidade."
            ),
        },
        {
            "eixo": "Fatos com origem",
            "valor": round(com_origem / len(fatos) * 100, 1) if fatos else None,
            "base": (
                f"{com_origem} de {len(fatos)} fatos trazem documento de origem."
                if fatos
                else str(agente.get("motivo") or "Nenhum fato apurado ainda.")
            ),
        },
        {
            "eixo": "Playbook",
            "valor": (
                _limitar(100 - pendencias["abertas"] / (len(pendencias["itens"]) or 1) * 100)
                if pendencias["disponivel"] and pendencias["itens"]
                else None
            ),
            "base": (
                "Pendências do playbook já satisfeitas sobre o total exigido."
                if pendencias["disponivel"]
                else str(pendencias["motivo"])
            ),
        },
        {"eixo": "Ritmo", "valor": ritmo, "base": base_ritmo},
    ]


# ---------------------------------------------------------------------- insights


def montar_insights(
    situacao: dict[str, Any],
    comparacoes: list[dict[str, Any]],
    referencia: dict[str, Any],
    medidas: list[dict[str, Any]],
    ocorrencias: dict[str, Any],
    pendencias: dict[str, Any],
    entregas: list[dict[str, Any]],
    agente: dict[str, Any],
    marcos: dict[str, datetime | None],
    eventos: list[dict[str, Any]],
    fatos: dict[str, Any],
    agora: datetime,
) -> list[dict[str, Any]]:
    """Frases curtas, cada uma amarrada ao número que a produziu.

    Insight só nasce quando o dado existe. Nada de "o caso está indo bem" — a tela
    prefere ficar com dois insights verdadeiros a encher a seção com dez genéricos.
    """
    insights: list[dict[str, Any]] = []
    progresso = situacao.get("progresso") or {}

    ciclo = next((c for c in comparacoes if c["codigo"] == "ciclo"), None)
    if ciclo and ciclo.get("desvio_percentual") is not None:
        desvio = ciclo["desvio_percentual"]
        if abs(desvio) >= 10:
            insights.append(
                {
                    "texto": (
                        f"Caso {abs(desvio)}% {'acima' if desvio > 0 else 'abaixo'} do tempo "
                        f"mediano da categoria."
                    ),
                    "tom": ATENCAO if desvio > 0 else OK,
                    "base": (
                        f"Ciclo de {ciclo['realizado_horas']}h contra mediana de "
                        f"{ciclo['previsto_horas']}h em {ciclo['amostra']} caso(s) anteriores."
                    ),
                }
            )

    for comparacao in comparacoes:
        if comparacao["codigo"] == "ciclo" or comparacao.get("desvio_horas") is None:
            continue
        dias = comparacao["desvio_horas"] / 24
        if dias >= 1:
            insights.append(
                {
                    "texto": (
                        f"A etapa “{comparacao['titulo']}” está {round(dias, 1)} dia(s) acima "
                        f"do esperado para a categoria."
                    ),
                    "tom": ATENCAO,
                    "base": (
                        f"{comparacao['realizado_horas']}h contra mediana de "
                        f"{comparacao['previsto_horas']}h em {comparacao['amostra']} caso(s)."
                    ),
                }
            )

    parado = _horas(marcos.get("ultima_movimentacao"), agora)
    if parado is not None and parado / 24 >= _DIAS_PARADO:
        ultimo = eventos[-1] if eventos else None
        insights.append(
            {
                "texto": f"Sem movimentações há {round(parado / 24)} dias.",
                "tom": ATENCAO,
                "base": (
                    f"Última movimentação: {ultimo['titulo']}." if ultimo else "Sem eventos registrados."
                ),
            }
        )

    medidas_validas = [
        m for m in medidas if m["codigo"] != "ciclo" and m["horas"] and m["horas"] > 0
    ]
    total = sum(m["horas"] for m in medidas_validas)
    if medidas_validas and total > 0:
        maior = max(medidas_validas, key=lambda m: m["horas"])
        fatia = round(maior["horas"] / total * 100)
        if fatia >= 30:
            insights.append(
                {
                    "texto": f"A etapa “{maior['titulo']}” representa {fatia}% do tempo medido.",
                    "tom": INFO,
                    "base": (
                        f"{maior['horas']}h de {round(total, 1)}h somadas nas etapas com "
                        "início e fim registrados."
                    ),
                }
            )

    faltando = [
        item["nome"]
        for item in situacao.get("itens", [])
        if item.get("obrigatorio") and item.get("status") == "pendente"
    ]
    if faltando:
        amostra = ", ".join(faltando[:3]) + ("…" if len(faltando) > 3 else "")
        insights.append(
            {
                "texto": f"{len(faltando)} documento(s) obrigatório(s) ainda não chegaram.",
                "tom": ATENCAO,
                "base": f"Faltando: {amostra}",
            }
        )
    elif progresso.get("pronto"):
        insights.append(
            {
                "texto": "Checklist obrigatório completo e conferido.",
                "tom": OK,
                "base": (
                    f"{progresso.get('obrigatorios_entregues')} de "
                    f"{progresso.get('obrigatorios_total')} itens, nenhum a conferir."
                ),
            }
        )

    if ocorrencias["abertas"]:
        insights.append(
            {
                "texto": f"{ocorrencias['abertas']} ocorrência(s) em aberto no caso.",
                "tom": ATENCAO,
                "base": ", ".join(
                    f"{item['quantidade']} de {item['tipo']}" for item in ocorrencias["por_tipo"]
                ),
            }
        )

    if pendencias["disponivel"] and pendencias["bloqueantes"]:
        insights.append(
            {
                "texto": (
                    f"{pendencias['bloqueantes']} pendência(s) bloqueante(s) impedem a petição."
                ),
                "tom": CRITICO,
                "base": "Itens marcados como BLOCKING pelo playbook da classificação.",
            }
        )

    if fatos["disponivel"] and fatos["apenas_relatados"]:
        insights.append(
            {
                "texto": (
                    f"{fatos['apenas_relatados']} de {fatos['vigentes']} fatos vêm só do "
                    "relato e ainda não têm documento que os sustente."
                ),
                "tom": ATENCAO,
                "base": (
                    "Fatos com estado ALLEGED e nenhuma fonte do tipo OCR_DOCUMENT. "
                    "Relatado e comprovado entram na petição de formas diferentes."
                ),
            }
        )

    if fatos["disponivel"] and fatos["sem_origem"]:
        insights.append(
            {
                "texto": f"{fatos['sem_origem']} fato(s) sem origem registrada.",
                "tom": CRITICO,
                "base": (
                    "Fato sem fonte não deveria existir no agente (é a regra do §47); "
                    "confira antes de usar qualquer um deles numa peça."
                ),
            }
        )

    media_score, quantas = _legibilidade(entregas)
    if media_score is not None and media_score < 75:
        insights.append(
            {
                "texto": f"Legibilidade média das leituras em {media_score}%.",
                "tom": ATENCAO,
                "base": f"Média de {quantas} leitura(s) com nota; abaixo de 75% o campo sai incerto.",
            }
        )

    if not referencia.get("suficiente") and referencia.get("motivo"):
        insights.append(
            {
                "texto": "Ainda não há base histórica para comparar este caso.",
                "tom": NEUTRO,
                "base": str(referencia["motivo"]),
            }
        )

    if not agente.get("disponivel"):
        insights.append(
            {
                "texto": "Parte dos indicadores depende do agente jurídico, que não respondeu.",
                "tom": NEUTRO,
                "base": str(agente.get("motivo") or "Agente jurídico indisponível."),
            }
        )

    return insights


# ------------------------------------------------------------------ ausências


#: O que a tela de BI costuma mostrar e este sistema **não guarda**. Sai declarado para
#: que a seção correspondente apareça vazia com o motivo, em vez de ser preenchida por
#: dedução — um "prazo" inferido da mediana viraria compromisso na cabeça de quem lê.
AUSENCIAS = (
    {
        "campo": "Prioridade",
        "motivo": "O cadastro do caso não tem campo de prioridade.",
    },
    {
        "campo": "Prazo e SLA contratado",
        "motivo": (
            "Nenhum prazo é contratado no sistema. A referência usada no painel é a "
            "mediana dos casos anteriores da mesma categoria, não um SLA."
        ),
    },
    {
        "campo": "Responsável pelo caso",
        "motivo": (
            "Não há atribuição de responsável. O que existe é o entrevistador registrado "
            "em cada entrevista."
        ),
    },
    {
        "campo": "Produto",
        "motivo": "O equivalente no sistema é a categoria do checklist, exibida no resumo.",
    },
    {
        "campo": "Valor da causa",
        "motivo": "O Acervo não registra valor; a estratégia do agente também não o calcula.",
    },
)


# --------------------------------------------------------------------- montagem


def _responsaveis(entrevistas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Quem conduziu cada entrevista — o mais perto de "responsável" que existe.

    Não é dono do caso: é quem atendeu. A distinção está escrita na tela, junto da
    ausência declarada de responsável formal.
    """
    linhas = []
    for entrevista in sorted(entrevistas, key=lambda e: str(e.get("criado_em") or "")):
        nome = (entrevista.get("entrevistador") or "").strip()
        linhas.append(
            {
                "nome": nome or "não informado",
                "informado": bool(nome),
                "desde": entrevista.get("criado_em"),
                "arquivo": entrevista.get("arquivo"),
                "fatos_gerados": entrevista.get("fatos_gerados") or 0,
                "lida": bool(entrevista.get("enviada_em")),
            }
        )
    return linhas


def _etapa_atual(etapas_dossie: list[dict[str, Any]]) -> dict[str, Any] | None:
    """A primeira etapa da linha do processo que ainda não está pronta.

    Etapa `indisponivel` não conta como etapa atual: "não consegui olhar" não é o lugar
    onde o caso está parado.
    """
    for etapa in etapas_dossie:
        if etapa.get("estado") in ("pendente", "andamento", "atencao"):
            return etapa
    return etapas_dossie[-1] if etapas_dossie else None


def compor(
    *,
    caso: dict[str, Any],
    situacao: dict[str, Any],
    entregas: list[dict[str, Any]],
    entrevistas: list[dict[str, Any]],
    assinaturas: list[dict[str, Any]],
    vinculo: dict[str, Any] | None,
    agente: dict[str, Any],
    etapas_dossie: list[dict[str, Any]],
    referencia: dict[str, Any],
    agora: datetime,
) -> dict[str, Any]:
    """Monta o painel a partir de dados já lidos. Sem banco e sem rede — é testável.

    Separada de `montar` de propósito: a leitura é I/O e a composição é regra, e é a
    regra que precisa ser exercitada com caso vazio, caso sem agente e caso completo.
    """
    marcos = marcos_do_caso(caso, entregas, entrevistas, assinaturas, vinculo)
    medidas = medir_etapas(marcos, situacao, agora)
    comparacoes = comparar(medidas, referencia)
    eventos = montar_eventos(caso, entregas, entrevistas, assinaturas, vinculo, agente)
    ocorrencias = montar_ocorrencias(entregas, situacao, vinculo, agente)
    pendencias = montar_pendencias(agente)
    fatos = montar_fatos(agente)

    indicadores = montar_indicadores(
        caso, situacao, entregas, entrevistas, marcos, ocorrencias, pendencias, agente,
        comparacoes, agora,
    )
    for indicador in indicadores:
        if indicador["codigo"] == "movimentacoes":
            indicador["valor"] = len(eventos)

    medidas_com_duracao = [
        m for m in medidas if m["codigo"] != "ciclo" and m["horas"] and m["horas"] > 0
    ]
    total_medido = sum(m["horas"] for m in medidas_com_duracao)
    distribuicao = [
        {
            "codigo": m["codigo"],
            "titulo": m["titulo"],
            "horas": m["horas"],
            "percentual": round(m["horas"] / total_medido * 100, 1) if total_medido else None,
            "em_curso": m["em_curso"],
        }
        for m in medidas_com_duracao
    ]

    progresso = situacao.get("progresso") or {}
    ultima = marcos.get("ultima_movimentacao")
    parado_horas = _horas(ultima, agora)
    atual = _etapa_atual(etapas_dossie)

    return {
        "caso": {
            "id": caso.get("id"),
            "cliente": caso.get("cliente"),
            "categoria_codigo": caso.get("categoria"),
            "categoria": (situacao.get("categoria") or {}).get("nome") or caso.get("categoria"),
            "observacao": caso.get("observacao") or "",
            "aberto_em": caso.get("criado_em"),
            "atualizado_em": caso.get("atualizado_em"),
            "portal_ativo": bool(caso.get("portal_ativo")),
            "caso_ref_agente": (vinculo or {}).get("caso_ref"),
        },
        "resumo": {
            "etapa_atual": atual,
            "etapas": etapas_dossie,
            "progresso": progresso,
            "tempo_em_aberto_horas": _horas(marcos.get("abertura"), agora),
            "ultima_movimentacao": _iso(ultima),
            "dias_sem_movimentacao": round(parado_horas / 24, 1) if parado_horas is not None else None,
            "limiar_parado_dias": _DIAS_PARADO,
            "responsaveis": _responsaveis(entrevistas),
        },
        "indicadores": indicadores,
        "eventos": eventos,
        "etapas_medidas": medidas,
        "distribuicao_do_tempo": distribuicao,
        "comparacao_historica": {
            "referencia": referencia,
            "linhas": comparacoes,
        },
        "ocorrencias": ocorrencias,
        "pendencias": pendencias,
        "fatos": fatos,
        "saude": montar_saude(situacao, ocorrencias, pendencias, agente, marcos, agora),
        "radar": montar_radar(situacao, entregas, agente, pendencias, comparacoes),
        "insights": montar_insights(
            situacao, comparacoes, referencia, medidas, ocorrencias, pendencias, entregas,
            agente, marcos, eventos, fatos, agora,
        ),
        "ausencias": list(AUSENCIAS),
        "agente": {
            "ligado": agente.get("ligado", False),
            "disponivel": agente.get("disponivel", False),
            "vinculado": agente.get("vinculado", False),
            "motivo": agente.get("motivo"),
        },
        "gerado_em": _iso(agora),
    }


def montar(caso_id: str) -> dict[str, Any] | None:
    """O painel do caso. `None` quando o caso não existe.

    Reaproveita `dossie.montar` em vez de refazer a leitura do agente: o dossiê já trata
    agente fora do ar, vínculo órfão e bloco parcial, e ter duas leituras diferentes do
    mesmo agente produziria duas telas discordando entre si sobre o mesmo caso.
    """
    caso = armazenamento.obter_caso(caso_id)
    if caso is None:
        return None

    # O dossiê fala com o agente pela rede; fica fora de qualquer escopo de conexão.
    montado = dossie.montar(caso_id) or {}

    # Uma conexão para o resto da montagem: são dezenas de leituras pequenas, e o banco
    # é remoto — abrir uma conexão por consulta custava mais que as consultas.
    with banco.sessao():
        situacao = casos_ocr.montar_situacao(caso_id) or {}
        entregas = armazenamento.listar_entregas(caso_id)
        entrevistas = armazenamento.listar_entrevistas(caso_id)
        assinaturas = armazenamento.listar_assinaturas(caso_id=caso_id)
        vinculo = armazenamento.obter_vinculo_agente(caso_id)
        agora = datetime.now(timezone.utc)
        referencia = referencia_historica(str(caso.get("categoria")), caso_id, agora)

    return compor(
        caso=caso,
        situacao=situacao,
        entregas=entregas,
        entrevistas=entrevistas,
        assinaturas=assinaturas,
        vinculo=vinculo,
        agente=montado.get("agente") or {"ligado": False, "disponivel": False, "vinculado": False},
        etapas_dossie=montado.get("etapas") or [],
        referencia=referencia,
        agora=agora,
    )
