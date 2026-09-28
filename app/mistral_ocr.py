"""Cliente leve do Document AI/OCR da Mistral, sem depender do SDK."""

from __future__ import annotations

import base64
import logging
import os
import re
import time

import cv2
import httpx
import numpy as np

from . import ambiente
from . import custos_api
from .extractors import Linha

# Pelo mesmo motivo do `transcricao_openrouter`: este módulo lê `MISTRAL_API_KEY`
# do ambiente, e nem todo processo que o importa passou pelo `iniciar.ps1` — um
# worker subido à mão, ou um script. Sem a chave, `configurada()` diz que não há
# OCR e quem chama cai no caminho de reserva; o defeito aparece como documento
# ilegível, não como configuração faltando. Ver o cabeçalho de `app/ambiente.py`.
ambiente.carregar()

log = logging.getLogger("ocr.mistral")


def configurada() -> bool:
    return bool(os.getenv("MISTRAL_API_KEY", "").strip())


#: Teto do payload de imagem (bytes do arquivo, antes do base64). Acima disto,
#: PNG sem perda dá lugar a JPEG de alta qualidade: o ganho de nitidez não paga
#: um upload de dezenas de MB, e a API tem limite de tamanho. Configurável para
#: quem quiser forçar sempre-PNG (teto alto) ou sempre-JPEG (teto zero).
_TETO_PNG_BYTES = int(os.getenv("OCR_PNG_MAX_BYTES", str(8 * 1024 * 1024)))


def _codificar_para_ocr(img_bgr: np.ndarray) -> tuple[str, bytes]:
    """Codifica a imagem para o OCR preferindo SEM PERDA.

    A imagem que chega aqui já foi decodificada de um JPEG do celular ou
    rasterizada de um PDF. Reencodá-la em JPEG acrescenta uma SEGUNDA compressão
    com perda, e é justamente na borda do glifo pequeno — o dígito do CPF, o
    código do CID — que o artefato de JPEG come a informação que o OCR precisa.
    PNG não tem esse custo. Só quando o PNG estoura o teto de tamanho é que vale
    voltar ao JPEG, aí com qualidade alta e sem subamostragem de croma (4:4:4),
    que é o que preserva a borda do texto.
    """
    # Teto: 0 força sempre-JPEG; negativo força sempre-PNG; positivo é o limite.
    if _TETO_PNG_BYTES != 0:
        ok, png = cv2.imencode(".png", img_bgr, [cv2.IMWRITE_PNG_COMPRESSION, 6])
        if ok and (_TETO_PNG_BYTES < 0 or len(png) <= _TETO_PNG_BYTES):
            return "image/png", png.tobytes()

    # Fallback JPEG: qualidade alta e, quando a build do OpenCV expõe o fator de
    # amostragem, 4:4:4 (sem subamostrar croma) para não borrar a borda do texto.
    params = [cv2.IMWRITE_JPEG_QUALITY, int(os.getenv("OCR_JPEG_QUALITY", "95"))]
    fator_444 = getattr(cv2, "IMWRITE_JPEG_SAMPLING_FACTOR", None)
    valor_444 = getattr(cv2, "IMWRITE_JPEG_SAMPLING_FACTOR_444", None)
    if fator_444 is not None and valor_444 is not None:
        params += [fator_444, valor_444]
    ok, jpg = cv2.imencode(".jpg", img_bgr, params)
    if not ok:
        raise RuntimeError("Não foi possível preparar a imagem para o OCR da Mistral")
    return "image/jpeg", jpg.tobytes()


#: Linha de separação de tabela markdown: `| --- | :---: |`. Não é conteúdo.
_SEPARADOR_TABELA = re.compile(r"^\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?$")

#: Respostas da Mistral que valem repetir: limite de uso e falha passageira do
#: provedor. Sem isto, um pico de upload (vários anexos do mesmo caso de uma
#: vez) esbarra no limite de taxa da conta e o primeiro 429 já derruba o
#: arquivo inteiro — o escritório via "erro no documento" onde bastava esperar.
_STATUS_TRANSITORIOS = {429, 500, 502, 503, 504}

