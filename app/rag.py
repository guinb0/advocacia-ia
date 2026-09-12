"""Recuperação vetorial e sugestões estratégicas fundadas em precedentes reais."""

from __future__ import annotations

import logging
import os
import random
import time
from dataclasses import dataclass
from collections import Counter
from statistics import median
from pathlib import Path
from typing import Any

import httpx
import psycopg
from psycopg.rows import dict_row

from . import llm

log = logging.getLogger("rag")
# As funções, e não o módulo: `buscar_similares` tem um PARÂMETRO chamado
# `tribunais` (a lista de regionais a filtrar), que sombrearia o módulo dentro dela.
from .tribunais import (
    link_do_processo,
    numero_processo_formatado,
    tribunal_do_processo,
)

BASE = Path(__file__).resolve().parent.parent


def carregar_env() -> None:
    """Carrega apenas variáveis ausentes; o ambiente do processo sempre prevalece."""
    caminho = BASE / ".env"
    if not caminho.is_file():
        return
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))


carregar_env()


class ErroRAG(RuntimeError):
    pass


def _consultar_pgvector(
    sql: str,
    parametros: tuple[Any, ...],
    *,
    connect_timeout: int,
    tentativas_maximas: int | None = None,
) -> list[dict[str, Any]]:
    """Executa uma consulta curta, recriando a sessao se a VPN oscilar.

    O pgvector fica atras da VPN 10.200/16. Uma sessao TCP pode morrer mesmo
    quando a rota e a porta ja voltaram; por isso nunca reaproveitamos uma
    conexao quebrada e repetimos apenas esta operacao de leitura, que e segura.
    """
    tentativas = max(
        1,
        tentativas_maximas
        if tentativas_maximas is not None
        else int(os.getenv("PGVECTOR_CONNECT_RETRIES", "4")),
    )
    atraso_base = max(0.05, float(os.getenv("PGVECTOR_RETRY_DELAY", "0.35")))
    ultimo_erro: Exception | None = None
    for tentativa in range(1, tentativas + 1):
        try:
            with psycopg.connect(
                _obrigatoria("DATABASE_URL"),
                connect_timeout=connect_timeout,
                row_factory=dict_row,
                keepalives=1,
                keepalives_idle=15,
                keepalives_interval=5,
                keepalives_count=3,
                tcp_user_timeout=30_000,
            ) as conexao:
                return list(conexao.execute(sql, parametros).fetchall())
        except psycopg.OperationalError as exc:
            ultimo_erro = exc
            if tentativa == tentativas:
                break
            time.sleep(atraso_base * (2 ** (tentativa - 1)) + random.uniform(0, 0.15))
    raise ErroRAG(
        f"pgvector indisponivel depois de {tentativas} tentativas"
    ) from ultimo_erro


def _obrigatoria(nome: str) -> str:
    valor = os.getenv(nome, "").strip()
    if not valor:
        raise ErroRAG(f"variável {nome} não configurada")
    return valor


def vetor_literal(vetor: list[float]) -> str:
    return "[" + ",".join(f"{valor:.9g}" for valor in vetor) + "]"


def gerar_embeddings(textos: list[str], *, timeout: float = 120) -> list[list[float]]:
    """`timeout` é parâmetro porque há dois usos com prazos opostos.

    A ingestão em lote pode esperar dois minutos — ninguém está olhando. Já a
    análise de uma resposta acontece com o cliente na frente, entre uma pergunta
    e a seguinte: lá, esperar mais que alguns segundos é pior que não analisar.
    """
    if not textos:
        return []
    dimensoes = int(os.getenv("EMBEDDINGS_DIMENSIONS", "1536"))
    resposta = httpx.post(
        _obrigatoria("EMBEDDINGS_BASE_URL").rstrip("/") + "/embeddings",
        headers={"Authorization": f"Bearer {_obrigatoria('EMBEDDINGS_API_KEY')}"},
        json={
            "model": _obrigatoria("EMBEDDINGS_MODEL_NAME"),
            "input": textos,
            "dimensions": dimensoes,
        },
        timeout=timeout,
    )
    resposta.raise_for_status()
    dados = sorted(resposta.json()["data"], key=lambda item: item["index"])
    vetores = [item["embedding"] for item in dados]
    if len(vetores) != len(textos) or any(len(v) != dimensoes for v in vetores):
        raise ErroRAG("serviço de embeddings devolveu quantidade ou dimensão inesperada")
    return vetores


