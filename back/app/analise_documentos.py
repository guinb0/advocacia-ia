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

import hashlib
import json
import logging
import os
import re
import unicodedata
from typing import Any

import httpx

from . import armazenamento, cache_leitura, custos_api, skill_de_arquivo

log = logging.getLogger("analise_documentos")


class ErroAnaliseDocumentos(RuntimeError):
    """Falha que o usuário precisa ver, com o que dá para fazer a respeito."""


class RespostaCortada(ErroAnaliseDocumentos):
    """O modelo bateu no teto de tokens: o JSON veio pela metade e nada dele é aproveitável."""


#: Teto por documento. O corte evita que um PDF de 40 páginas consuma a janela
#: inteira e empurre os outros anexos para fora — perder documento em silêncio é
#: pior que analisar menos texto. Era 6 mil, e 6 mil é uma página e meia: o
#: resto do laudo, da CTPS e do processo do INSS nunca era lido, e a análise
#: "deixava passar" exatamente o que estava depois da primeira página.
MAX_CARACTERES_POR_DOCUMENTO = int(os.getenv("ANALISE_MAX_CARACTERES_DOCUMENTO", "25000"))

#: Teto do conjunto. Acima disto o modelo passa a ignorar o meio do prompt, e o
#: que ele ignora ninguém fica sabendo.
#:
#: Era 40 mil, e 40 mil derrubava metade de um caso de verdade. Medido no caso
#: `da5a030b` (46 anexos, 57 mil caracteres de OCR): 15 documentos ficavam de
#: fora — e não uns quaisquer. Ficavam fora 8 notas fiscais de farmácia, 7
#: comprovantes de transporte, os exames e o plano de saúde: exatamente os papéis
#: que carregam DATA e VALOR. A cronologia e os gastos eram montados sem ver os
#: documentos que os produzem, e a tela dizia "cronologia dos fatos" para uma
#: leitura feita sobre a outra metade do caso. Depois virou 90 mil; com o teto
#: por documento maior, 250 mil (~75 mil tokens) ainda cabe no contexto dos dois
#: provedores (Gemini e DeepSeek).
MAX_CARACTERES_TOTAL = int(os.getenv("ANALISE_MAX_CARACTERES_TOTAL", "250000"))

#: Quantos achados a leitura devolve. Era 12 — num caso com 40 anexos, doze
#: achados é garantir que a maior parte do que os documentos dizem se perca.
MAX_ACHADOS = 60

#: Cada documento entra com PELO MENOS isto, mesmo num caso com muitos anexos.
#: Uma nota fiscal cabe inteira aqui — é o que garante que nenhum TIPO de
#: documento fique invisível só por estar no fim da lista.
FATIA_MINIMA_POR_DOCUMENTO = 700

#: Modelo com raciocínio + 58 documentos passou de 90 s em produção e a análise inteira
#: virava "o modelo não respondeu a tempo". 240 s cobre o pior caso medido com folga.
TEMPO_MODELO_S = float(os.getenv("ANALISE_TIMEOUT_S", "240"))

ESFORCO_RACIOCINIO = os.getenv("ANALISE_ESFORCO_RACIOCINIO", "medium").strip() or "medium"

