"""Lê o texto que o OCR extraiu e diz para que aquele documento serve no caso.

O BURACO QUE ISTO FECHA

O classificador de `extractors.py` conhece documentos de IDENTIDADE — CPF, RG,
CNH, CTPS, título, comprovante de residência. Ele é bom nisso: reconhece o tipo,
extrai os campos, confere dígito verificador.

Só que os documentos que decidem uma ação trabalhista não estão nessa lista. CAT,
laudo médico, boletim de ocorrência, atestado, exame, perícia do INSS, CNIS,
contracheque: todos caem em "desconhecido", nenhum campo é extraído, e o texto
que o OCR leu fica guardado sem que ninguém o interprete. Num checklist de doze
itens, sete são assim.

O advogado abre a foto e lê. Este módulo lê antes, e diz o que encontrou.

O QUE ELE DEVOLVE

    documento     o que o texto revela ser, mesmo que o OCR não saiba classificar
    serve_para    a que itens do checklist ele responde, e por quê
    achados       os dados que importam: CID, datas, número de benefício, CAT
    atencao       o que está errado ou faltando NO documento
    sugere_pedir  o documento complementar que ele torna necessário

O QUE ELE NÃO FAZ

Não decide se o item do checklist está cumprido — quem decide é o advogado, e o
`casos.py` continua derivando status de arquivo entregue, não de opinião de
modelo. O que sai daqui é leitura, e vai rotulada como tal.

Não emite juízo sobre procedência, valor de indenização ou chance de êxito. Um
laudo com CID M54.5 sustenta um pedido; ele não ganha a causa, e dizer o
contrário numa tela que a atendente lê ao vivo é o começo de uma promessa ao
cliente que o escritório não fez.

PRIVACIDADE

O texto sai da máquina — vai para o modelo de linguagem, como a triagem e a
conferência já fazem. Mas nada é GRAVADO fora daqui: não há embedding, não há
inserção no banco vetorial. Isso é decisão pendente e está registrada no
CONTEXTO.md, porque documento de cliente traz CPF e dado de saúde, e o servidor
de vetores é compartilhado com outros sistemas.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import httpx

log = logging.getLogger("valor-documento")

TEMPO_MODELO_S = 30.0

#: Abaixo disto o OCR não leu o suficiente para haver o que interpretar — foto
#: ilegível, página em branco, verso de documento.
MINIMO_CARACTERES = 60

CODIGOS_DOCUMENTO = {
    "cpf", "rg", "cin", "cnh", "ctps", "titulo_eleitor", "cartao_sus",
    "comprovante_residencia", "certidao", "nao_estruturado",
}


class ErroValor(Exception):
    """Falha que o usuário precisa ver, sem travar o envio do documento."""


def texto_do_ocr(extracao: dict[str, Any]) -> str:
    """Junta as linhas que o OCR leu, na ordem em que saíram.

    Usa `texto_linhas` e não os campos extraídos: os campos são o que o
    classificador soube nomear, e para CAT e laudo ele não soube nada. O que há
    é o texto cru, e é ele que carrega o CID, a data e o nome do médico.
    """
    linhas = extracao.get("texto_linhas") or []
    partes = [str(l.get("texto", "")).strip() for l in linhas if isinstance(l, dict)]
    # Diagnóstico, assinatura e conclusão podem estar nas páginas finais; a
    # DeepSeek recebe o conteúdo integral que a Mistral conseguiu ler.
    return "\n".join(p for p in partes if p)


INSTRUCAO = """Você assessora um advogado trabalhista brasileiro. Recebe o TEXTO BRUTO
que um OCR extraiu de um documento entregue pelo cliente, e a lista de documentos
que o caso ainda espera.

Diga o que esse documento é e para que ele serve NESTE caso.

REGRAS
- O texto vem de OCR: pode ter erro de leitura, linha fora de ordem e palavra
  truncada. Interprete com isso em mente e NÃO invente o que não está legível.