@dataclass(frozen=True)
class TrechoSimilar:
    texto: str
    similaridade: float
    titulo: str
    identificador: str | None
    url: str | None
    metadados: dict[str, Any]

    def referencia(self) -> dict[str, Any]:
        """O precedente como a tela e a peça o citam — com link para ABRIR o processo.

        O `url` guardado na fonte vem primeiro, quando existe. Ele quase nunca
        existe: o coletor do DJEN não recebe link da API de comunicações, e medido
        no acervo são 7566 fontes com 2 urls, as duas de consulta de CNPJ. Por isso
        o link é derivado do número CNJ (ver `tribunais.link_do_processo`) — é o
        que leva o advogado à consulta processual do próprio TRT em um clique, que
        é o que ele pediu ao ver a lista de "decisões consultadas".

        `processo_formatado` existe pelo mesmo motivo: o número no acervo é 20
        dígitos seguidos, e ninguém confere processo nesse formato.
        """
        processo = self.metadados.get("numero_processo")
        return {
            "processo": processo,
            "processo_formatado": numero_processo_formatado(processo),
            "tribunal": tribunal_do_processo(processo),
            "resultado": self.metadados.get("rotulo"),
            "vara": self.metadados.get("orgao_julgador"),
            "relator": self.metadados.get("relator"),
            "magistrados": self.metadados.get("magistrados", []),
            "fonte": self.metadados.get("origem"),
            "tipo_documento": self.metadados.get("tipo_documento"),
            "titulo": self.titulo,
            "identificador": self.identificador,
            "url": self.url or link_do_processo(processo),
            "similaridade": round(self.similaridade, 4),
        }


def buscar_similares(
    consulta: str, *, limite: int = 8, timeout: float = 120,
    connect_timeout: int = 10, connect_retries: int | None = None,
    tribunais: list[str] | None = None,
) -> list[TrechoSimilar]:
    """`timeout`/`connect_timeout` curtos para quem chama durante a entrevista.

    O servidor pgvector é remoto e compartilhado, e já ficou fora do ar (ver
    CONTEXTO.md). Com os prazos longos da ingestão, cada resposta analisada
    pagaria 10s parada antes de descobrir que o banco não responde — com o
    cliente esperando do outro lado da mesa.

    `tribunais` restringe a busca aos regionais dados (ex.: `["TRT8"]`) — é como
    a análise fica sobre o estado do caso. Vazio/`None` = acervo inteiro.
    """
    if not consulta.strip():
        return []
    embedding = vetor_literal(gerar_embeddings([consulta[:12000]], timeout=timeout)[0])
    # O tribunal fica no metadados do chunk (`tribunal`, ex.: "TRT8"). Filtra por
    # ele; o que não tem a etiqueta é alcançado pela camada nacional do fallback.
    filtro_tribunal = ""
    params: list[Any] = [embedding]
    if tribunais:
        filtro_tribunal = " AND upper(k.metadados->>'tribunal') = ANY(%s)"
        params.append([t.upper() for t in tribunais])
    params += [embedding, limite * 24]
    sql = f"""
        SELECT k.texto, 1 - (k.embedding <=> %s::vector) AS similaridade,
               f.titulo, f.identificador, f.url, k.metadados
          FROM knowledge_chunks k
          JOIN fontes f ON f.id = k.fonte_id
         WHERE k.embedding IS NOT NULL
           AND f.tipo = 'jurisprudencia'{filtro_tribunal}
         ORDER BY k.embedding <=> %s::vector
         LIMIT %s
    """
    linhas = _consultar_pgvector(
        sql, tuple(params), connect_timeout=connect_timeout,
        tentativas_maximas=connect_retries,
    )
    candidatos = [
        TrechoSimilar(
            texto=linha["texto"],
            similaridade=float(linha["similaridade"]),
            titulo=linha["titulo"],
            identificador=linha["identificador"],
            url=linha["url"],
            metadados=linha["metadados"],
        )
        for linha in linhas
    ]
    def qualidade(trecho: TrechoSimilar) -> float:
        tipo = str(trecho.metadados.get("tipo_documento") or "").casefold()
        origem = str(trecho.metadados.get("origem") or "").casefold()
        ajuste = 0.0
        if any(nome in tipo for nome in ("sentença", "sentenca", "acórdão", "acordao", "decisão", "decisao")):
            ajuste += 0.025
        if any(nome in tipo for nome in ("notificação", "notificacao", "distribuição", "distribuicao", "pauta", "edital")):
            ajuste -= 0.035
        if "despacho" in tipo:
            ajuste -= 0.02
        if origem in {"trt8_juris", "tst"}:
            ajuste += 0.01
        return trecho.similaridade + ajuste

    # Um processo pode render muitos chunks e expedientes. Mantém seu melhor
    # trecho, priorizando conteúdo decisório sobre notificação ou despacho.
    por_processo: dict[str, TrechoSimilar] = {}
    for trecho in candidatos:
        numero = str(trecho.metadados.get("numero_processo") or trecho.identificador or "")
        anterior = por_processo.get(numero)
        if anterior is None or qualidade(trecho) > qualidade(anterior):
            por_processo[numero] = trecho
    ordenados = sorted(por_processo.values(), key=qualidade, reverse=True)
    if not ordenados:
        return []

    # Evita contaminar a amostra com o 30º "menos distante" quando ele já não é
    # comparável ao relato. O piso de seis mantém contexto mínimo para divergência.
    corte = max(0.35, ordenados[0].similaridade - 0.12)
    comparaveis = [trecho for trecho in ordenados if trecho.similaridade >= corte]
    if len(comparaveis) < min(6, limite):
        comparaveis = ordenados[: min(6, limite)]
    return comparaveis[:limite]