#: Quatro tentativas com teto de 8s de espera (1+2+4s de espera cumulativa,
#: ~15s no pior caso com o tempo das próprias chamadas) — o suficiente para um
#: PICO de upload esvaziar sozinho. Deliberadamente CURTO: `pipeline.py` chama
#: o OCR várias vezes por página (até 4 rotações), e um teto alto aqui
#: multiplicava minutos de espera por chamada — com o worker processando um
#: documento por vez, isso empilhava a fila inteira atrás de UM documento
#: preso, e para o advogado parecia "ficou lendo para sempre". Rate limit
#: SUSTENTADO (cota esgotada, não pico) deve cair para a reserva rápido, não
#: bloquear a fila tentando de novo.
_TENTATIVAS_OCR = int(os.getenv("MISTRAL_OCR_TENTATIVAS", "2"))
_PAUSA_MAXIMA_S = float(os.getenv("MISTRAL_OCR_PAUSA_MAXIMA_S", "8"))


def _post_com_repeticao(cliente: httpx.Client, url: str, *, headers: dict, json: dict) -> "httpx.Response":
    """POST ao OCR da Mistral repetindo em 429, falha passageira e queda de rede.

    Usa `Retry-After` quando o provedor manda; sem ele, espera crescente
    (1s, 2s, 4s...) para não martelar a API bem no instante em que ela pediu
    para esperar. Uma queda de conexão (timeout, reset) é tratada como o mesmo
    tipo de falha passageira — repetir é mais barato que desistir na primeira.
    """
    resposta = None
    erro_rede: httpx.HTTPError | None = None
    for tentativa in range(_TENTATIVAS_OCR):
        try:
            resposta = cliente.post(url, headers=headers, json=json)
        except httpx.HTTPError as exc:
            erro_rede = exc
            resposta = None
        else:
            erro_rede = None
            if resposta.status_code not in _STATUS_TRANSITORIOS:
                return resposta
        if tentativa < _TENTATIVAS_OCR - 1:
            cabecalho = resposta.headers.get("Retry-After") if resposta is not None else None
            pausa = min(float(cabecalho) if cabecalho else 2.0 ** tentativa, _PAUSA_MAXIMA_S)
            motivo = resposta.status_code if resposta is not None else type(erro_rede).__name__
            log.warning(
                "Mistral OCR falhou (%s); repetindo em %.1fs (tentativa %d/%d).",
                motivo, pausa, tentativa + 2, _TENTATIVAS_OCR,
            )
            time.sleep(pausa)
    if resposta is None:
        raise erro_rede
    return resposta


def _celulas(texto: str) -> list[str]:
    """Uma linha de markdown vira as CÉLULAS dela, não uma linha só.

    A Mistral devolve documento estruturado como TABELA markdown, e é um acerto:
    ela entendeu o layout. Só que a tabela vinha inteira como uma linha de texto —
    `|  NOME MARIA APARECIDA DA SILVA  |   |` — e aí a extração de campos
    quebrava. `parece_nome` exige `fullmatch` de letras e espaços, e o `|` que
    sobrava no fim do valor bastava para o nome ser recusado.

    O efeito era exatamente o que a suíte media na CNH limpa: nome, filiação 1 e
    filiação 2 não saíam de um documento em que estavam escritos com todas as
    letras, e a categoria vinha `B` no lugar de `AB`. Quanto MAIS limpa a foto,
    pior — foto boa é a que faz a Mistral reconhecer a tabela.

    Cada célula é uma linha própria, e a coluna entra no `x` para a geometria
    continuar valendo: `indices_abaixo` procura o valor "na mesma coluna", e sem
    isso duas colunas diferentes pareceriam a mesma.
    """
    if "|" not in texto:
        return [texto]
    if _SEPARADOR_TABELA.match(texto):
        return []
    return [parte.strip() for parte in texto.strip().strip("|").split("|")]


#: Largura de coluna assumida ao espalhar as células no eixo x. Só precisa ser
#: maior que a largura de uma célula para colunas vizinhas não se sobreporem.
_PASSO_COLUNA = 1_000.0