INSTRUCAO = """Você lê os documentos de um caso jurídico (trabalhista, previdenciário ou de
qualquer outra área) e aponta o que eles dizem e o caso ainda NÃO registrou.

Devolva APENAS JSON: {"achados": [...], "gastos": [...], "cronologia": [...], "contradicoes": [...], "diagnostico": {...}}

diagnostico: {"sentido":"POSITIVO ou NEGATIVO","motivo":"uma frase"}.
POSITIVO se os documentos sustentam o relato e não divergem. NEGATIVO se um documento contradiz a
entrevista, se dois documentos se contradizem, ou se falta prova do fato central. Sem percentual.

Cada contradição entre documentos (não entre documento e entrevista — essa vai em "contradiz" do achado):
{"titulo":"o que diverge","o_que_diverge":"uma frase","fontes":[{"documento":"nome exato","citacao":"trecho LITERAL","valor":"o que este trecho diz"}]}.
Exige duas fontes, de documentos diferentes, com citação literal de cada um. Sem as duas, não registre.

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
2. Só entra o que a entrevista NÃO registrou, o que a contradiz, ou o que dá
   PRECISÃO a um fato que ela só mencionou por alto (a data exata, o valor, o
   CID, o número do benefício, o nome do médico, o horário). O que já está nos
   fatos conhecidos com a mesma precisão não é achado.
3. Nome, CPF e RG já são extraídos como campo. Não os repita como achado.
4. Não deduza. "O laudo é de psiquiatra, então há transtorno mental" não é
   achado; "CID F43.1" escrito no laudo é.
5. Nenhum achado é melhor que achado duvidoso. Lista vazia é resposta válida.
6. Um GASTO também tem citação literal conferível, pela mesma regra. Registre
   todo valor pago que o documento comprovar — cada nota/recibo pode ter vários.
   O que não tiver valor em reais não é gasto. Não invente data.

EXTRAIA O MÁXIMO. Leia CADA documento inteiro, do começo ao fim, antes de
responder — conclusão, diagnóstico, valores e assinaturas costumam estar nas
últimas linhas. Passe por todos os documentos da lista, não só pelos primeiros.
Cada dado útil vira um achado próprio (três CIDs são três achados; dois
salários em datas diferentes, dois achados). Um achado a mais nunca atrapalha
o advogado; um dado que você deixa passar pode custar um pedido na petição.

Até 60 achados, os mais relevantes primeiro. Cronologia: todos os
acontecimentos datados. Gastos: todos os que houver."""

#: Onde cada critério da skill documental entra no JSON acima. A skill diz O QUE olhar em
#: cada documento; este texto só diz em que chave a conclusão vai.
_COMO_APLICAR_A_SKILL = """COMO APLICAR OS CRITÉRIOS DA SKILL NESTA RESPOSTA:
- Analise documento a documento como a skill manda (pontos fortes, vulnerabilidades, inconsistências,
  atualizado ou desatualizado, pode melhorar ou não). Cada conclusão com trecho literal vira um achado:
  a informação em "informacao", o porquê (fortalece, enfraquece, está velho demais para a ação, dá para
  obter versão melhor) em "relevancia".
- Documento desatualizado para a ação (laudo, PPP, comprovante, certidão, extrato antigos) é achado: cite a
  data que o torna velho e diga em "relevancia" por que enfraquece e o que pedir no lugar.
- Inconsistência entre dois documentos (nome, data, valor, assinatura) vai em "contradicoes", com as duas
  citações. Inconsistência entre documento e entrevista vai no achado com "contradiz": true.
- Prova fraca ou faltando que a skill manda apontar entra no "diagnostico" (NEGATIVO se falta prova do
  fato central)."""


def instrucao_padrao() -> str:
    """A instrução da leitura do caso: formato e regras deste módulo + critérios da skill documental."""
    criterios = skill_de_arquivo.criterios_documentais(
        r"^3\.5\b", r"^3\.6\b", r"^Arquivos duplicados",
    )
    if not criterios:
        return INSTRUCAO
    return f"{INSTRUCAO}\n\n{_COMO_APLICAR_A_SKILL}\n\n{criterios}"


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
    """Nome e texto lido de cada anexo que tem leitura.

    UMA consulta para o caso inteiro, e não uma por arquivo.

    Antes eram `listar_entregas` + um `obter_entrega` por anexo — e `obter_entrega`
    abre conexão própria e ainda vai perguntar ao agente jurídico se existe OCR
    espelhado daquele arquivo. Medido em 12/09/2026 no caso `da5a030b` (46 anexos):
    93 consultas e 27s só para montar esta lista, com a tela do advogado parada. E o
    espelho do agente, que custava 46 dessas consultas, hoje não existe para
    NENHUMA entrega do banco — a busca nunca acha nada.

    `listar_extracoes_do_caso` já resolvia isso e foi criada para isto mesmo (ver o
    docstring dela); este caminho simplesmente não a usava. O que se perde é o
    enriquecimento pelo agente em entrega antiga sem extração local — inexistente
    hoje, e ainda disponível em `obter_entrega` nas telas de um documento só.
    """
    documentos = []
    for entrega in armazenamento.listar_extracoes_do_caso(caso_id):
        texto = str((entrega.get("extracao") or {}).get("texto_completo") or "").strip()
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