def _estatisticas_amostra(similares: list[TrechoSimilar]) -> dict[str, Any]:
    """Resume somente os processos recuperados, sem vender correlação como previsão."""
    resultados = Counter(
        str(t.metadados.get("rotulo"))
        for t in similares
        if t.metadados.get("rotulo")
    )
    varas = Counter(
        str(t.metadados.get("orgao_julgador"))
        for t in similares
        if t.metadados.get("orgao_julgador")
    )
    magistrados: Counter[str] = Counter()
    for trecho in similares:
        nomes = trecho.metadados.get("magistrados") or []
        if isinstance(nomes, str):
            nomes = [nomes]
        magistrados.update(str(nome) for nome in nomes if nome)
    total_resultados = sum(resultados.values())

    def itens(contagem: Counter[str], limite: int = 6) -> list[dict[str, Any]]:
        return [
            {
                "nome": nome,
                "quantidade": quantidade,
                "percentual": round(quantidade * 100 / sum(contagem.values()), 1),
            }
            for nome, quantidade in contagem.most_common(limite)
        ] if contagem else []

    favoraveis = sum(resultados.get(r, 0) for r in ("PROCEDENTE", "PARCIAL", "ACORDO"))
    merito_total = sum(resultados.get(r, 0) for r in ("PROCEDENTE", "PARCIAL", "IMPROCEDENTE"))
    merito_favoravel = sum(resultados.get(r, 0) for r in ("PROCEDENTE", "PARCIAL"))
    similaridades = [trecho.similaridade for trecho in similares]
    return {
        "processos_analisados": len(similares),
        "resultados": itens(resultados),
        "varas": itens(varas),
        "magistrados": itens(magistrados),
        "desfechos_favoraveis_amplos": {
            "quantidade": favoraveis,
            "percentual": round(favoraveis * 100 / total_resultados, 1) if total_resultados else 0,
            "criterio": "PROCEDENTE + PARCIAL + ACORDO",
        },
        "desfechos_merito": {
            "processos": merito_total,
            "favoraveis": merito_favoravel,
            "percentual": round(merito_favoravel * 100 / merito_total, 1) if merito_total else 0,
            "criterio": "PROCEDENTE + PARCIAL, excluindo acordo, extinção e indefinido",
        },
        "similaridade_amostra": {
            "maxima": round(max(similaridades), 4) if similaridades else 0,
            "mediana": round(median(similaridades), 4) if similaridades else 0,
            "minima": round(min(similaridades), 4) if similaridades else 0,
        },
        "aviso": (
            "Estatística descritiva da amostra semanticamente semelhante; "
            "não mede causalidade nem probabilidade de êxito do novo caso."
        ),
    }


