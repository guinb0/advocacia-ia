"""Monta um roteiro de entrevista a partir do documento que o escritório usa hoje.

O roteiro do `app/roteiros.py` foi transcrito à mão de um `.docx` da Lara & Melo.
Deu certo uma vez; não escala. Cada nova categoria de causa tem o seu documento, e
transcrever 86 perguntas em dataclasses leva um dia e erra o que o advogado
escreveu.

Aqui o documento entra como arquivo e sai como `roteiros.Roteiro`. O texto é lido
pelo caminho mais barato que funcione — `.docx` e PDF com texto nativo saem em
milissegundos; PDF digitalizado e foto passam pelo OCR — e o modelo transforma o
texto corrido em blocos e perguntas.

A geração é em **duas passadas**, e isso não é capricho:

    1ª  o esboço — nome, saudação, encerramento e a lista de blocos
    2ª  as perguntas, um bloco de cada vez

Um roteiro completo em JSON passa de 15 mil tokens de saída, e `max_tokens` do
DeepSeek é 8192: pedir tudo de uma vez devolve JSON cortado no meio de uma
pergunta. Bloco a bloco, cada resposta cabe com folga — e a barra de progresso
passa a medir alguma coisa real, porque há uma etapa por bloco.

O que sai daqui é uma PROPOSTA. Ninguém entrevista com roteiro que a máquina
escreveu sem alguém ler: por isso existe o editor na tela, e por isso o texto
lido do documento volta junto, para conferência lado a lado.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Callable

import httpx

from . import entrevista as entrevista_lib
from . import roteiros

log = logging.getLogger(__name__)

__all__ = ["ErroGeracao", "EXTENSOES_ROTEIRO", "texto_do_documento", "gerar"]

#: O que se aceita como fonte de roteiro. Os quatro primeiros têm texto de
#: verdade; os outros passam pelo OCR.
EXTENSOES_ROTEIRO = {
    ".txt", ".md", ".docx", ".pdf",
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff",
}

#: Acima disto o modelo perde o começo do documento na janela de contexto. Um
#: roteiro de entrevista real tem 10 a 20 páginas; 45 mil caracteres cobrem isso
#: com sobra, e o excedente costuma ser anexo que não vira pergunta.
LIMITE_TEXTO = 45_000

TEMPO_MODELO_S = 120.0

#: Teto de blocos e de perguntas por bloco. Sem eles, um documento estranho
#: (uma petição, um contrato) vira uma entrevista de 400 perguntas.
MAX_BLOCOS = 20
MAX_PERGUNTAS_POR_BLOCO = 30


class ErroGeracao(RuntimeError):
    """Falha ao ler o documento ou ao montar o roteiro, com o motivo em português."""


# --------------------------------------------------------------- leitura


def texto_do_documento(nome: str, conteudo: bytes) -> tuple[str, str]:
    """O texto do arquivo e como ele foi lido ("texto nativo" ou "OCR").

    A ordem importa: tenta-se sempre o texto nativo primeiro. Rodar OCR num
    `.docx` seria trocar uma leitura exata por uma aproximada, e num PDF de texto
    o OCR ainda inventaria erro de acento onde não havia nenhum.
    """
    extensao = Path(nome).suffix.lower()
    if extensao and extensao not in EXTENSOES_ROTEIRO:
        raise ErroGeracao(
            f"Extensão '{extensao}' não suportada. "
            f"Use: {', '.join(sorted(EXTENSOES_ROTEIRO))}."
        )

    if extensao in entrevista_lib.EXTENSOES_ENTREVISTA:
        try:
            return entrevista_lib.extrair_texto(nome, conteudo), "texto nativo"
        except entrevista_lib.ErroDeLeitura:
            # PDF digitalizado cai aqui: tem páginas, não tem texto. É exatamente
            # o caso do OCR, então segue adiante em vez de devolver o erro.
            if extensao != ".pdf":
                raise ErroGeracao(
                    "Não foi possível ler texto deste arquivo."
                ) from None

    return _texto_por_ocr(conteudo), "OCR"


def _texto_por_ocr(conteudo: bytes) -> str:
    """Rasteriza (se for PDF) e passa o PaddleOCR, devolvendo só as linhas.

    Não se usa `pipeline.processar` aqui de propósito: ele classifica o documento
    e extrai campos de RG, CPF e contracheque. Um roteiro de entrevista não é
    nenhum desses tipos, e todo esse trabalho seria descartado — o que se quer é
    o texto.
    """
    from . import pipeline, quality

    try:
        imagem = pipeline.decodificar(conteudo)
    except ValueError as erro:
        raise ErroGeracao(str(erro)) from erro

    try:
        preparada = quality.preparar_para_ocr(imagem)
        linhas, _rotacao, _tentativas, _passadas = pipeline.ocr_com_rotacao_medido(
            preparada, "pt"
        )
    except Exception as erro:
        log.exception("OCR falhou ao ler documento de roteiro")
        raise ErroGeracao(f"O OCR não conseguiu ler este arquivo: {erro}") from erro

    texto = "\n".join(linha.texto.strip() for linha in linhas if linha.texto.strip())
    if not texto.strip():
        raise ErroGeracao(
            "O OCR não encontrou texto neste arquivo. Confira se a digitalização "
            "está legível e na orientação correta."
        )
    return texto[: entrevista_lib.LIMITE_CARACTERES]


# --------------------------------------------------------------- prompts


_TIPOS = ", ".join(f'"{t}"' for t in roteiros.TIPOS_RESPOSTA)

_REGRA_TIPOS = f"""
TIPOS DE RESPOSTA disponiveis: {_TIPOS}.
  dado       texto curto digitado (nome, matricula, endereco, telefone)
  data       uma data
  sim_nao    pergunta fechada de sim ou nao
  escolha    poucas opcoes, viram botoes (ate 8) - preencha "opcoes"
  lista      muitas opcoes, viram seletor (UFs, cargos) - preencha "opcoes"
  documentos qual papelada o cliente tem
  relato     a pessoa CONTA algo, em texto livre