def _limite_por_documento(tamanhos: list[int], disponivel: int) -> int:
    """O maior corte por documento em que o conjunto ainda cabe no orçamento.

    Dividir o orçamento em partes iguais desperdiçava o espaço dos documentos
    curtos: uma nota fiscal de 800 caracteres "reservava" 3 mil, e o laudo de
    20 mil ficava cortado nos mesmos 3 mil. Aqui o que o curto não usa vai para
    o longo — o corte só alcança quem é maior que ele.
    """
    if not tamanhos:
        return MAX_CARACTERES_POR_DOCUMENTO
    if sum(min(t, MAX_CARACTERES_POR_DOCUMENTO) for t in tamanhos) <= disponivel:
        return MAX_CARACTERES_POR_DOCUMENTO
    restante, faltam = disponivel, len(tamanhos)
    for tamanho in sorted(tamanhos):
        corte = restante // faltam
        if tamanho > corte:
            return max(FATIA_MINIMA_POR_DOCUMENTO, min(MAX_CARACTERES_POR_DOCUMENTO, corte))
        restante -= tamanho
        faltam -= 1
    return MAX_CARACTERES_POR_DOCUMENTO


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
    cabecalhos = sum(len(_cabecalho(doc["arquivo"])) for doc in documentos)
    disponivel = max(0, MAX_CARACTERES_TOTAL - cabecalhos)
    limite = _limite_por_documento([len(doc["texto"]) for doc in documentos], disponivel)

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


def _texto_da_escolha(escolha: dict[str, Any]) -> str:
    """Extrai o texto útil da escolha OpenAI-compatível.

    Modelos de raciocínio (Gemini 3.x) às vezes devolvem `content` vazio ou em
    lista de partes, e o JSON da análise some — a tela só via "ilegível".
    """
    msg = escolha.get("message") if isinstance(escolha.get("message"), dict) else {}
    conteudo = msg.get("content")
    if isinstance(conteudo, list):
        partes: list[str] = []
        for parte in conteudo:
            if isinstance(parte, dict):
                partes.append(str(parte.get("text") or parte.get("content") or ""))
            elif parte:
                partes.append(str(parte))
        conteudo = "\n".join(partes)
    texto = str(conteudo or "").strip()
    if texto:
        return texto
    for chave in ("reasoning", "reasoning_content"):
        alt = msg.get(chave)
        if isinstance(alt, str) and alt.strip():
            return alt.strip()
    return ""


def _json_do_modelo(resposta: httpx.Response) -> dict[str, Any]:
    """Aceita JSON puro e o JSON embrulhado em Markdown que o gateway devolve.

    Cópia do contrato de `escuta._json_do_modelo`: `response_format` nem sempre
    é cumprido; fence ```json ou texto antes do objeto derrubava a análise inteira.
    """
    escolha: dict[str, Any] = {}
    try:
        corpo = resposta.json()
        escolha = (corpo.get("choices") or [{}])[0] or {}
        texto = _texto_da_escolha(escolha)
        if not texto:
            raise ValueError("content vazio")
        if texto.startswith("```"):
            texto = re.sub(r"^```(?:json)?\s*", "", texto, flags=re.IGNORECASE)
            texto = re.sub(r"\s*```$", "", texto).strip()
        try:
            dado = json.loads(texto)
        except json.JSONDecodeError:
            inicio, fim = texto.find("{"), texto.rfind("}")
            if inicio < 0 or fim <= inicio:
                raise
            dado = json.loads(texto[inicio : fim + 1])
        if not isinstance(dado, dict):
            raise ValueError("raiz não é objeto")
        return dado
    except Exception as exc:
        motivo = escolha.get("finish_reason") or "desconhecido"
        preview = (_texto_da_escolha(escolha) or "")[:120]
        log.warning(
            "Análise dos documentos ilegível (finish_reason=%s, preview=%r): %s",
            motivo,
            preview,
            exc,
        )
        if motivo == "length":
            raise RespostaCortada(
                "A resposta do modelo foi cortada por tamanho. Tente de novo; "
                "se persistir, analise com menos documentos anexados."
            ) from exc
        raise ErroAnaliseDocumentos(
            "Resposta ilegível do modelo. Tente de novo em instantes."
        ) from exc