INSTRUCAO_ESTRATEGIA = """Você auxilia um advogado trabalhista brasileiro.
Use SOMENTE o relato e os trechos fornecidos. Compare fatos, prova, pedido e
fundamento; coincidência de palavras não basta. O resultado rotulado pertence ao
PROCESSO, não necessariamente ao trecho, então não atribua causalidade sem apoio
textual. Não invente fatos, artigos, valores, juiz ou conclusão.

Para cada ação ou risco: cite precedente existente; informe os fatos que tornam a
comparação aplicável; registre diferenças que podem afastá-la; classifique a força
como alta, média ou baixa. Um único precedente nunca tem força alta. Exponha
precedentes divergentes. Priorize perguntas, provas e providências concretas.
A decisão final é sempre do advogado.

As `perguntas_criticas` aparecem para uma pessoa que pode não ser do Direito.
Escreva perguntas curtas, diretas e prontas para ela ler ao cliente, em português
simples. Evite jargão e nunca diga apenas para "apurar", "investigar" ou
"confirmar o nexo": diga exatamente o que deve ser perguntado.

Responda apenas JSON no formato:
{"resumo":"...","acoes":[{"acao":"...","porque":"...","aplicabilidade":"...","contrapontos":"...","forca":"alta|media|baixa","precedentes":["P1"]}],
"riscos":[{"risco":"...","aplicabilidade":"...","contrapontos":"...","forca":"alta|media|baixa","precedentes":["P2"]}],
"divergencias":[{"ponto":"...","precedentes_favoraveis":["P1"],"precedentes_contrarios":["P2"]}],
"lacunas":["..."],"perguntas_criticas":["..."],
"aviso":"Análise assistiva; requer revisão do advogado."}
"""


def _normalizar_resultado(
    resultado: dict[str, Any],
    validos: set[str],
    documentos_validos: set[str] | None = None,
) -> dict[str, Any]:
    """Descarta referências inventadas e recomendações sem lastro verificável.

    Lastro é precedente OU documento do caso — `sintetizar_estrategia_caso` passa
    `documentos_validos` (os arquivos que realmente entraram no pacote) para que
    uma ação fundamentada só nos fatos do caso, sem precedente, não seja
    descartada; `sugerir_acoes` não passa nada e mantém a exigência antiga de
    sempre ter precedente, porque é tudo que ela tem para se apoiar.
    """
    for chave in ("acoes", "riscos"):
        limpos = []
        for item in resultado.get(chave) or []:
            if not isinstance(item, dict):
                continue
            refs = [str(r) for r in (item.get("precedentes") or []) if str(r) in validos]
            docs = (
                [str(d) for d in (item.get("documentos") or []) if str(d) in documentos_validos]
                if documentos_validos is not None
                else []
            )
            if not refs and not docs:
                continue
            item["precedentes"] = refs
            if documentos_validos is not None:
                item["documentos"] = docs
            forca = str(item.get("forca") or "baixa").casefold()
            item["forca"] = forca if forca in {"alta", "media", "média", "baixa"} else "baixa"
            if item["forca"] == "alta" and len(set(refs)) < 2:
                item["forca"] = "media"
            limpos.append(item)
        resultado[chave] = limpos[:6]
    divergencias = []
    for item in resultado.get("divergencias") or []:
        if not isinstance(item, dict):
            continue
        item["precedentes_favoraveis"] = [str(r) for r in item.get("precedentes_favoraveis", []) if str(r) in validos]
        item["precedentes_contrarios"] = [str(r) for r in item.get("precedentes_contrarios", []) if str(r) in validos]
        if item["precedentes_favoraveis"] or item["precedentes_contrarios"]:
            divergencias.append(item)
    resultado["divergencias"] = divergencias[:4]
    resultado["lacunas"] = [str(x).strip() for x in (resultado.get("lacunas") or []) if str(x).strip()][:8]
    resultado["perguntas_criticas"] = [str(x).strip() for x in (resultado.get("perguntas_criticas") or []) if str(x).strip()][:8]

    if documentos_validos is not None:
        contradicoes = []
        for item in resultado.get("contradicoes") or []:
            if not isinstance(item, dict):
                continue
            docs = [str(d) for d in (item.get("documentos") or []) if str(d) in documentos_validos]
            if len(docs) < 2:
                continue
            item["documentos"] = docs
            contradicoes.append(item)
        resultado["contradicoes"] = contradicoes[:6]

        sensiveis = []
        for item in resultado.get("pontos_sensiveis") or []:
            if not isinstance(item, dict):
                continue
            doc = str(item.get("documento") or "")
            if doc not in documentos_validos:
                continue
            item["documento"] = doc
            sensiveis.append(item)
        resultado["pontos_sensiveis"] = sensiveis[:8]

        partes = []
        for item in resultado.get("partes") or []:
            if not isinstance(item, dict) or not str(item.get("nome") or "").strip():
                continue
            partes.append(
                {
                    "nome": str(item.get("nome") or "").strip()[:120],
                    "relacao": str(item.get("relacao") or "").strip()[:80],
                    "relacao_com_cliente": str(item.get("relacao_com_cliente") or "").strip()[:80]
                    or "não estabelecido",
                    # Vínculo lido no arquivo pesa mais que vínculo ouvido na
                    # entrevista, e o advogado precisa ver de qual se trata sem
                    # abrir o documento. Fonte fora do vocabulário vira o valor
                    # mais fraco: o modelo não decide sozinho que algo é documental.
                    "vinculo_fonte": (
                        str(item.get("vinculo_fonte") or "").strip().casefold()
                        if str(item.get("vinculo_fonte") or "").strip().casefold()
                        in {"documento", "entrevista"}
                        else "não estabelecido"
                    ),
                    "documentos": [
                        str(d) for d in (item.get("documentos") or []) if str(d) in documentos_validos
                    ],
                    "relevancia": str(item.get("relevancia") or "").strip()[:400],
                    "acoes": str(item.get("acoes") or "").strip()[:400],
                }
            )
        resultado["partes"] = partes[:12]

        # Mesma exigência de lastro das ações: oportunidade que não aponta documento
        # do caso nem precedente recuperado é palpite, e palpite não vai para o
        # parecer que o advogado usa para decidir a tese.
        oportunidades = []
        for item in resultado.get("oportunidades") or []:
            if not isinstance(item, dict) or not str(item.get("oportunidade") or "").strip():
                continue
            refs = [str(r) for r in (item.get("precedentes") or []) if str(r) in validos]
            docs = [str(d) for d in (item.get("documentos") or []) if str(d) in documentos_validos]
            if not refs and not docs:
                continue
            oportunidades.append(
                {
                    "oportunidade": str(item.get("oportunidade") or "").strip()[:400],
                    "porque": str(item.get("porque") or "").strip()[:400],
                    "documentos": docs,
                    "precedentes": refs,
                }
            )
        resultado["oportunidades"] = oportunidades[:6]
        resultado["perfil_foro"] = str(resultado.get("perfil_foro") or "").strip()[:1500]

    return resultado


