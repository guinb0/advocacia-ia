"""O que os documentos dizem e a entrevista não registrou.

POR QUE ISTO EXISTE

O OCR lê a página inteira e o formulário guarda meia dúzia de campos. Todo o
resto — o CID que está no laudo, a data de afastamento que está no CNIS, o valor
que está no contracheque — fica no `texto_completo` da extração e não chega a
lugar nenhum. Ninguém abre vinte documentos para conferir se algum deles diz
algo que a conversa não pegou, e é justamente aí que mora o fato que sustenta a
peça.

TODO ACHADO CITA, E A CITAÇÃO É CONFERIDA

O modelo devolve o trecho literal que sustenta cada achado, e este módulo
confere que ele existe no texto do documento antes de mostrar. É a mesma regra
de `app/escuta.py`, e pelo mesmo motivo: quem revisa depois não estava na
conversa nem leu o documento, e para essa pessoa achado inventado e achado
verdadeiro são indistinguíveis. Aqui é pior que na entrevista — o documento é
prova, e um "CID F43.1" que ninguém escreveu vira alegação em juízo.

Achado sem citação conferível não vira "achado fraco". Ele não sai.

POR QUE NÃO USA BUSCA VETORIAL

Os embeddings dos anexos servem para recuperar trecho entre MUITOS documentos —
é o que a petição vai precisar. Aqui o conjunto é o caso inteiro, oito ou vinte
páginas, e ele cabe na janela do modelo. Recuperar por similaridade só
acrescentaria o risco de deixar de fora justamente o trecho que ninguém procurou
— e "o que passou direto" é, por definição, o que ninguém procurou.
"""

from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from typing import Any

import httpx

from . import armazenamento, cache_leitura

log = logging.getLogger("analise_documentos")


class ErroAnaliseDocumentos(RuntimeError):
    """Falha que o usuário precisa ver, com o que dá para fazer a respeito."""


#: Teto por documento. Uma página de OCR raramente passa disso, e o corte evita
#: que um PDF de 40 páginas consuma a janela inteira e empurre os outros anexos
#: para fora — perder documento em silêncio é pior que analisar menos texto.
MAX_CARACTERES_POR_DOCUMENTO = 6000

#: Teto do conjunto. Acima disto o modelo passa a ignorar o meio do prompt, e o
#: que ele ignora ninguém fica sabendo.
#:
#: Era 40 mil, e 40 mil derrubava metade de um caso de verdade. Medido no caso
#: `da5a030b` (46 anexos, 57 mil caracteres de OCR): 15 documentos ficavam de
#: fora — e não uns quaisquer. Ficavam fora 8 notas fiscais de farmácia, 7
#: comprovantes de transporte, os exames e o plano de saúde: exatamente os papéis
#: que carregam DATA e VALOR. A cronologia e os gastos eram montados sem ver os
#: documentos que os produzem, e a tela dizia "cronologia dos fatos" para uma
#: leitura feita sobre a outra metade do caso.
MAX_CARACTERES_TOTAL = 90000

#: Cada documento entra com PELO MENOS isto, mesmo num caso com muitos anexos.
#: Uma nota fiscal cabe inteira aqui — é o que garante que nenhum TIPO de
#: documento fique invisível só por estar no fim da lista.
FATIA_MINIMA_POR_DOCUMENTO = 700

TEMPO_MODELO_S = 60.0