REGRA DO GRAVADOR ("transcrever"): true apenas quando o cliente CONTA
(tipo "relato"); false quando ele INFORMA um dado. Transcrever um CPF e pior que
digita-lo - o audio erra digito e ninguem confere numero lido de ouvido.
"""

_INSTRUCAO_ESBOCO = f"""Voce recebe o texto de um roteiro de entrevista de um escritorio de advocacia
brasileiro e devolve a ESTRUTURA dele em JSON. Nao invente conteudo: use as
palavras do documento, em portugues, com a acentuacao correta.

Responda SOMENTE JSON no formato:
{{"nome":"...","descricao":"...",
 "saudacao":["paragrafo lido em voz alta antes da primeira pergunta"],
 "encerramento":["paragrafo lido ao final"],
 "blocos":[{{"id":"identificacao","titulo":"Identificacao","objetivo":"...",
             "abertura":"frase lida em voz alta ao entrar no bloco",
             "instrucao":"orientacao interna, NUNCA lida ao cliente",
             "modulo":null}}]}}

"id" em minusculas, sem acento e sem espaco (use _).
"abertura" e "saudacao" sao falas LIDAS ao cliente; "instrucao" e "objetivo" sao
orientacao interna. Se o documento nao trouxer o texto, devolva "".
"modulo": null quando o bloco aparece sempre. Quando o bloco so existe se uma
pergunta de rastreio for positiva, ponha um nome curto do assunto (ex.: "assalto").
No maximo {MAX_BLOCOS} blocos."""

_INSTRUCAO_PERGUNTAS = f"""Voce recebe o texto de um roteiro de entrevista e o nome de UM bloco dele.
Devolva as perguntas DESSE BLOCO em JSON, na ordem do documento, com as palavras
do documento, em portugues e com a acentuacao correta. Nao crie perguntas que o
texto nao tem.