- `documento`: o que o texto revela ser, em poucas palavras ("CAT", "Laudo
  médico — ortopedia", "Boletim de ocorrência"). Não sabendo, diga "indefinido".
- `serve_para`: a que itens da lista de pendências ele responde. Use o CÓDIGO do
  item como veio na lista. Só inclua item de que você tem evidência no texto.
- `achados`: os dados que um advogado procuraria neste tipo de documento — CID,
  datas, número de benefício, espécie (B31/B91), nome do médico, CRM, empresa,
  período de afastamento. Só o que ESTÁ no texto, com o valor como aparece.
- `atencao`: problemas NO documento — falta assinatura, data ilegível, período
  incompleto, CID sem relação com o relato, documento vencido, página faltando.
- `sugere_pedir`: o documento complementar que este torna necessário. Ex.: um
  laudo que menciona afastamento pelo INSS torna necessário o processo do INSS.
- Não avalie chance de êxito, não estime valores, não afirme que um direito
  existe. Você descreve o documento; quem conclui é o advogado.
- Seja breve: no máximo 4 itens em cada lista.

Em cada `achado`, explique em `importancia` por que o dado importa e em
`relevante_para` qual pedido, prova ou providência jurídica ele ajuda.

Responda APENAS JSON. Em `codigo_documento`, use cpf, rg, cin, cnh, ctps,
titulo_eleitor, cartao_sus, comprovante_residencia ou certidao quando houver
evidência. Para laudo, atestado, contrato, petição, boletim de ocorrência, CNIS
e qualquer tipo livre, use nao_estruturado:
{"documento":"...", "codigo_documento":"nao_estruturado",
 "serve_para":[{"item":"DOC.10","porque":"..."}],
 "achados":[{"campo":"CID","valor":"M54.5","importancia":"identifica o diagnóstico registrado","relevante_para":"provar doença e relacionar afastamentos"}],
 "atencao":["..."],
 "sugere_pedir":["..."]}"""


def _chamar_modelo(mensagem: str) -> dict[str, Any]:
    chave = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not chave:
        raise ErroValor(
            "Leitura do documento desligada: falta DEEPSEEK_API_KEY no .env. "
            "O documento foi guardado e o checklist funciona normalmente."
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
                "max_tokens": 800,
                "messages": [
                    {"role": "system", "content": INSTRUCAO},
                    {"role": "user", "content": mensagem},
                ],
            },
            timeout=TEMPO_MODELO_S,
        )
        resposta.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("Leitura do documento falhou: %s", str(exc)[:160])
        raise ErroValor(
            "O modelo não respondeu. O documento está guardado; tente a leitura de novo."
        ) from exc

    try:
        return json.loads(resposta.json()["choices"][0]["message"]["content"])
    except Exception as exc:
        raise ErroValor("Resposta ilegível do modelo.") from exc


def _texto(valor: Any, limite: int = 200) -> str:
    return re.sub(r"\s+", " ", str(valor or "")).strip()[:limite]


def _lista(bruto: Any, limite: int = 4) -> list[str]:
    saida = []
    for item in bruto if isinstance(bruto, list) else []:
        t = _texto(item)
        if t:
            saida.append(t)
    return saida[:limite]


def ler(
    extracao: dict[str, Any],
    pendencias: list[dict[str, str]] | None = None,
    categoria: str = "",
) -> dict[str, Any]:
    """Interpreta um documento já processado pelo OCR.

    `pendencias` são os itens do checklist ainda em aberto, cada um com `codigo`
    e `nome`. Mandar só os abertos e não os doze é o que mantém o prompt curto e
    impede o modelo de "resolver" item que já foi entregue.
    """
    texto = texto_do_ocr(extracao)
    if len(texto) < MINIMO_CARACTERES:
        raise ErroValor(
            "O OCR leu pouco texto neste arquivo — foto ilegível, página em branco "
            "ou verso do documento. Não há o que interpretar."
        )

    abertas = [
        {"codigo": str(p.get("codigo", "")), "nome": str(p.get("nome", ""))}
        for p in (pendencias or [])
        if p.get("codigo")
    ][:20]

    partes = [f"TEXTO LIDO PELO OCR:\n{texto}"]
    if categoria:
        partes.append(f"TIPO DE AÇÃO: {categoria}")
    if abertas:
        partes.append(
            "DOCUMENTOS QUE O CASO AINDA ESPERA:\n"
            + "\n".join(f"- {p['codigo']}: {p['nome']}" for p in abertas)
        )
    else:
        partes.append("DOCUMENTOS QUE O CASO AINDA ESPERA: nenhum listado.")

    bruto = _chamar_modelo("\n\n".join(partes))

    codigos = {p["codigo"] for p in abertas}
    serve_para = []
    for item in bruto.get("serve_para") or []:
        if not isinstance(item, dict):
            continue
        codigo = _texto(item.get("item"), 30)
        # Código que não estava entre os pendentes é alucinação, ou item já
        # entregue. Nos dois casos não pode aparecer como novidade na tela.
        if codigo not in codigos:
            continue
        serve_para.append({"item": codigo, "porque": _texto(item.get("porque"), 240)})

    achados = []
    for item in bruto.get("achados") or []:
        if not isinstance(item, dict):
            continue
        campo, valor = _texto(item.get("campo"), 60), _texto(item.get("valor"), 120)
        if campo and valor:
            achados.append({
                "campo": campo,
                "valor": valor,
                "importancia": _texto(item.get("importancia"), 240),
                "relevante_para": _texto(item.get("relevante_para"), 240),
            })

    codigo = _texto(bruto.get("codigo_documento"), 40).lower()
    return {
        "documento": _texto(bruto.get("documento"), 80) or "indefinido",
        "codigo_documento": codigo if codigo in CODIGOS_DOCUMENTO else "nao_estruturado",
        "serve_para": serve_para[:4],
        "achados": achados[:8],
        "atencao": _lista(bruto.get("atencao")),
        "sugere_pedir": _lista(bruto.get("sugere_pedir")),
        "aviso": (
            "Leitura automática do texto do OCR. Descreve o documento — não decide "
            "item do checklist nem avalia o mérito do pedido."
        ),
    }