INSTRUCAO = """Você lê documentos de um processo trabalhista e aponta o que eles
dizem e o caso ainda NÃO registrou.

Devolva APENAS JSON: {"achados": [...], "gastos": [...], "cronologia": [...]}

Cada item de cronologia é um acontecimento do caso registrado em documento (acidente,
atendimento, internação, cirurgia, exame, afastamento, decisão do INSS etc.):
{"data":"DD/MM/AAAA","evento":"frase curta do que ocorreu","documento":"nome exato do arquivo","citacao":"trecho LITERAL que traz a data e o evento"}.
Não inclua data de upload; sem data do acontecimento, não inclua o item.

Cada gasto (despesa que o documento comprova — nota fiscal, recibo, comprovante
de farmácia, transporte, consulta, exame, honorário etc.):
{
  "valor": "o valor em reais como está no documento, ex.: R$ 123,45",
  "data": "a data DO GASTO no formato DD/MM/AAAA (a data da compra/serviço; se só
           houver mês/ano, use 01 no dia; se não houver data, deixe vazio)",
  "descricao": "o que foi pago, em poucas palavras (ex.: 'medicamentos', 'corrida
                de aplicativo', 'consulta')",
  "documento": "nome exato do arquivo, como veio na lista",
  "citacao": "trecho LITERAL e contínuo do documento onde o valor aparece"
}

Cada achado:
{
  "informacao": "o que o documento diz, em uma frase",
  "documento": "nome exato do arquivo, como veio na lista",
  "citacao": "trecho LITERAL e contínuo do documento, copiado caractere a caractere",
  "relevancia": "por que isto importa para o caso, em uma frase",
  "parte": "de quem é esta informação — um de: titular, terceiro, empresa, indefinido",
  "papel": "o envolvimento dessa pessoa no caso, em poucas palavras (ex.: reclamante, empregadora, médico, perito, testemunha, preposto, sindicato). Vazio se não der para saber.",
  "contradiz": true se o documento contradiz o que a entrevista registrou, senão false
}

COMO PREENCHER "parte" E "papel":
- "titular": o cliente do escritório, autor da ação — o dono do RG/CPF do caso.
- "empresa": a empregadora / reclamada.
- "terceiro": qualquer outra pessoa citada (médico que assinou o laudo, perito,
  testemunha, preposto, colega, familiar). Em "papel", diga qual é o envolvimento.
- "indefinido": não dá para saber de quem é a informação. Na dúvida, use este —
  atribuir errado é pior que admitir que não se sabe.

REGRAS QUE NÃO SE NEGOCIAM:

1. A citação é copiada do texto do documento, sem reescrever, sem corrigir erro
   de OCR, sem juntar pedaços de lugares diferentes. Se você não consegue copiar
   um trecho contínuo, não faça o achado.
2. Só entra o que a entrevista NÃO registrou, ou o que a contradiz. O que já está
   nos fatos conhecidos não é achado.
3. Nome, CPF e RG já são extraídos como campo. Não os repita como achado.
4. Não deduza. "O laudo é de psiquiatra, então há transtorno mental" não é
   achado; "CID F43.1" escrito no laudo é.
5. Nenhum achado é melhor que achado duvidoso. Lista vazia é resposta válida.
6. Um GASTO também tem citação literal conferível, pela mesma regra. Registre
   todo valor pago que o documento comprovar — cada nota/recibo pode ter vários.
   O que não tiver valor em reais não é gasto. Não invente data.

Máximo 12 achados, os mais relevantes primeiro. Gastos: todos os que houver."""


#: Vocabulário fechado de "de quem é a informação". Fechá-lo é o que permite ao
#: painel agrupar e colorir sem adivinhar sinônimo; o texto livre do envolvimento
#: fica em `papel`. Valor fora da lista vira "indefinido" — atribuir errado a
#: prova a uma parte é pior que dizer que não se sabe.
PARTES_VALIDAS = {"titular", "terceiro", "empresa", "indefinido"}


def _normalizar_parte(bruto: Any) -> str:
    valor = str(bruto or "").strip().lower()
    return valor if valor in PARTES_VALIDAS else "indefinido"


def _normalizar(texto: str) -> str:
    """Para conferir citação: sem acento, sem pontuação, espaço colapsado.

    O OCR troca acento e pontuação com frequência, e exigir igualdade byte a byte
    recusaria citação honesta. O que a conferência protege é contra texto
    INVENTADO, não contra til perdido.
    """
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9\s]", " ", sem_acento.upper())).strip()


