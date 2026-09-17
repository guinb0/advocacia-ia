"""Olha a FOTO quando o OCR não achou texto — o arquivo que não é documento.

O BURACO QUE ISTO FECHA

`valor_documento.ler` interpreta o TEXTO que o OCR extraiu, e desiste abaixo de
`MINIMO_CARACTERES` ("foto ilegível, página em branco ou verso do documento").
`tasks/ocr.py` só o chama quando `validacao.texto_utilizavel` é verdadeiro.

Entre as duas condições sobra um caso inteiro, e ele é comum num escritório
trabalhista: a foto que NÃO É documento. Foto do veículo amassado, da máquina que
prensou a mão, do corredor onde a pessoa caiu, da lesão. O OCR roda, não acha
texto, e o arquivo cai na triagem sem que nada seja dito sobre ele — o advogado
abre uma a uma para descobrir o que o cliente mandou.

Aqui a imagem é olhada. O retorno tem a MESMA FORMA de `valor_documento.ler`, e
isso é deliberado: assim ele atravessa `indexacao_documento.aplicar_interpretacao`
sem um ramo especial, e herda a disciplina que já existe lá — opinião de modelo
não rebaixa classificação determinística, campo interpretado entra com confiança
zero e com a nota de conferir.

POR QUE PELA OPENROUTER, E COM O MODELO QUE JÁ ESTÁ PAGO

O resto do sistema fala com a DeepSeek para texto, e a DeepSeek não tem visão.
A OpenRouter já está configurada (transcrição do áudio e embeddings), a chave já
existe e tem crédito, e o `google/gemini-3.7-flash` — o MESMO que transcreve as
entrevistas — aceita `["text","image","video","file","audio"]`. Abrir uma segunda
conta para economizar centavos por foto custaria mais em credencial no CI, num
segundo modo de falha e numa segunda fatura do que economizaria em tokens.

O QUE ELE NÃO FAZ, E POR QUÊ

Não diagnostica lesão, não atribui culpa, não estabelece nexo causal e não estima
valor. Uma foto de braço machucado não é laudo; dizer "fratura" a partir dela, na
tela que a atendente lê ao vivo, é o começo de uma promessa que o escritório não
fez — e a mesma regra que `valor_documento` já impõe ao texto. A descrição fica
no que é visualmente observável, e vai rotulada como leitura automática.

PRIVACIDADE

A imagem sai da máquina. Isso já vale para o texto do OCR e para o áudio da
entrevista, mas aqui pesa mais: foto de lesão é dado de saúde. Nada é gravado
fora daqui — sem embedding, sem banco vetorial —, pela mesma razão registrada no
cabeçalho de `valor_documento`.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from typing import Any

import httpx

log = logging.getLogger("visao-documento")

TEMPO_MODELO_S = 40.0

#: Extensões que valem uma olhada.
#:
#: O `.pdf` esteve FORA daqui, com a justificativa de que "PDF sem texto é
#: digitalização, e para ela o caminho é o OCR de página inteira". Estava errado
#: no caso mais comum de todos: o cliente fotografa a lesão no celular e manda
#: como PDF. Foi o que aconteceu com `FOTOS LESAO POS-OPERATORIO.pdf` — cinco
#: fotos de pós-operatório num PDF, que o sistema leu como documento sem campos
#: e classificou como "Indefinido", sem uma palavra sobre o que havia nas fotos.
#:
#: `pipeline.decodificar` já rasteriza PDF (`pdf.pdf_para_imagem`), então a
#: capacidade sempre existiu. As páginas viram UMA imagem empilhada e o modelo
#: descreve o conjunto — que é o que se quer de um álbum de fotos de lesão.
EXTENSOES_IMAGEM = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".pdf"}

#: Uma referência de imagem em markdown, que é o que o OCR devolve quando a
#: página é só foto: `![img-0.jpeg](img-0.jpeg)`.
_RE_IMAGEM_MD = re.compile(r"!\[[^\]]*\]\([^)]*\)")


def so_referencias_de_imagem(texto: str) -> bool:
    """O "texto" do OCR é só a lista de imagens da página — ou seja, não há texto.

    O PORQUÊ DISTO EXISTIR, E POR QUE CONTAR CARACTERE NÃO BASTA

    `pipeline` decide `texto_utilizavel` por quantidade: 80 caracteres. Um PDF
    com cinco fotos devolve `![img-0.jpeg](img-0.jpeg)` cinco vezes — 125
    caracteres, acima do corte. O arquivo era então tratado como documento com
    texto, ia para o classificador semântico, que lia nomes de arquivo e
    respondia "Indefinido". A foto nunca era olhada, e a tela dizia
    "Dados lidos (0)" sem explicar por quê.

    Aqui a pergunta é outra: tirando as referências de imagem, sobrou alguma
    coisa? Não sobrando, o arquivo é um álbum de fotos, e quem tem de olhar é o
    modelo de visão — não o de texto.
    """
    if not texto:
        return True
    return not _RE_IMAGEM_MD.sub(" ", texto).strip()

#: Teto do arquivo enviado. Acima disto a imagem é reduzida antes (ver
#: `_codificar`), porque base64 de dezenas de MB estoura o corpo do POST.
_TETO_BYTES = int(os.getenv("VISAO_MAX_BYTES", str(4 * 1024 * 1024)))

#: O modelo de visão. O padrão é o mesmo que já transcreve o áudio — trocável
#: sem mexer no código, como o de áudio.
MODELO = os.getenv("OPENROUTER_MODELO_VISAO", "").strip() or "google/gemini-3.7-flash"

URL = "https://openrouter.ai/api/v1/chat/completions"


class ErroVisao(Exception):
    """Falha que a tela precisa ver, sem travar o envio do arquivo."""


def _chave() -> str:
    """A credencial da visão — própria, com a do resto como reserva.

    Chave separada porque a conta é separada: a visão roda por foto que ninguém
    pediu (o cliente manda o que quiser no portal), e misturá-la com a conta que
    sustenta a transcrição ao vivo significaria uma entrevista emudecer porque
    alguém subiu vinte fotos de um acidente. Contas distintas isolam o estrago.

    Sem a específica, cai na geral: assim o caminho continua funcionando em
    ambiente de desenvolvimento, onde costuma haver uma chave só.
    """
    return (
        os.getenv("OPENROUTER_VISAO_API_KEY", "").strip()
        or os.getenv("OPENROUTER_API_KEY", "").strip()
    )


def configurada() -> bool:
    """Há credencial para olhar a imagem. Sem isto o caminho fica inerte."""
    return bool(_chave())


INSTRUCAO = """Você assessora um advogado trabalhista brasileiro. Recebe UMA FOTO que um
cliente enviou e que o OCR não conseguiu ler como documento — provavelmente não é
um documento, e sim uma cena, um objeto ou uma lesão.