#: OpenRouter (Gemini) é o motor PRINCIPAL de leitura: mais barato que a
#: Mistral e sem o teto de plano gratuito dela (rate limit agressivo, US$10/mês
#: — ver decisão registrada em 2026-09-23). Reaproveita a chave de visão que já
#: existe para fotos (`app/visao_documento.py`) por padrão, mas aceita uma
#: própria via `OPENROUTER_OCR_FALLBACK_KEY` para isolar custo/quota se quiser.
#: Sem nenhuma das duas, este caminho fica inerte e quem lê é só a Mistral —
#: exatamente o comportamento de antes desta mudança.
_URL_OPENROUTER = "https://openrouter.ai/api/v1/chat/completions"

_INSTRUCAO_OCR_OPENROUTER = (
    "Transcreva TODO o texto visível nesta imagem, na ordem de leitura, sem "
    "resumir, sem pular e sem corrigir nada. Isso inclui cabeçalho, rodapé, "
    "número de página, carimbo, protocolo, código de barras legível, texto "
    "manuscrito, anotação à margem, texto pequeno ou apagado, marca d'água "
    "legível e o conteúdo de cada campo de formulário (inclusive os marcados "
    "com X). Onde houver assinatura, escreva '[assinatura]' e o nome impresso "
    "embaixo dela, se houver; onde houver algo ilegível, escreva '[ilegível]' "
    "em vez de omitir. Números (datas, valores, CID, CPF, CNPJ, matrícula, "
    "processo) exatamente como aparecem, dígito a dígito. Se houver tabela ou "
    "campos alinhados em colunas, represente em markdown de tabela com TODAS "
    "as linhas e colunas.\n\n"
    "Se a imagem for um PRINT DE CONVERSA (WhatsApp ou similar), transcreva "
    "cada mensagem como 'remetente (horário): texto', na ordem em que aparecem. "
    "Para um balão de ÁUDIO, FOTO ou VÍDEO embutido na conversa — que não tem "
    "texto para transcrever —, descreva o que o balão MOSTRA entre colchetes: "
    "'[áudio, duração X]', '[foto: o que a miniatura mostra]', '[vídeo, "
    "duração X]'. Nunca invente o conteúdo de um áudio a partir do ícone — só "
    "o que está visivelmente escrito (duração, remetente, legenda, se houver).\n\n"
    "Responda SOMENTE o texto transcrito, sem comentário, sem explicação, sem "
    "cercas de código."
)

#: Sem `confidence_scores` real vindo de um modelo de chat, um valor baixo
#: (ex.: 0.5) derrubaria `quality.avaliar` — o portão de legibilidade exige
#: `confianca_ocr >= 0.60` — e marcaria como ILEGÍVEL todo documento lido por
#: aqui, mesmo os bem transcritos. 0.85 reflete que o modelo geralmente acerta
#: a transcrição, sem fingir a precisão por página que só a Mistral mede.
_CONFIANCA_OPENROUTER = float(os.getenv("OPENROUTER_OCR_CONFIANCA", "0.85"))


def _chave_openrouter() -> str:
    return (
        os.getenv("OPENROUTER_OCR_FALLBACK_KEY", "").strip()
        or os.getenv("OPENROUTER_VISAO_API_KEY", "").strip()
        or os.getenv("OPENROUTER_API_KEY", "").strip()
    )


def _openrouter_disponivel() -> bool:
    return bool(_chave_openrouter())