def _precedentes_para_contexto(
    texto_consulta: str,
    *,
    limite: int,
    embedding_timeout: float,
    connect_timeout: int,
    connect_retries: int | None,
) -> tuple[list[Any], list[Any]]:
    """Busca os precedentes mais próximos e devolve (amostra completa, recorte pro modelo).

    Compartilhado por `sugerir_acoes` e `sintetizar_estrategia_caso`: as duas
    fundamentam a resposta nos MESMOS precedentes reais, só muda o que entra
    junto no prompt (relato puro vs. fatos do caso + relato).
    """
    similares = buscar_similares(
        texto_consulta,
        limite=max(limite, 30),
        timeout=embedding_timeout,
        connect_timeout=connect_timeout,
        connect_retries=connect_retries,
    )
    if not similares:
        raise ErroRAG("nenhum precedente vetorizado foi localizado")
    return similares, similares[:limite]


def _formatar_perfil_foro(estatisticas: dict[str, Any]) -> str:
    """O retrato de varas e magistrados da amostra, em texto, para ENTRAR no prompt.

    Estes números já eram calculados, mas só depois da chamada ao modelo — iam
    para a tela sem nunca terem passado pelo raciocínio de quem escreveu o
    parecer. O modelo lia os precedentes um a um e não enxergava o padrão do
    conjunto: "nesta vara, 8 de 10 casos como este foram procedentes".

    Não diz "o juiz do caso" de propósito: na captação o processo ainda não foi
    distribuído. É perfil da amostra semelhante, e o prompt exige que seja
    apresentado assim.
    """
    varas = estatisticas.get("varas") or []
    magistrados = estatisticas.get("magistrados") or []
    if not varas and not magistrados:
        return ""

    linhas = [
        f"Amostra: {estatisticas.get('processos_analisados', 0)} processos semelhantes já julgados."
    ]
    merito = estatisticas.get("desfechos_merito") or {}
    if merito.get("processos"):
        linhas.append(
            f"Desfecho de mérito na amostra: {merito.get('favoraveis', 0)} de "
            f"{merito['processos']} favoráveis ({merito.get('percentual', 0)}%) — "
            f"critério: {merito.get('criterio', '')}."
        )
    if varas:
        linhas.append("Varas/órgãos que mais julgaram casos assim:")
        linhas += [
            f"- {v['nome']}: {v['quantidade']} processo(s) ({v['percentual']}% da amostra)"
            for v in varas
        ]
    if magistrados:
        linhas.append("Magistrados que mais assinaram essas decisões:")
        linhas += [
            f"- {m['nome']}: {m['quantidade']} decisão(ões) ({m['percentual']}% da amostra)"
            for m in magistrados
        ]
    linhas.append(
        "Estes números descrevem a amostra recuperada, não preveem o resultado deste caso "
        "e não indicam quem o julgará."
    )
    return "\n".join(linhas)