Diga o que a foto MOSTRA, e só isso.

REGRAS ABSOLUTAS
- Descreva apenas o que é visualmente observável. Nada de diagnóstico médico,
  nada de culpa, nada de nexo causal, nada de estimativa de valor ou de êxito.
  "Antebraço com hematoma extenso" é observação; "fratura de rádio" é laudo, e
  laudo não sai de foto.
- Não invente contexto que a imagem não mostra. Se não dá para saber onde é,
  quando foi ou de quem é, diga que não dá.
- Se a foto for, afinal, um documento (papel, tela, formulário), diga isso em
  `documento` e descreva o que se lê nele.

Responda SOMENTE JSON:
{"documento":"o que a foto é, em poucas palavras",
 "achados":[{"campo":"o que se vê","valor":"descrição objetiva",
             "importancia":"por que pode importar ao caso"}],
 "atencao":["o que a foto NÃO permite afirmar, ou problema de qualidade"],
 "sugere_pedir":["documento que confirmaria o que a foto sugere"]}

`documento`: use termos como "Foto de veículo danificado", "Foto de lesão
corporal", "Foto de local de trabalho", "Foto de equipamento", "Foto sem
conteúdo identificável".
`achados`: no máximo 6, cada um sobre algo efetivamente visível.
`atencao`: inclua SEMPRE o que a foto não prova sozinha.
`sugere_pedir`: o documento que transformaria isto em prova (CAT, laudo, boletim
de ocorrência, atestado). No máximo 4."""


def _codificar(conteudo: bytes, extensao: str) -> tuple[str, bytes]:
    """O par (mime, bytes) para o payload, reduzindo a imagem se ela for grande.

    Reduz com o mesmo utilitário do OCR (`pipeline.decodificar` +
    `mistral_ocr._codificar_para_ocr`), que já resolve orientação, formato e
    teto de tamanho. Se a decodificação falhar — formato exótico —, manda os
    bytes originais: o modelo pode aceitar o que o OpenCV não abriu.
    """
    mime_por_extensao = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp", ".bmp": "image/bmp",
        ".tif": "image/tiff", ".tiff": "image/tiff",
    }
    # PDF SEMPRE é rasterizado, tenha o tamanho que tiver.
    #
    # O modelo espera uma IMAGEM. Mandar os bytes de um PDF rotulados como
    # `data:image/jpeg` — que é o que o mapa acima faria, por não ter entrada
    # para `.pdf` — entrega um arquivo que não é o que o cabeçalho promete. O
    # `pipeline.decodificar` já empilha as páginas numa imagem só (ver
    # `pdf.pdf_para_imagem`), que é exatamente o formato certo para um álbum de
    # fotos: o modelo vê as cinco de uma vez e descreve o conjunto.
    ehpdf = extensao == ".pdf" or conteudo.lstrip().startswith(b"%PDF-")
    if not ehpdf and len(conteudo) <= _TETO_BYTES:
        return mime_por_extensao.get(extensao, "image/jpeg"), conteudo

    try:
        from . import mistral_ocr, pipeline

        imagem = pipeline.decodificar(conteudo)
        return mistral_ocr._codificar_para_ocr(imagem)
    except Exception as exc:  # noqa: BLE001 - imagem exótica segue como veio
        log.info("redução da imagem falhou (%s); enviando original", str(exc)[:120])
        if ehpdf:
            # Sem rasterizar, um PDF não tem como virar entrada de visão: melhor
            # dizer que não deu do que mandar bytes que o modelo vai recusar.
            raise ErroVisao(
                "Não foi possível converter o PDF em imagem para leitura visual. "
                "O arquivo segue guardado no caso."
            ) from exc
        return mime_por_extensao.get(extensao, "image/jpeg"), conteudo


def _texto(valor: Any, limite: int = 200) -> str:
    return re.sub(r"\s+", " ", str(valor or "")).strip()[:limite]


def _lista(bruto: Any, limite: int = 4) -> list[str]:
    saida = []
    for item in bruto if isinstance(bruto, list) else []:
        t = _texto(item)
        if t:
            saida.append(t)
    return saida[:limite]


def ler_imagem(
    conteudo: bytes,
    extensao: str,
    categoria: str = "",
    pendencias: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Descreve a foto, no MESMO formato de `valor_documento.ler`.

    `codigo_documento` sai sempre `nao_estruturado`: uma cena não é um dos tipos
    do whitelist, e forçá-la a virar um deles faria o roteamento marcar item de
    checklist com uma fotografia. O que ela responde ao caso vai em `achados` e
    `sugere_pedir`, que é leitura, não decisão.
    """
    chave = _chave()
    if not chave:
        raise ErroVisao(
            "A leitura de imagem está desligada: falta OPENROUTER_VISAO_API_KEY "
            "(ou OPENROUTER_API_KEY). O arquivo segue guardado no caso."
        )

    mime, dados = _codificar(conteudo, extensao.lower())
    b64 = base64.b64encode(dados).decode("ascii")

    abertas = [
        f"- {p.get('codigo')}: {p.get('nome')}"
        for p in (pendencias or [])
        if p.get("codigo")
    ][:20]
    contexto = []
    if categoria:
        contexto.append(f"TIPO DE AÇÃO: {categoria}")
    if abertas:
        contexto.append("DOCUMENTOS QUE O CASO AINDA ESPERA:\n" + "\n".join(abertas))

    try:
        resposta = httpx.post(
            URL,
            headers={"Authorization": f"Bearer {chave}"},
            json={
                "model": MODELO,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": INSTRUCAO},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "\n\n".join(contexto) or "Sem contexto do caso."},
                            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                        ],
                    },
                ],
            },
            timeout=TEMPO_MODELO_S,
        )
        if resposta.status_code in (401, 402):
            # Separado do erro genérico: chave recusada e crédito no fim mandam
            # procurar o problema em lugares diferentes, e o sintoma é o mesmo.
            raise ErroVisao(
                f"A OpenRouter recusou a leitura da imagem ({resposta.status_code}): "
                "confira a chave e o crédito da conta."
            )
        resposta.raise_for_status()
    except ErroVisao:
        raise
    except httpx.HTTPError as exc:
        log.warning("Leitura da imagem falhou: %s", str(exc)[:160])
        raise ErroVisao(
            "O modelo de imagem não respondeu. O arquivo está guardado; tente de novo."
        ) from exc

    try:
        bruto = json.loads(resposta.json()["choices"][0]["message"]["content"])
    except Exception as exc:  # noqa: BLE001
        raise ErroVisao("Resposta ilegível do modelo de imagem.") from exc

    achados = []
    for item in bruto.get("achados") or []:
        if not isinstance(item, dict):
            continue
        campo, valor = _texto(item.get("campo"), 60), _texto(item.get("valor"), 120)
        if campo and valor:
            achados.append(
                {
                    "campo": campo,
                    "valor": valor,
                    "importancia": _texto(item.get("importancia"), 240),
                    "relevante_para": "",
                }
            )

    return {
        "documento": _texto(bruto.get("documento"), 80) or "Foto sem conteúdo identificável",
        # Cena não é tipo de documento: ver o docstring desta função.
        "codigo_documento": "nao_estruturado",
        # Foto não responde item de checklist sozinha. Quem decide é o advogado,
        # e deixar isto vazio é o que impede o roteamento de marcar item cumprido.
        "serve_para": [],
        "achados": achados[:6],
        "atencao": _lista(bruto.get("atencao")),
        "sugere_pedir": _lista(bruto.get("sugere_pedir")),
        "aviso": (
            "Descrição automática da imagem. Diz o que se vê — não é laudo, não "
            "atribui causa nem culpa, e não decide item do checklist."
        ),
    }