def _documentos_do_caso(caso_id: str) -> list[dict[str, str]]:
    """Nome e texto lido de cada anexo que tem leitura."""
    documentos = []
    for entrega in armazenamento.listar_entregas(caso_id):
        detalhe = armazenamento.obter_entrega(entrega["id"])
        if not detalhe:
            continue
        extracao = detalhe.get("extracao") or {}
        texto = str(extracao.get("texto_completo") or "").strip()
        if not texto:
            continue
        documentos.append(
            {
                "id": entrega["id"],
                "arquivo": str(entrega.get("arquivo") or ""),
                "texto": texto[:MAX_CARACTERES_POR_DOCUMENTO],
            }
        )
    return documentos


def _fatos_conhecidos(caso_id: str) -> list[str]:
    """O que a entrevista já registrou, em linhas de 'pergunta: resposta'."""
    conhecidos: list[str] = []
    for entrevista in armazenamento.listar_entrevistas(caso_id):
        for pergunta in entrevista.get("perguntas") or []:
            if not isinstance(pergunta, dict):
                continue
            texto = str(pergunta.get("pergunta") or "").strip()
            valor = str(pergunta.get("resposta") or pergunta.get("valor") or "").strip()
            if texto and valor:
                conhecidos.append(f"{texto}: {valor}")
    return conhecidos


def _apelidos_de_arquivo(caminhos: Any) -> dict[str, str]:
    """Nome curto do arquivo → caminho completo, SÓ quando o nome curto é único.

    POR QUE ISTO EXISTE

    Os anexos chegam com caminho ("HILDEBRANDO_.../04_Notas_Fiscais/Scanner_20250623
    (25).pdf") e é o caminho que vai no cabeçalho de cada documento no prompt. O
    modelo, ao apontar de onde tirou um gasto, responde com o NOME DO ARQUIVO —
    "Scanner_20250623 (25).pdf". A conferência procurava esse texto como chave e
    não achava, então TODO achado era recusado por "atribuição errada".

    Medido no caso `da5a030b`: o modelo devolveu 19 gastos e 13 eventos de
    cronologia, e os 46 anexos foram lidos. Recusados: todos. A tela mostrava
    "cronologia dos fatos" vazia, como se os documentos não dissessem nada.

    POR QUE SÓ QUANDO É ÚNICO

    A conferência existe para impedir que uma citação seja atribuída ao documento
    errado. Se duas pastas têm "Scanner_20250623 (2).pdf", resolver pelo nome
    curto escolheria uma das duas no chute — exatamente o erro que a regra evita.
    Nome curto repetido não ganha apelido, e o achado é recusado como antes.
    """
    candidatos: dict[str, list[str]] = {}
    for bruto in caminhos:
        caminho = str(bruto or "")
        curto = caminho.replace(chr(92), "/").split("/")[-1]
        if curto and curto != caminho:
            candidatos.setdefault(curto, []).append(caminho)
    return {curto: caminhos[0] for curto, caminhos in candidatos.items() if len(caminhos) == 1}


def _resolver_arquivo(nome: str, conhecidos: dict[str, Any]) -> str:
    """O caminho canônico do anexo que o modelo apontou, ou "" se não der para saber."""
    if nome in conhecidos:
        return nome
    apelidos = _apelidos_de_arquivo(conhecidos)
    return apelidos.get(str(nome).replace(chr(92), "/").split("/")[-1], "")


def _cabecalho(arquivo: str) -> str:
    """A linha que separa um anexo do outro no prompt. Também consome orçamento."""
    return f"\n=== {arquivo} ===\n"


def _fatia(texto: str, limite: int) -> str:
    """O documento encurtado pelas DUAS pontas, não só pelo começo.

    Numa nota fiscal o emitente e a data estão no cabeçalho e o VALOR TOTAL está
    no pé. Cortar só o começo entregava ao modelo um gasto sem valor — e um gasto
    sem valor não entra na lista de gastos nem na cronologia.
    """
    if len(texto) <= limite:
        return texto
    cabeca = int(limite * 0.62)
    cauda = max(0, limite - cabeca - 8)
    return texto[:cabeca] + "\n[…]\n" + (texto[-cauda:] if cauda else "")