def _formatar_precedentes(contexto_modelo: list[Any]) -> str:
    partes = []
    for indice, trecho in enumerate(contexto_modelo, 1):
        ref = trecho.referencia()
        partes.append(
            f"[P{indice}] processo={ref['processo']} resultado={ref['resultado']} "
            f"fonte={ref['fonte']} tipo={ref['tipo_documento']} "
            f"similaridade={ref['similaridade']}\n{trecho.texto[:3500]}"
        )
    return "\n\n".join(partes)


def _fechar_resultado(
    resultado: dict[str, Any],
    similares: list[Any],
    contexto_modelo: list[Any],
    documentos_validos: set[str] | None = None,
) -> dict[str, Any]:
    resultado = _normalizar_resultado(
        resultado, {f"P{i}" for i in range(1, len(contexto_modelo) + 1)}, documentos_validos
    )
    resultado["precedentes"] = [
        {"indice": f"P{i}", **trecho.referencia()}
        for i, trecho in enumerate(contexto_modelo, 1)
    ]
    if similares:
        resultado["estatisticas"] = _estatisticas_amostra(similares)
        resultado["metodologia"] = (
            "Busca vetorial com corte relativo de similaridade, um trecho por processo "
            "e prioridade para sentenças/acórdãos do TRT8/TST/DJEN/DEJT; referências "
            "inexistentes são descartadas antes da resposta."
        )
    return resultado


def sugerir_acoes(
    relato: str,
    *,
    limite: int = 8,
    embedding_timeout: float = 120,
    connect_timeout: int = 10,
    connect_retries: int | None = None,
    model_timeout: float = 120,
) -> dict[str, Any]:
    similares, contexto_modelo = _precedentes_para_contexto(
        relato,
        limite=limite,
        embedding_timeout=embedding_timeout,
        connect_timeout=connect_timeout,
        connect_retries=connect_retries,
    )
    try:
        resultado = llm.chamar(
            INSTRUCAO_ESTRATEGIA,
            f"RELATO:\n{relato[:12000]}\n\nPRECEDENTES:\n" + _formatar_precedentes(contexto_modelo),
            temperatura=0,
            timeout=model_timeout,
        )
    except llm.ErroLLM as exc:
        raise ErroRAG(str(exc)) from exc
    return _fechar_resultado(resultado, similares, contexto_modelo)