def _chamar_modelo(
    mensagem: str,
    *,
    instrucao: str | None = None,
    max_tokens: int | None = None,
    tempo_s: float | None = None,
) -> dict[str, Any]:
    """Executa a análise pelo provedor configurado, com resposta JSON auditável.

    OpenRouter é o caminho padrão do ambiente de produção. DeepSeek direto fica
    apenas como compatibilidade para instalações que já o configuravam.
    """
    chave_openrouter = os.getenv("OPENROUTER_API_KEY", "").strip()
    chave_deepseek = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not chave_openrouter and not chave_deepseek:
        raise ErroAnaliseDocumentos(
            "Análise dos documentos desligada: falta OPENROUTER_API_KEY (ou DEEPSEEK_API_KEY) no .env. "
            "Os documentos seguem anexados e legíveis — só não há leitura automática."
        )

    usando_openrouter = bool(chave_openrouter)
    chave = chave_openrouter or chave_deepseek
    base_url = (
        "https://openrouter.ai/api/v1"
        if usando_openrouter
        else os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    )
    if usando_openrouter:
        modelo = (
            os.getenv("OPENROUTER_MODELO_ANALISE", "").strip()
            or "google/gemini-3.7-flash"
        )
    else:
        modelo = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    payload: dict[str, Any] = {
        "model": modelo,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        # 12 achados com citação LITERAL passam de 1900 tokens — 2000 de
        # teto truncava a resposta no meio e o JSON inteiro virava
        # "ilegível", perdendo TODOS os achados de uma vez (não só o
        # último). Folga larga; DeepSeek cobra pelo que gera, não pelo teto.
        "max_tokens": max_tokens or int(os.getenv("OPENROUTER_ANALISE_MAX_TOKENS", "16000")),
        "messages": [
            # `instrucao` permite a OUTRA análise (skill documental) reusar este cliente
            # (retentativa, reasoning, custos) sem duplicar a chamada.
            {"role": "system", "content": instrucao or instrucao_padrao()},
            {"role": "user", "content": mensagem},
        ],
    }
    # Gemini 3.x gasta a saída em "thinking" e deixa `content` vazio → ilegível.
    # `effort: none` NÃO serve: nesses modelos o reasoning é obrigatório e o
    # OpenRouter responde 400 ("Reasoning is mandatory for this endpoint") — e
    # toda análise falhava em silêncio, com o brief vazio chegando à geração da
    # peça. `low` + `exclude` mantém o raciocínio curto e o tira da resposta,
    # deixando o JSON em `content`. Medido no caso de 58 documentos: 12 s.
    # `low` deixava passar dado de documento longo; `medium` pensa o bastante
    # para ler o conjunto inteiro, e o `TEMPO_MODELO_S` de 240 s absorve a
    # diferença.
    if usando_openrouter:
        payload["reasoning"] = {"effort": ESFORCO_RACIOCINIO, "exclude": True}

    cabecalhos = {"Authorization": f"Bearer {chave}"}
    if usando_openrouter:
        cabecalhos["HTTP-Referer"] = os.getenv("OPENROUTER_REFERER", "http://localhost:3000")

    def _enviar(corpo: dict[str, Any]) -> httpx.Response:
        return httpx.post(
            base_url + "/chat/completions", headers=cabecalhos, json=corpo, timeout=tempo_s or TEMPO_MODELO_S
        )

    try:
        try:
            resposta = _enviar(payload)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            # Uma segunda tentativa: queda de conexão ou timeout isolado não deve
            # derrubar a leitura de todos os documentos do caso.
            log.warning("Análise dos documentos: %s; tentando de novo", type(exc).__name__)
            resposta = _enviar(payload)
        # Modelo que recusa o parâmetro de reasoning: repete sem ele em vez de
        # perder a análise inteira por causa de um detalhe de provedor.
        if resposta.status_code == 400 and "reasoning" in payload and "easoning" in resposta.text:
            log.warning("Análise dos documentos: provedor recusou reasoning (%s); repetindo sem ele",
                        resposta.text[:160])
            sem_reasoning = {k: v for k, v in payload.items() if k != "reasoning"}
            resposta = _enviar(sem_reasoning)
        resposta.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detalhe = f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
        log.warning("Análise dos documentos falhou: %s", detalhe)
        raise ErroAnaliseDocumentos(
            f"O provedor do modelo recusou a análise ({detalhe}). Os documentos continuam "
            "no caso; avise quem administra o sistema."
        ) from exc
    except httpx.HTTPError as exc:
        log.warning("Análise dos documentos falhou: %s", str(exc)[:160])
        raise ErroAnaliseDocumentos(
            "O modelo não respondeu a tempo. Os documentos continuam no caso; "
            "tente a análise de novo."
        ) from exc

    if usando_openrouter:
        custos_api.registrar("openrouter", modelo, "analise_documentos", resposta)
    return _json_do_modelo(resposta)