def _ocr_via_openrouter(mime: str, dados_img: bytes) -> dict:
    """Lê a imagem pelo modelo de visão da OpenRouter — motor principal.

    Devolve no MESMO formato de resposta da Mistral (`{"pages": [...]}`) para
    que `_linhas_da_resposta` sirva sem ramo especial.
    """
    chave = _chave_openrouter()
    modelo = os.getenv("OPENROUTER_MODELO_OCR", "").strip() or "google/gemini-3.7-flash"
    b64 = base64.b64encode(dados_img).decode("ascii")
    payload = {
        "model": modelo,
        "temperature": 0,
        # Documento de página cheia em fonte pequena passa fácil das 2000
        # tokens padrão do provedor e corta o texto no meio — o mesmo
        # defeito já visto em `analise_documentos._chamar_modelo`.
        "max_tokens": int(os.getenv("OPENROUTER_OCR_MAX_TOKENS", "16000")),
        "messages": [
            {"role": "system", "content": _INSTRUCAO_OCR_OPENROUTER},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ],
            },
        ],
    }
    with httpx.Client(timeout=float(os.getenv("OPENROUTER_OCR_TIMEOUT", "120"))) as cliente:
        resposta = _post_com_repeticao(
            cliente,
            _URL_OPENROUTER,
            headers={"Authorization": f"Bearer {chave}"},
            json=payload,
        )
    resposta.raise_for_status()
    custos_api.registrar("openrouter", modelo, "ocr", resposta)
    escolha = resposta.json()["choices"][0]
    texto = str(escolha["message"]["content"] or "").strip()
    if escolha.get("finish_reason") == "length":
        # Transcrição cortada no teto: aceitar calado é perder o fim da
        # página. A Mistral não tem teto de saída e lê a mesma imagem inteira.
        chave_mistral = os.getenv("MISTRAL_API_KEY", "").strip()
        log.warning("OCR via OpenRouter cortado no teto de tokens (%d caracteres)%s.",
                    len(texto), "; relendo pela Mistral" if chave_mistral else "")
        if chave_mistral:
            try:
                return _ocr_via_mistral(chave_mistral, mime, dados_img)
            except httpx.HTTPError as exc:
                log.warning("Mistral não releu a página cortada (%s); fica a transcrição parcial.", exc)
    return {"pages": [{"markdown": texto,
                        "confidence_scores": {"average_page_confidence_score": _CONFIANCA_OPENROUTER}}]}


def _ocr_via_mistral(chave: str, mime: str, dados_img: bytes) -> dict:
    """Lê a imagem pela Mistral — reserva, usada quando a OpenRouter falha ou não está configurada."""
    payload = {
        "model": os.getenv("MISTRAL_OCR_MODEL", "mistral-ocr-latest"),
        "document": {
            "type": "image_url",
            "image_url": f"data:{mime};base64," + base64.b64encode(dados_img).decode("ascii"),
        },
        "include_blocks": True,
        "confidence_scores_granularity": "page",
        "include_image_base64": False,
    }
    url_base = os.getenv("MISTRAL_BASE_URL", "https://api.mistral.ai").rstrip("/")
    with httpx.Client(timeout=float(os.getenv("MISTRAL_OCR_TIMEOUT", "90"))) as cliente:
        resposta = _post_com_repeticao(
            cliente,
            f"{url_base}/v1/ocr",
            headers={"Authorization": f"Bearer {chave}"},
            json=payload,
        )
    resposta.raise_for_status()
    custos_api.registrar("mistral", payload["model"], "ocr", resposta)
    return resposta.json()


def _linhas_da_resposta(dados: dict) -> list[Linha]:
    linhas: list[Linha] = []
    y = 0.0
    for pagina in dados.get("pages") or []:
        scores = pagina.get("confidence_scores") or {}
        try:
            confianca = min(1.0, max(0.0, float(scores.get("average_page_confidence_score", 1.0))))
        except (TypeError, ValueError):
            confianca = 1.0
        for texto in str(pagina.get("markdown") or "").splitlines():
            texto = texto.strip().lstrip("#").strip()
            if not texto:
                continue
            for coluna, celula in enumerate(_celulas(texto)):
                if not celula:
                    continue
                linhas.append(
                    Linha(
                        celula,
                        confianca,
                        y,
                        coluna * _PASSO_COLUNA,
                        float(len(celula)),
                        1.0,
                    )
                )
            y += 1.0
        y += 10.0
    return linhas