INSTRUCAO_ESTRATEGIA_CASO = """Você auxilia um advogado trabalhista brasileiro a preparar o
parecer de UM CASO ESPECÍFICO — não uma pesquisa genérica.

Você recebe até quatro blocos: (1) FATOS DO CASO — evidências extraídas dos documentos que o
cliente entregou, cada uma com a citação literal e a página de onde saiu, e a lista de
PESSOAS CITADAS com seus papéis; (2) RELATO da entrevista, quando houver; (3) PRECEDENTES de
processos semelhantes já julgados; (4) PERFIL DO FORO — como as varas e os magistrados que
julgam casos semelhantes vêm decidindo, medido sobre esses mesmos precedentes.

REGRAS
- O `resumo` deve CONTEXTUALIZAR o caso inteiro NOMEANDO EXPLICITAMENTE cada pessoa envolvida,
  os documentos que ela apresentou, e a dupla relação dela: com o CASO (vítima,
  agressor/assaltante, empregador/chefe, motorista, perito, médico, testemunha) e com o
  CLIENTE (esposa, filho, pai, chefe, colega, desconhecido). Não escreva "a parte" nem "o
  terceiro": escreva o nome. Diga também o que ainda falta e o que o foro sugere.
- `partes`: uma entrada por pessoa relevante citada nos documentos. `relacao` é o papel no
  CASO; `relacao_com_cliente` é o vínculo pessoal/profissional com o cliente do escritório;
  `documentos` são os arquivos em que ela aparece.
- **CRUZE OS DOCUMENTOS COM O RELATO PARA ESTABELECER O VÍNCULO.** Um documento quase nunca
  diz de quem a pessoa é parente — um resumo de alta traz "Paciente: Artur Nunes" e nada
  mais. Mas o cliente costuma dizer isso na entrevista ("meu filho Artur se acidentou"). Ao
  encontrar um nome sem vínculo nos documentos, PROCURE esse nome no RELATO e use o vínculo
  que o cliente declarou. Preencha `relacao_com_cliente` com ele e registre em
  `vinculo_fonte` de onde veio: "documento" (o arquivo declara), "entrevista" (o cliente
  disse no relato) ou "não estabelecido". Quando vier da entrevista, cite em `relevancia` a
  passagem que sustenta o vínculo.
- Nunca invente parentesco, e NÃO deduza vínculo por sobrenome igual — sobrenome coincidente
  não é prova de filiação. Sem documento nem relato que diga, use "não estabelecido".
- Toda ação, risco ou contradição que citar um fato do caso precisa apontar de qual
  documento ele veio, em `documentos`. Fato sem essa origem não pode aparecer na resposta.
  NÃO invente fato nem pessoa que não esteja nas evidências ou no relato.
- `contradicoes`: quando dois documentos do PRÓPRIO caso divergem entre si (data, nome,
  empregador, valor, função) — cite os dois arquivos e o que diverge. Vazio se não houver.
- `pontos_sensiveis`: dado de saúde física/mental, violência sofrida, ou informação que a
  parte contrária poderia usar contra o cliente — para o advogado ter cuidado ao usar,
  não para reforçar pedido.
- `lacunas` inclui tanto o que falta PROVAR quanto item obrigatório do checklist ainda sem
  documento (virá listado, quando houver).
- `oportunidades`: brechas e pontos de alavancagem concretos deste caso — tese que a vara já
  vem acolhendo, prova que o adversário dificilmente produz, prazo/preclusão a explorar,
  cumulação de pedidos que os precedentes sustentam. Cada uma amarrada a `documentos` e/ou
  `precedentes`. Oportunidade sem lastro não entra.
- `perfil_foro`: leitura do bloco PERFIL DO FORO — o que os números dizem sobre onde causas
  como esta são julgadas e por quem, e o que isso muda na condução. Use SOMENTE as varas e
  magistrados que aparecem naquele bloco, com os números que vieram. NÃO afirme que este caso
  será julgado por eles: o processo ainda não foi distribuído, e a amostra é dos precedentes
  semelhantes. Se o bloco não vier, deixe vazio.
- Precedente sustenta ação/risco do mesmo jeito que numa pesquisa comum: força "alta" nunca
  com um único precedente, sempre citando o número [P1], [P2] etc.
- Não avalie chance de êxito, não estime valor de causa, não decida se um item do checklist
  está cumprido — isso é sempre do advogado.

Responda apenas JSON no formato:
{"resumo":"...",
 "partes":[{"nome":"...","relacao":"cliente|vítima|agressor|empregador|motorista|perito|médico|testemunha|...","relacao_com_cliente":"esposa|filho|chefe|colega|agressor|não estabelecido|...","vinculo_fonte":"documento|entrevista|não estabelecido","documentos":["arquivo.pdf"],"relevancia":"...","acoes":"..."}],
 "oportunidades":[{"oportunidade":"...","porque":"...","documentos":["arquivo.pdf"],"precedentes":["P1"]}],
 "perfil_foro":"...",
 "acoes":[{"acao":"...","porque":"...","documentos":["arquivo.pdf"],"aplicabilidade":"...","contrapontos":"...","forca":"alta|media|baixa","precedentes":["P1"]}],
 "riscos":[{"risco":"...","documentos":["arquivo.pdf"],"aplicabilidade":"...","contrapontos":"...","forca":"alta|media|baixa","precedentes":["P2"]}],
 "contradicoes":[{"ponto":"...","documentos":["a.pdf","b.pdf"]}],
 "pontos_sensiveis":[{"ponto":"...","documento":"arquivo.pdf"}],
 "divergencias":[{"ponto":"...","precedentes_favoraveis":["P1"],"precedentes_contrarios":["P2"]}],
 "lacunas":["..."],"perguntas_criticas":["..."],
 "aviso":"Análise assistiva; requer revisão do advogado."}
"""