def _montar_mensagem(
    documentos: list[dict[str, str]], conhecidos: list[str]
) -> tuple[str, list[str]]:
    """A mensagem do modelo e a lista do que NÃO couber nela.

    TODO documento entra, com uma fatia do tamanho do orçamento dividido entre
    eles. Antes era por ordem de chegada até o teto estourar, e aí um `break`
    largava todo o resto — quem estivesse no fim da lista simplesmente não
    existia para a análise, sem aparecer em lugar nenhum. Dividir é o que garante
    que uma classe inteira de documento (as notas fiscais, no caso medido) não
    fique invisível por causa da posição na fila.
    """
    partes = ["O QUE A ENTREVISTA JÁ REGISTROU:"]
    partes.append("\n".join(f"- {c}" for c in conhecidos) if conhecidos else "- (nada ainda)")
    partes.append("\nDOCUMENTOS DO CASO:")

    # O nome de cada anexo também ocupa lugar, e nestes casos ele é comprido
    # ("HILDEBRANDO_.../04_Notas_Fiscais_Farmacia/Scanner_20250623 (12).pdf").
    # Dividir o teto cru pelo número de documentos deixava o último de fora por
    # causa dos cabeçalhos; o desconto é medido, não estimado.
    quantos = max(1, len(documentos))
    cabecalhos = sum(len(_cabecalho(doc["arquivo"])) for doc in documentos)
    disponivel = max(0, MAX_CARACTERES_TOTAL - cabecalhos)
    limite = min(
        MAX_CARACTERES_POR_DOCUMENTO,
        max(FATIA_MINIMA_POR_DOCUMENTO, disponivel // quantos),
    )

    total = 0
    fora: list[str] = []
    for doc in documentos:
        bloco = _cabecalho(doc["arquivo"]) + _fatia(doc["texto"], limite)
        if total + len(bloco) > MAX_CARACTERES_TOTAL:
            # `continue`, e não `break`: o próximo documento pode ser pequeno e
            # ainda caber. O que não couber sai nomeado, para a tela poder dizer.
            fora.append(doc["arquivo"])
            continue
        partes.append(bloco)
        total += len(bloco)

    if fora:
        partes.append(
            f"\n[{len(fora)} de {len(documentos)} documentos não couberam nesta "
            "análise: " + ", ".join(fora[:10]) + ("…]" if len(fora) > 10 else "]")
        )
    return "\n".join(partes), fora


def _chamar_modelo(mensagem: str) -> dict[str, Any]:
    chave = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not chave:
        raise ErroAnaliseDocumentos(
            "Análise dos documentos desligada: falta DEEPSEEK_API_KEY no .env. "
            "Os documentos seguem anexados e legíveis — só não há leitura automática."
        )

    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    try:
        resposta = httpx.post(
            base_url + "/chat/completions",
            headers={"Authorization": f"Bearer {chave}"},
            json={
                "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
                "temperature": 0,
                "response_format": {"type": "json_object"},
                # 12 achados com citação LITERAL passam de 1900 tokens — 2000 de
                # teto truncava a resposta no meio e o JSON inteiro virava
                # "ilegível", perdendo TODOS os achados de uma vez (não só o
                # último). Folga larga; DeepSeek cobra pelo que gera, não pelo teto.
                "max_tokens": 8000,
                "messages": [
                    {"role": "system", "content": INSTRUCAO},
                    {"role": "user", "content": mensagem},
                ],
            },
            timeout=TEMPO_MODELO_S,
        )
        resposta.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("Análise dos documentos falhou: %s", str(exc)[:160])
        raise ErroAnaliseDocumentos(
            "O modelo não respondeu a tempo. Os documentos continuam no caso; "
            "tente a análise de novo."
        ) from exc

    try:
        return json.loads(resposta.json()["choices"][0]["message"]["content"])
    except Exception as exc:
        raise ErroAnaliseDocumentos("Resposta ilegível do modelo.") from exc


def analisar(caso_id: str) -> dict[str, Any]:
    """Lê os anexos do caso e devolve o que eles dizem e a entrevista não pegou.

    A leitura é cara (uma volta na DeepSeek) e o mesmo caso a pede em dois pontos
    quase juntos — o painel de jurimetria e o contexto da petição. Sem cache, cada
    um paga a volta e, pior, podem divergir (o modelo não é 100% determinístico):
    o painel mostraria um conjunto de achados e a peça citaria outro. A assinatura
    é o `atualizado_em` do caso, que `_tocar_caso` bumpa a cada nova entrega ou
    entrevista — documento novo invalida sozinho; nada muda, reaproveita.
    """
    caso = armazenamento.obter_caso(caso_id) or {}
    return _analisar_cacheado(caso_id, str(caso.get("atualizado_em") or ""))


@cache_leitura.por_alguns_segundos(300)
def _analisar_cacheado(caso_id: str, _assinatura: str) -> dict[str, Any]:
    documentos = _documentos_do_caso(caso_id)
    if not documentos:
        return {
            "achados": [],
            "gastos": [],
            "documentos_lidos": 0,
            "aviso": (
                "Nenhum anexo deste caso tem texto lido ainda. Envie os documentos "
                "e espere a leitura terminar."
            ),
        }

    conhecidos = _fatos_conhecidos(caso_id)
    mensagem, documentos_fora = _montar_mensagem(documentos, conhecidos)
    bruto = _chamar_modelo(mensagem)

    # Índice por nome de arquivo, para conferir a citação contra o documento que
    # o modelo apontou — e não contra o conjunto. Citação que existe em OUTRO
    # documento é atribuição errada, e atribuição errada de prova é grave.
    texto_por_arquivo = {d["arquivo"]: _normalizar(d["texto"]) for d in documentos}
    id_por_arquivo = {d["arquivo"]: d["id"] for d in documentos}

    achados: list[dict[str, Any]] = []
    recusados = 0
    for item in bruto.get("achados") or []:
        if not isinstance(item, dict):
            continue
        arquivo = str(item.get("documento") or "").strip()
        citacao = str(item.get("citacao") or "").strip()
        informacao = str(item.get("informacao") or "").strip()
        if not (arquivo and citacao and informacao):
            recusados += 1
            continue

        arquivo = _resolver_arquivo(arquivo, texto_por_arquivo)
        corpo = texto_por_arquivo.get(arquivo) if arquivo else None
        if corpo is None or _normalizar(citacao) not in corpo:
            # Citação que não está no documento apontado: pode ser invenção ou
            # troca de arquivo. Os dois são inaceitáveis num achado que vai
            # sustentar peça, e não há como distinguir um do outro daqui.
            recusados += 1
            continue

        achados.append(
            {
                "informacao": informacao[:300],
                "documento": arquivo,
                "entrega_id": id_por_arquivo[arquivo],
                "citacao": citacao[:400],
                "relevancia": str(item.get("relevancia") or "").strip()[:300],
                # De quem é a informação e qual o envolvimento dessa pessoa: é o
                # que separa, no painel, o dado do cliente do dado de um terceiro.
                "parte": _normalizar_parte(item.get("parte")),
                "papel": str(item.get("papel") or "").strip()[:80],
                "contradiz": bool(item.get("contradiz")),
            }
        )

    if recusados:
        log.info("análise do caso %s: %d achado(s) recusados na conferência", caso_id, recusados)

    gastos = _extrair_gastos(bruto, texto_por_arquivo, id_por_arquivo)
    cronologia = []
    for item in bruto.get("cronologia") or []:
        if not isinstance(item, dict):
            continue
        arquivo = str(item.get("documento") or "").strip()
        citacao = str(item.get("citacao") or "").strip()
        data = str(item.get("data") or "").strip()
        evento = str(item.get("evento") or "").strip()
        if not (arquivo and citacao and data and evento):
            continue
        arquivo = _resolver_arquivo(arquivo, texto_por_arquivo)
        corpo = texto_por_arquivo.get(arquivo) if arquivo else None
        if corpo is None or _normalizar(citacao) not in corpo or _chave_data(data)[0]:
            continue
        cronologia.append({"data": data[:20], "evento": evento[:220], "documento": arquivo,
                           "entrega_id": id_por_arquivo[arquivo], "citacao": citacao[:400]})
    cronologia.sort(key=lambda evento: _chave_data(evento["data"]))

    return {
        "achados": achados[:12],
        # Gastos comprovados nos documentos, EM ORDEM CRONOLÓGICA, cada um ligado
        # ao arquivo de origem (issue "Organizar gastos em ordem cronológica").
        "gastos": gastos,
        "cronologia": cronologia,
        "documentos_lidos": len(documentos) - len(documentos_fora),
        # Quais anexos NÃO entraram, com nome. Um número sozinho ("31 de 46") não
        # deixa ninguém conferir se o que faltou era importante — e o que faltava,
        # no caso medido, eram justamente as notas fiscais.
        "documentos_fora": documentos_fora,
        "aviso_documentos_fora": (
            f"{len(documentos_fora)} de {len(documentos)} anexos não couberam nesta "
            "leitura e não estão refletidos na cronologia nem nos gastos."
            if documentos_fora
            else ""
        ),
        # Contado e mostrado de propósito: silenciar a recusa esconderia um
        # modelo alucinando com frequência, que é o que precisa aparecer.
        "recusados": recusados,
    }


#: A data do gasto para ordenar: "DD/MM/AAAA" vira "AAAAMMDD"; sem data, vai para
#: o fim (a tupla começa com 1, e as datadas com 0).
def _chave_data(bruto: str) -> tuple[int, str]:
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", str(bruto or ""))
    if not m:
        return (1, "")
    dia, mes, ano = m.groups()
    ano = ("20" + ano) if len(ano) == 2 else ano
    try:
        return (0, f"{int(ano):04d}{int(mes):02d}{int(dia):02d}")
    except ValueError:
        return (1, "")


def _extrair_gastos(
    bruto: dict[str, Any],
    texto_por_arquivo: dict[str, str],
    id_por_arquivo: dict[str, str],
) -> list[dict[str, Any]]:
    """Gastos comprovados nos documentos, conferidos pela citação e ordenados.

    Mesma regra dos achados: a citação tem de existir LITERALMENTE no documento
    apontado — gasto sem prova conferível não entra. Cada gasto guarda o
    `entrega_id` de origem para a tela/peça rastrear de onde veio. A ordenação é
    pela data do gasto; sem data, vai para o fim (mantém, mas não some).
    """
    gastos: list[dict[str, Any]] = []
    for item in bruto.get("gastos") or []:
        if not isinstance(item, dict):
            continue
        arquivo = str(item.get("documento") or "").strip()
        citacao = str(item.get("citacao") or "").strip()
        valor = str(item.get("valor") or "").strip()
        if not (arquivo and citacao and valor):
            continue
        arquivo = _resolver_arquivo(arquivo, texto_por_arquivo)
        corpo = texto_por_arquivo.get(arquivo) if arquivo else None
        if corpo is None or _normalizar(citacao) not in corpo:
            continue
        data = str(item.get("data") or "").strip()
        gastos.append(
            {
                "valor": valor[:40],
                "data": data[:20],
                "descricao": str(item.get("descricao") or "").strip()[:120],
                "documento": arquivo,
                "entrega_id": id_por_arquivo[arquivo],
                "citacao": citacao[:400],
            }
        )
    gastos.sort(key=lambda g: _chave_data(g["data"]))
    return gastos