def rodar_ocr_com_tempo(
    img_bgr: np.ndarray, lang: str = "pt"
) -> tuple[list[Linha], dict[str, float]]:
    """Envia uma imagem ao OCR e devolve o formato interno do pipeline.

    OpenRouter (Gemini) é tentado PRIMEIRO — mais barato e sem o teto de plano
    gratuito que a Mistral tem hoje (rate limit agressivo, US$10/mês). A
    Mistral vira RESERVA: melhor estrutura de tabela e confiança por página de
    verdade, mas só entra se o OpenRouter não responder depois do retry, ou se
    não houver credencial de OpenRouter configurada.
    """
    del lang  # O modelo é multilíngue e detecta o idioma automaticamente.
    mime, dados_img = _codificar_para_ocr(img_bgr)
    inicio = time.perf_counter()

    usou_mistral = False
    dados_resposta: dict = {}
    erro_openrouter: Exception | None = None

    if _openrouter_disponivel():
        try:
            dados_resposta = _ocr_via_openrouter(mime, dados_img)
        except httpx.HTTPError as exc:
            erro_openrouter = exc
            log.warning("OpenRouter esgotou tentativas de OCR (%s); tentando a Mistral.", exc)
    else:
        erro_openrouter = RuntimeError("Nenhuma credencial de OpenRouter configurada para OCR.")

    if not dados_resposta:
        chave_mistral = os.getenv("MISTRAL_API_KEY", "").strip()
        if not chave_mistral:
            raise erro_openrouter
        usou_mistral = True
        try:
            dados_resposta = _ocr_via_mistral(chave_mistral, mime, dados_img)
        except httpx.HTTPError:
            raise  # nem OpenRouter nem Mistral leram: o erro da Mistral é o mais recente

    inferencia = time.perf_counter() - inicio
    linhas = _linhas_da_resposta(dados_resposta)
    total = time.perf_counter() - inicio
    log.info("OCR concluído em %.2fs (%d linhas)%s.", total, len(linhas),
              " via Mistral (reserva)" if usou_mistral else " via OpenRouter")
    return linhas, {"fila_s": 0.0, "inferencia_s": inferencia,
                    "pos_processamento_s": total - inferencia, "total_s": total}


def markdown_do_pdf(conteudo: bytes, tempo_limite: float | None = None) -> str:
    """O PDF INTEIRO pela API de OCR, em markdown, uma página após a outra.

    POR QUE NÃO PASSA PELO `pdf.pdf_para_imagem`

    O caminho de documento do checklist rasteriza o PDF numa imagem só e manda
    como `image_url`. Isso serve a um RG ou a um contracheque — uma página, dois
    campos. Para um roteiro de entrevista não serve, por dois motivos:

    - a imagem única de `pdf_para_imagem` empilha todas as páginas e reduz a
      escala para caber no teto de pixels — num roteiro de dezenas de páginas
      isso já compromete a nitidez antes mesmo de chegar ao OCR;
    - a imagem única perde a divisão em páginas, e o `_linhas_da_resposta`
      ainda achata os títulos (`lstrip("#")`) para caber no formato de linha do
      pipeline.

    Aqui o PDF vai como `document_url`, que é o que a API espera para documento:
    ela mesma pagina, e devolve markdown por página. O markdown é o ponto —
    título continua título e lista continua lista, e é dessa estrutura que o
    modelo tira onde um bloco do roteiro termina e o próximo começa.
    """
    chave = os.getenv("MISTRAL_API_KEY", "").strip()
    if not chave:
        raise RuntimeError("MISTRAL_API_KEY não configurada")

    dados = base64.b64encode(conteudo).decode("ascii")
    url_base = os.getenv("MISTRAL_BASE_URL", "https://api.mistral.ai").rstrip("/")
    espera = tempo_limite or float(os.getenv("MISTRAL_OCR_TIMEOUT_DOC", "300"))

    inicio = time.perf_counter()
    with httpx.Client(timeout=espera) as cliente:
        resposta = _post_com_repeticao(
            cliente,
            f"{url_base}/v1/ocr",
            headers={"Authorization": f"Bearer {chave}"},
            json={
                "model": os.getenv("MISTRAL_OCR_MODEL", "mistral-ocr-latest"),
                "document": {
                    "type": "document_url",
                    "document_url": "data:application/pdf;base64," + dados,
                },
                "include_image_base64": False,
            },
        )
    resposta.raise_for_status()

    paginas = resposta.json().get("pages") or []
    textos = [str(p.get("markdown") or "").strip() for p in paginas]
    log.info(
        "Mistral OCR leu %d página(s) em %.1fs.", len(paginas), time.perf_counter() - inicio
    )
    # Duas quebras entre páginas: o modelo que monta o roteiro lê isso como
    # separação de seção, e não como uma frase que continua na linha de baixo.
    return "\n\n".join(t for t in textos if t)