Responda SOMENTE JSON no formato:
{{"perguntas":[{{"id":"nome_completo","texto":"Qual o seu nome completo?",
  "tipo":"dado","transcrever":false,"opcoes":[],"dica":"","obrigatoria":true,
  "validacao":"","fala":{{}},"depende_de":"","depende_valor":"",
  "impedimento":""}}]}}
{_REGRA_TIPOS}
"id": minusculas, sem acento, sem espaco, unico e descritivo.
"depende_de"/"depende_valor": quando o enunciado do documento pressupoe a
resposta de outra pergunta ("Se ja entrou com acao: qual o numero do processo?"),
ponha em "depende_de" o id da pergunta anterior e em "depende_valor" a resposta
que abre esta ("sim", "nao"). Nos demais casos deixe os dois como "".
"dica": orientacao interna a atendente, nunca lida ao cliente. "" se nao houver.
"obrigatoria": true quando o documento marcar a pergunta como obrigatoria.
"validacao": "cpf" quando a pergunta pedir um CPF; "" nos demais casos.
"fala": texto que a atendente LE EM VOZ ALTA dependendo da resposta - chave "sim"
ou "nao" nas perguntas de sim/nao, "*" para qualquer resposta. {{}} se nao houver.
"impedimento": a resposta que, segundo o documento, IMPEDE prosseguir com o caso
(ex.: "sim"). "" quando o documento nao disser nada disso.
No maximo {MAX_PERGUNTAS_POR_BLOCO} perguntas."""


def _chamar_modelo(instrucao: str, mensagem: str, max_tokens: int) -> dict[str, Any]:
    chave = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not chave:
        raise ErroGeracao(
            "Geração de roteiro desligada: falta DEEPSEEK_API_KEY no .env. "
            "O roteiro pode ser montado à mão pelo editor."
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
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": instrucao},
                    {"role": "user", "content": mensagem},
                ],
            },
            timeout=TEMPO_MODELO_S,
        )
        resposta.raise_for_status()
    except httpx.HTTPError as erro:
        log.warning("Geração de roteiro falhou: %s", str(erro)[:200])
        raise ErroGeracao("O modelo não respondeu. Tente novamente em instantes.") from erro

    try:
        return json.loads(resposta.json()["choices"][0]["message"]["content"])
    except Exception as erro:
        raise ErroGeracao("Resposta ilegível do modelo.") from erro


# --------------------------------------------------------------- geração


def gerar(
    texto: str,
    *,
    origem: str = "",
    progresso: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
    """O roteiro proposto, como dicionário pronto para `roteiros.de_dict`.

    `progresso` é chamado a cada etapa com (percentual, descrição). É o que a
    barra na tela mostra — sem isso o usuário olha para um spinner por um minuto
    sem saber se são dez blocos ou dois.
    """

    def avisar(pct: int, etapa: str) -> None:
        if progresso is not None:
            progresso(pct, etapa)

    corpo = texto.strip()[:LIMITE_TEXTO]
    if len(corpo) < 200:
        raise ErroGeracao(
            "O documento tem texto de menos para virar um roteiro. Confira se o "
            "arquivo enviado é mesmo o roteiro de entrevista."
        )

    avisar(20, "Lendo a estrutura do documento")
    esboco = _chamar_modelo(_INSTRUCAO_ESBOCO, f"Documento:\n\n{corpo}", max_tokens=4000)

    blocos_brutos = esboco.get("blocos")
    if not isinstance(blocos_brutos, list) or not blocos_brutos:
        raise ErroGeracao(
            "O modelo não encontrou blocos de perguntas neste documento. "
            "Confira se o arquivo é o roteiro de entrevista."
        )
    blocos_brutos = [b for b in blocos_brutos if isinstance(b, dict)][:MAX_BLOCOS]

    total = max(len(blocos_brutos), 1)
    blocos: list[dict[str, Any]] = []
    ids_usados: set[str] = set()

    for indice, bruto in enumerate(blocos_brutos):
        titulo = str(bruto.get("titulo") or f"Bloco {indice + 1}").strip()
        avisar(
            25 + int(70 * indice / total),
            f"Perguntas de '{titulo}' ({indice + 1} de {total})",
        )
        perguntas = _perguntas_do_bloco(corpo, titulo, bruto, ids_usados)
        # Bloco sem pergunta nenhuma é ruído do modelo, não seção do roteiro: na
        # tela ele apareceria como um título solto que não pede nada.
        if not perguntas:
            continue
        blocos.append(
            {
                "id": roteiros.identificador(bruto.get("id") or titulo, ids_usados, "bloco"),
                "titulo": titulo[:200],
                "objetivo": str(bruto.get("objetivo") or "").strip()[:1000],
                "abertura": str(bruto.get("abertura") or "").strip()[:2000],
                "instrucao": str(bruto.get("instrucao") or "").strip()[:2000],
                "modulo": _modulo(bruto.get("modulo")),
                "delegado_a": "",
                "perguntas": perguntas,
            }
        )

    if not blocos:
        raise ErroGeracao("Nenhuma pergunta foi reconhecida no documento.")

    avisar(97, "Conferindo o roteiro")
    nome = str(esboco.get("nome") or Path(origem).stem or "Roteiro importado").strip()
    return {
        "codigo": roteiros.identificador(nome, set(), "roteiro"),
        "nome": nome[:200],
        "descricao": str(esboco.get("descricao") or "").strip()[:1000],
        "saudacao": _paragrafos(esboco.get("saudacao")),
        "encerramento": _paragrafos(esboco.get("encerramento")),
        # O escritório escreveu estas duas para o roteiro de empregado público, e
        # elas não têm nada de específico daquele caso: são o que se diz quando o
        # cliente sai do assunto. Nascer com elas poupa reescrever o óbvio.
        "retomadas": list(roteiros.RETOMADAS),
        "fechos_por_tipo": dict(roteiros.FECHOS_POR_TIPO),
        "blocos": blocos,
    }


def _perguntas_do_bloco(
    corpo: str, titulo: str, bruto: dict[str, Any], ids_usados: set[str]
) -> list[dict[str, Any]]:
    pedido = (
        f"Bloco: {titulo}\n"
        f"Objetivo: {bruto.get('objetivo') or '(nao informado)'}\n\n"
        f"Documento:\n\n{corpo}"
    )
    try:
        resposta = _chamar_modelo(_INSTRUCAO_PERGUNTAS, pedido, max_tokens=6000)
    except ErroGeracao:
        # Um bloco que falhou não derruba o roteiro inteiro: o advogado
        # acrescenta as perguntas dele no editor, que é mais rápido que refazer a
        # importação e torcer para o modelo não falhar de novo.
        log.warning("Bloco '%s' ficou sem perguntas: o modelo falhou.", titulo)
        return []

    brutas = resposta.get("perguntas")
    if not isinstance(brutas, list):
        return []

    perguntas: list[dict[str, Any]] = []
    # O modelo escreve `depende_de` com o id que ELE inventou, e `identificador`
    # pode ter renomeado esse id para desfazer uma colisão. Sem este mapa, a
    # pergunta condicional apontaria para um id inexistente e ficaria fechada
    # para sempre — some da entrevista sem ninguém notar.
    renomeadas: dict[str, str] = {}
    for bruta in brutas[:MAX_PERGUNTAS_POR_BLOCO]:
        if not isinstance(bruta, dict):
            continue
        texto = str(bruta.get("texto") or "").strip()
        if not texto:
            continue
        tipo = str(bruta.get("tipo") or "").strip()
        if tipo not in roteiros.TIPOS_RESPOSTA:
            tipo = "relato"
        id_bruto = str(bruta.get("id") or "").strip()
        id_final = roteiros.identificador(id_bruto or texto, ids_usados, "p")
        if id_bruto:
            # `setdefault`, não atribuição: quando o modelo repete um id, quem
            # fica com o nome original é a PRIMEIRA pergunta. Sobrescrever aqui
            # faria "depende_de: houve" — escrito para apontar à primeira —
            # ser reescrito para a segunda, que é ela mesma.
            renomeadas.setdefault(id_bruto, id_final)
        perguntas.append(
            {
                "id": id_final,
                "texto": texto[:500],
                "tipo": tipo,
                # O modelo erra este campo com frequência (marca "transcrever" num
                # CPF). A regra é do roteiro, não do modelo: quem CONTA é relato.
                "transcrever": tipo == "relato",
                "opcoes": _opcoes(bruta.get("opcoes"), tipo),
                "dica": str(bruta.get("dica") or "").strip()[:500],
                "obrigatoria": bool(bruta.get("obrigatoria")),
                "validacao": "cpf" if str(bruta.get("validacao") or "") == "cpf" else "",
                "busca": "",
                "preenche": "",
                "fala": _fala(bruta.get("fala")),
                "depende_de": str(bruta.get("depende_de") or "").strip()[:60],
                "depende_valor": str(bruta.get("depende_valor") or "").strip()[:60],
                "impedimento": str(bruta.get("impedimento") or "").strip()[:60],
            }
        )

    for pergunta in perguntas:
        pai = pergunta["depende_de"]
        if pai:
            # Fora do mapa: o modelo apontou para uma pergunta de outro bloco, ou
            # inventou. `roteiros.de_dict` solta o que sobrar de órfão.
            pergunta["depende_de"] = renomeadas.get(pai, pai)
    return perguntas


def _modulo(valor: Any) -> str | None:
    texto = str(valor or "").strip()
    if not texto or texto.lower() in {"null", "none", "nenhum"}:
        return None
    return roteiros.identificador(texto, set(), "modulo")


def _opcoes(valor: Any, tipo: str) -> list[str]:
    if tipo not in {"escolha", "lista"} or not isinstance(valor, list):
        return []
    limpas = [str(item).strip()[:120] for item in valor if str(item).strip()]
    return limpas[:60]


def _fala(valor: Any) -> dict[str, str]:
    if not isinstance(valor, dict):
        return {}
    return {
        str(chave).strip().lower()[:20]: str(texto).strip()[:1000]
        for chave, texto in valor.items()
        if str(texto).strip()
    }


def _paragrafos(valor: Any) -> list[str]:
    if isinstance(valor, str):
        valor = [valor]
    if not isinstance(valor, list):
        return []
    return [str(item).strip()[:2000] for item in valor if str(item).strip()][:20]
