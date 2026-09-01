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

from . import armazenamento

log = logging.getLogger("analise_documentos")


class ErroAnaliseDocumentos(RuntimeError):
    """Falha que o usuário precisa ver, com o que dá para fazer a respeito."""


#: Teto por documento. Uma página de OCR raramente passa disso, e o corte evita
#: que um PDF de 40 páginas consuma a janela inteira e empurre os outros anexos
#: para fora — perder documento em silêncio é pior que analisar menos texto.
MAX_CARACTERES_POR_DOCUMENTO = 6000

#: Teto do conjunto. Acima disto o modelo passa a ignorar o meio do prompt, e o
#: que ele ignora ninguém fica sabendo.
MAX_CARACTERES_TOTAL = 40000

TEMPO_MODELO_S = 60.0

INSTRUCAO = """Você lê documentos de um processo trabalhista e aponta o que eles
dizem e o caso ainda NÃO registrou.

Devolva APENAS JSON: {"achados": [...]}

Cada achado:
{
  "informacao": "o que o documento diz, em uma frase",
  "documento": "nome exato do arquivo, como veio na lista",
  "citacao": "trecho LITERAL e contínuo do documento, copiado caractere a caractere",
  "relevancia": "por que isto importa para o caso, em uma frase",
  "contradiz": true se o documento contradiz o que a entrevista registrou, senão false
}

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

Máximo 12 achados, os mais relevantes primeiro."""


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


def _montar_mensagem(documentos: list[dict[str, str]], conhecidos: list[str]) -> str:
    partes = ["O QUE A ENTREVISTA JÁ REGISTROU:"]
    partes.append("\n".join(f"- {c}" for c in conhecidos) if conhecidos else "- (nada ainda)")
    partes.append("\nDOCUMENTOS DO CASO:")
    total = 0
    for doc in documentos:
        bloco = f"\n=== {doc['arquivo']} ===\n{doc['texto']}"
        if total + len(bloco) > MAX_CARACTERES_TOTAL:
            partes.append(
                f"\n[{len(documentos)} documentos no caso; o restante não coube nesta análise]"
            )
            break
        partes.append(bloco)
        total += len(bloco)
    return "\n".join(partes)


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
                "max_tokens": 2000,
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
    """Lê os anexos do caso e devolve o que eles dizem e a entrevista não pegou."""
    documentos = _documentos_do_caso(caso_id)
    if not documentos:
        return {
            "achados": [],
            "documentos_lidos": 0,
            "aviso": (
                "Nenhum anexo deste caso tem texto lido ainda. Envie os documentos "
                "e espere a leitura terminar."
            ),
        }

    conhecidos = _fatos_conhecidos(caso_id)
    bruto = _chamar_modelo(_montar_mensagem(documentos, conhecidos))

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

        corpo = texto_por_arquivo.get(arquivo)
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
                "contradiz": bool(item.get("contradiz")),
            }
        )

    if recusados:
        log.info("análise do caso %s: %d achado(s) recusados na conferência", caso_id, recusados)

    return {
        "achados": achados[:12],
        "documentos_lidos": len(documentos),
        # Contado e mostrado de propósito: silenciar a recusa esconderia um
        # modelo alucinando com frequência, que é o que precisa aparecer.
        "recusados": recusados,
    }