def sintetizar_estrategia_caso(
    caso_id: str,
    *,
    relato: str = "",
    limite: int = 8,
    embedding_timeout: float = 120,
    connect_timeout: int = 10,
    connect_retries: int | None = None,
    model_timeout: float = 120,
) -> dict[str, Any]:
    """A mesma síntese de `sugerir_acoes`, fundamentada nos documentos do caso.

    `conciliacao.montar_pacote_caso` já reduziu cada documento a evidências com
    citação e página — aqui isso só é achatado em texto e mandado junto do
    relato (quando houver) e dos precedentes recuperados pela MESMA busca
    vetorial de `sugerir_acoes`.
    """
    from . import conciliacao

    pacote = conciliacao.montar_pacote_caso(caso_id)
    if not pacote["documentos"] and not relato.strip():
        raise ErroRAG(
            "O caso não tem documentos lidos nem relato informado — nada para analisar."
        )

    texto_fatos = conciliacao.texto_para_modelo(pacote)
    consulta = (relato.strip() + "\n\n" + texto_fatos)[:8000] if relato.strip() else texto_fatos

    # Precedente é ENRIQUECIMENTO, não requisito: os documentos do caso são o
    # material principal. Se o banco vetorial não responde (remoto, compartilhado,
    # já saiu do ar — ver CONTEXTO.md) ou os embeddings não estão configurados, o
    # parecer ainda sai, marcado `com_precedentes: false`. É a mesma degradação
    # honesta que a análise de resposta da entrevista já faz.
    try:
        similares, contexto_modelo = _precedentes_para_contexto(
            consulta,
            limite=limite,
            embedding_timeout=embedding_timeout,
            connect_timeout=connect_timeout,
            connect_retries=connect_retries,
        )
        com_precedentes = True
    except Exception as exc:  # noqa: BLE001 - fronteira com o banco de precedentes
        log.warning("parecer sem precedentes: %s", str(exc)[:160])
        similares, contexto_modelo, com_precedentes = [], [], False

    mensagem = f"FATOS DO CASO:\n{texto_fatos[:12000]}\n\n"
    if relato.strip():
        mensagem += f"RELATO DA ENTREVISTA:\n{relato[:6000]}\n\n"
    if contexto_modelo:
        mensagem += "PRECEDENTES:\n" + _formatar_precedentes(contexto_modelo)
        # O perfil sai da amostra INTEIRA (`similares`), não do recorte que foi
        # para o prompt: a estatística fica mais estável com 30 processos do que
        # com os 8 citáveis, e é a mesma que a tela mostra depois — os números do
        # texto e os do painel não podem divergir.
        perfil_foro = _formatar_perfil_foro(_estatisticas_amostra(similares))
        if perfil_foro:
            mensagem += "\n\nPERFIL DO FORO (amostra dos precedentes acima):\n" + perfil_foro
    else:
        mensagem += (
            "PRECEDENTES: nenhum disponível nesta análise. Baseie ações e riscos "
            "apenas nos fatos do caso; NÃO invente número de processo nem cite "
            "precedente. Deixe `precedentes` vazio em cada item. Não há PERFIL DO "
            "FORO nesta análise: deixe `perfil_foro` vazio."
        )

    try:
        resultado = llm.chamar(
            INSTRUCAO_ESTRATEGIA_CASO, mensagem, temperatura=0, timeout=model_timeout
        )
    except llm.ErroLLM as exc:
        raise ErroRAG(str(exc)) from exc

    documentos_validos = {d["arquivo"] for d in pacote["documentos"]}
    resultado = _fechar_resultado(resultado, similares, contexto_modelo, documentos_validos)
    resultado["com_precedentes"] = com_precedentes
    resultado["pacote"] = {
        "documentos": sorted(documentos_validos),
        "pendentes": pacote["pendentes"],
        "lacunas_checklist": pacote["lacunas_checklist"],
    }
    return resultado