def analisar(caso_id: str) -> dict[str, Any]:
    """Lê os anexos do caso e devolve o que eles dizem e a entrevista não pegou.

    A leitura é cara (uma volta na DeepSeek) e o mesmo caso a pede em dois pontos
    quase juntos — o painel de jurimetria e o contexto da petição. Sem cache, cada
    um paga a volta e, pior, podem divergir (o modelo não é 100% determinístico):
    o painel mostraria um conjunto de achados e a peça citaria outro. A assinatura
    é o `atualizado_em` do caso, que `_tocar_caso` bumpa a cada nova entrega ou
    entrevista — documento novo invalida sozinho; nada muda, reaproveita.
    """
    from .agente import contexto_caso

    documentos = _documentos_do_caso(caso_id)
    assinatura = _assinatura_dos_textos(documentos, _fatos_conhecidos(caso_id))
    guardada = contexto_caso.analise_guardada(caso_id, assinatura) if documentos else None
    if guardada is not None:
        return {**guardada, "reaproveitada": True}
    resultado = _analisar_cacheado(caso_id, assinatura)
    if documentos and not resultado.get("aviso"):
        contexto_caso.guardar_analise(caso_id, assinatura, resultado)
    return resultado


def _assinatura_dos_textos(documentos: list[dict[str, str]], fatos: list[str]) -> str:
    """Muda só quando um texto lido ou uma resposta da entrevista entra ou muda — não por qualquer toque no caso."""
    partes = sorted((d["id"], hashlib.sha1(d["texto"].encode("utf-8")).hexdigest()) for d in documentos)
    return hashlib.sha1(json.dumps([partes, sorted(fatos)]).encode("utf-8")).hexdigest()


def relatorio_global(caso_id: str) -> dict[str, Any]:
    """Camada não destrutiva de relevância para TODOS os documentos do caso.

    A classificação técnica nunca decide descarte: anexo sem OCR ou sem
    identificação volta como INDETERMINADO e pede revisão humana.
    """
    documentos = _documentos_do_caso(caso_id)
    fatos = _fatos_conhecidos(caso_id)
    if not documentos:
        return {
            "contexto_compreendido": "Não há documento com texto disponível.",
            "documentos": [],
            "documentos_faltantes": [],
            "contradicoes": [],
            "atencao_humana": ["Envie documentos ou aguarde a leitura OCR."],
        }
    leitura = analisar(caso_id)
    por_arquivo: dict[str, list[dict[str, Any]]] = {}
    for achado in leitura.get("achados") or []:
        por_arquivo.setdefault(str(achado.get("documento") or ""), []).append(achado)
    itens = []
    for doc in documentos:
        achados = por_arquivo.get(doc["arquivo"], [])
        contradiz = any(bool(a.get("contradiz")) for a in achados)
        if contradiz:
            relevancia, acao = "ESSENCIAL", "REVISAR_MANUALMENTE"
        elif achados:
            relevancia, acao = "RELEVANTE", "PRIORIZAR"
        else:
            relevancia, acao = "INDETERMINADO", "REVISAR_MANUALMENTE"
        itens.append({
            "id": doc["id"], "arquivo": doc["arquivo"],
            "tipo_identificado": "Não identificado" if not achados else "Identificado a partir do conteúdo",
            "confianca": 85 if achados else 0,
            "resumo": "; ".join(str(a.get("informacao") or "") for a in achados)[:2000] or "Sem conclusão automática segura.",
            "relacao_com_fatos": "; ".join(str(a.get("relevancia") or "") for a in achados)[:2000] or "Ainda precisa ser confrontado com a narrativa do caso.",
            "fatos_comprovados": [str(a.get("informacao") or "") for a in achados],
            "relevancia": relevancia,
            "justificativa": "Há informação documental relacionada ao caso." if achados else "Não foi descartado: falta contexto suficiente para concluir sua utilidade.",
            "relacoes": [],
            "inconsistencias": [str(a.get("informacao") or "") for a in achados if a.get("contradiz")],
            "acao_recomendada": acao,
        })
    return {
        "contexto_compreendido": "\n".join(fatos)[:2500] or "Contexto ainda depende da entrevista e dos documentos.",
        "documentos": itens,
        "documentos_faltantes": [],
        "contradicoes": [a for a in leitura.get("achados") or [] if a.get("contradiz")],
        "atencao_humana": ["Documentos sem achados automáticos foram mantidos como indeterminados, não como irrelevantes."],
    }


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
    contradicoes = _contradicoes_entre_documentos(bruto, texto_por_arquivo)

    return {
        "achados": achados[:MAX_ACHADOS],
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
        "contradicoes": contradicoes,
        "diagnostico": _diagnostico_do_caso(achados[:MAX_ACHADOS], contradicoes, bruto.get("diagnostico")),
    }


def _contradicoes_entre_documentos(bruto: dict[str, Any], texto_por_arquivo: dict[str, str]) -> list[dict[str, Any]]:
    """Divergência entre dois documentos, só quando as duas citações conferem."""
    saida: list[dict[str, Any]] = []
    for item in bruto.get("contradicoes") or []:
        if not isinstance(item, dict):
            continue
        fontes: list[dict[str, str]] = []
        arquivos: set[str] = set()
        for fonte in item.get("fontes") or []:
            if not isinstance(fonte, dict):
                continue
            arquivo = _resolver_arquivo(str(fonte.get("documento") or "").strip(), texto_por_arquivo)
            citacao = str(fonte.get("citacao") or "").strip()
            corpo = texto_por_arquivo.get(arquivo) if arquivo else None
            if not corpo or not citacao or _normalizar(citacao) not in corpo or arquivo in arquivos:
                continue
            arquivos.add(arquivo)
            fontes.append({
                "documento": arquivo,
                "citacao": citacao[:400],
                "valor": str(fonte.get("valor") or "").strip()[:200],
            })
        if len(fontes) < 2:
            continue
        saida.append({
            "titulo": str(item.get("titulo") or "Contradição entre documentos").strip()[:180],
            "o_que_diverge": str(item.get("o_que_diverge") or "").strip()[:300],
            "fontes": fontes,
        })
    return saida


def _diagnostico_do_caso(achados: list[dict[str, Any]], contradicoes: list[dict[str, Any]], informado: Any) -> dict[str, str]:
    """Positivo ou negativo a partir do que a conferência deixou passar.

    O motivo do modelo só entra se o sentido que ele deu for o mesmo da conferência.
    Contradição conferida nunca vira diagnóstico positivo.
    """
    contra_entrevista = [a for a in achados if a.get("contradiz")]
    sentido = "NEGATIVO" if contra_entrevista or contradicoes else "POSITIVO"
    if sentido == "NEGATIVO":
        partes = []
        if contradicoes:
            partes.append(
                f"{len(contradicoes)} contradição(ões) entre documentos"
            )
        if contra_entrevista:
            partes.append(
                f"{len(contra_entrevista)} ponto(s) em que o documento contradiz a entrevista"
            )
        motivo = "Diagnóstico negativo: " + "; ".join(partes) + "."
    else:
        motivo = (
            "Diagnóstico positivo: os documentos lidos não contradizem a entrevista "
            "nem divergem entre si."
        )
    if isinstance(informado, dict) and str(informado.get("sentido") or "").strip().upper() == sentido:
        texto = str(informado.get("motivo") or "").strip()
        if texto:
            motivo = texto[:400]
    return {"sentido": sentido, "motivo": motivo}


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
