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
from . import custos_api, skill_de_arquivo

log = logging.getLogger("valor-documento")

#: Resposta completa (dezenas de achados) leva mais que a curta de antes.
TEMPO_MODELO_S = float(os.getenv("VALOR_DOCUMENTO_TIMEOUT_S", "120"))

#: Abaixo disto o OCR não leu o suficiente para haver o que interpretar — foto
#: ilegível, página em branco, verso de documento.
MINIMO_CARACTERES = 60

#: Teto do texto que vai para o modelo de leitura. Era 12 mil, e o que passava
#: disso (as páginas finais de um prontuário, a conclusão de um laudo, os
#: últimos contratos de uma CTPS) nunca era lido — a queixa de "a IA deixa
#: informação passar" começava aqui. 60 mil caracteres (~20 mil tokens) cabem
#: com folga no contexto do modelo. Corta em fronteira de linha para não partir
#: um CID ou uma data no meio.
MAXIMO_CARACTERES = int(os.getenv("VALOR_DOCUMENTO_MAX_CARACTERES", "60000"))

#: Tetos do que a leitura devolve. Altos de propósito: um dado a mais nunca
#: atrapalha a petição; um dado cortado pode custar um pedido.
MAXIMO_ACHADOS = 80
MAXIMO_ITENS_LISTA = 15

CODIGOS_DOCUMENTO = {
    "cpf",
    "rg",
    "cin",
    "cnh",
    "ctps",
    "titulo_eleitor",
    "cartao_sus",
    "comprovante_residencia",
    "certidao",
    "nao_estruturado",
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
    # DeepSeek recebe o conteúdo integral que a Mistral conseguiu ler, até o teto.
    texto = "\n".join(p for p in partes if p)
    if len(texto) <= MAXIMO_CARACTERES:
        return texto
    # Corta na última quebra de linha antes do teto para não partir um dado no
    # meio; se não houver quebra, corta seco no teto.
    corte = texto.rfind("\n", 0, MAXIMO_CARACTERES)
    return texto[: corte if corte > 0 else MAXIMO_CARACTERES]


INSTRUCAO = """Você assessora um advogado brasileiro (trabalhista, previdenciário ou de outra
área, conforme o caso). Recebe o TEXTO BRUTO
que um OCR extraiu de um documento entregue pelo cliente, e a lista de documentos
que o caso ainda espera.

Diga o que esse documento é e para que ele serve NESTE caso.

REGRAS
- O texto vem de OCR: pode ter erro de leitura, linha fora de ordem e palavra
  truncada. Interprete com isso em mente e NÃO invente o que não está legível.
- `documento`: o que o texto revela ser, em poucas palavras ("CAT", "Laudo
  médico — ortopedia", "Boletim de ocorrência"). Não sabendo, diga "indefinido".
  NÃO CONFUNDA documentos parecidos — são coisas diferentes:
  • CAT (Comunicação de Acidente de Trabalho): formulário sobre o ACIDENTE em si,
    emitido pela empresa/sindicato/médico; traz data e hora do acidente, agente
    causador, parte do corpo atingida, CID da lesão. Fala do EVENTO.
  • Comunicação de Decisão / Carta de Concessão do INSS: a decisão do INSS que
    CONCEDE ou INDEFERE um benefício (auxílio-doença B31, auxílio-acidente B94,
    aposentadoria); traz número do benefício, espécie, DIB/DCB, "deferido" ou
    "indeferido". Fala da DECISÃO sobre o benefício, não do acidente. Se o texto
    fala em conceder/negar benefício, é decisão do INSS — NUNCA "CAT".
  • Atestado/Laudo médico: descreve o estado de saúde e o afastamento; não é
    nenhum dos dois acima.
- `serve_para`: a que itens da lista de pendências ele responde. Use o CÓDIGO do
  item como veio na lista. Só inclua item de que você tem evidência no texto.
- `achados`: EXTRAIA O MÁXIMO. Leia o texto INTEIRO, do começo ao fim — as
  páginas finais costumam ter a conclusão, o diagnóstico, a assinatura e os
  valores — e registre CADA dado que possa servir a um advogado, um achado por
  dado. Um dado a mais nunca atrapalha; um dado que você deixa passar pode
  custar um pedido na petição. Procure, conforme o documento:
  • pessoas e empresas: empregador, razão social, CNPJ, endereço do
    estabelecimento, tomador de serviço, médico, CRM, testemunha, autoridade;
  • contrato de trabalho: admissão, demissão, função/cargo, CBO, salário
    (cada valor e cada alteração, com data), jornada, local, forma de
    dispensa, aviso prévio, anotações e contratos anteriores;
  • verbas e valores: cada verba, desconto, base de cálculo, total, FGTS,
    multa, horas extras, adicionais — com o valor e a competência;
  • saúde e acidente: CID (todos), data e hora do acidente, parte do corpo,
    agente causador, afastamento (início, fim, dias), sequela, restrição,
    conclusão do laudo, nexo apontado;
  • INSS: número e espécie do benefício (B31/B91/B94...), DIB, DCB, DER,
    decisão (deferido/indeferido) e o motivo;
  • processo e ocorrência: número, vara, data, protocolo, fatos narrados.
  Registre o valor exatamente como aparece. Dados repetidos com valores
  diferentes (dois salários, três CIDs, vários períodos) viram achados
  separados — nunca escolha só um. Só o que ESTÁ no texto: não invente.
  NÃO inclua CPF, RG nem número de CNH da pessoa como achado: esses números só
  valem quando saem do OCR da foto do próprio documento de identidade (CNPJ,
  matrícula, PIS e número de CTPS podem entrar).
- `atencao`: problemas NO documento — falta assinatura, data ilegível, período
  incompleto, CID sem relação com o relato, documento vencido, página faltando,
  contradição com outro dado do mesmo documento.
- `sugere_pedir`: o documento complementar que este torna necessário. Ex.: um
  laudo que menciona afastamento pelo INSS torna necessário o processo do INSS.
- Não avalie chance de êxito, não estime valores, não afirme que um direito
  existe. Você descreve o documento; quem conclui é o advogado.

Em cada `achado`, explique em `importancia` por que o dado importa e em
`relevante_para` qual pedido, prova ou providência jurídica ele ajuda.

`resumo`: o que o documento diz, de ponta a ponta, em texto corrido (até 8
frases) — quem emitiu, quando, sobre quem, o que registra e o que conclui.

Responda APENAS JSON. Em `codigo_documento`, use cpf, rg, cin, cnh, ctps,
titulo_eleitor, cartao_sus, comprovante_residencia ou certidao quando houver
evidência. Para laudo, atestado, contrato, petição, boletim de ocorrência, CNIS
e qualquer tipo livre, use nao_estruturado:
{"documento":"...", "codigo_documento":"nao_estruturado", "resumo":"...",
 "serve_para":[{"item":"DOC.10","porque":"..."}],
 "achados":[{"campo":"CID","valor":"M54.5","importancia":"identifica o diagnóstico registrado","relevante_para":"provar doença e relacionar afastamentos"}],
 "atencao":["..."],
 "sugere_pedir":["..."]}"""

#: Onde a análise documento a documento da skill documental entra no JSON acima.
_COMO_APLICAR_A_SKILL = """COMO APLICAR OS CRITÉRIOS DA SKILL NESTA RESPOSTA (um documento só):
- Vulnerabilidades e inconsistências internas do documento vão em `atencao`.
- Atualizado ou desatualizado: se o documento tem validade prática (laudo, PPP, comprovante de
  residência, certidão, extrato), diga em `atencao` se a data dele ainda serve ou se está velho demais,
  citando a data.
- Pode melhorar: se dá para obter versão melhor ou mais recente, diga qual em `sugere_pedir`. Documento
  definitivo (RG, certidão de óbito, contrato assinado) não "melhora": só se refaz se estiver ilegível
  ou incompleto — nesse caso, diga em `atencao` o que reenviar.
- Pontos fortes (o que ele comprova) vão nos `achados`, em `importancia` e `relevante_para`."""


def instrucao() -> str:
    """Formato e regras deste módulo + a análise documento a documento da skill documental."""
    criterios = skill_de_arquivo.criterios_documentais(r"^3\.5\b")
    if not criterios:
        return INSTRUCAO
    return f"{INSTRUCAO}\n\n{_COMO_APLICAR_A_SKILL}\n\n{criterios}"


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
                # Era 800, e 800 cortava o JSON no meio justamente nos documentos
                # mais ricos: medido no caso-gabarito (18/09), CTPS e TRCT bateram o
                # teto nas duas tentativas (`finish_reason=length`), carta do INSS e
                # CAT em uma de duas (713 e 781 tokens). O documento ia para a
                # triagem como "não identificado", sem campo nenhum — e o chat não
                # achava o número da CTPS que estava no caso. Depois virou 2000,
                # e 2000 ainda obrigava a resposta a ser curta; agora a leitura
                # pede todos os dados do documento, e 8000 é o teto do modelo.
                "max_tokens": int(os.getenv("VALOR_DOCUMENTO_MAX_TOKENS", "8000")),
                "messages": [
                    {"role": "system", "content": instrucao()},
                    {"role": "user", "content": mensagem},
                ],
            },
            timeout=TEMPO_MODELO_S,
        )
        resposta.raise_for_status()
        custos_api.registrar(
            "deepseek", os.getenv("DEEPSEEK_MODEL", "deepseek-chat"), "classificacao_documento", resposta
        )
    except httpx.HTTPError as exc:
        log.warning("Leitura do documento falhou: %s", str(exc)[:160])
        raise ErroValor(
            "O modelo não respondeu. O documento está guardado; tente a leitura de novo."
        ) from exc

    escolha: dict[str, Any] = {}
    try:
        escolha = resposta.json()["choices"][0]
        return json.loads(escolha["message"]["content"])
    except Exception as exc:
        # Resposta cortada pelo teto é o caso comum de "ilegível", e ele não é
        # aleatório: é o documento com mais dado. Sem isto no log, parece instabilidade.
        log.warning("Leitura do documento ilegível (finish_reason=%s)", escolha.get("finish_reason"))
        raise ErroValor("Resposta ilegível do modelo.") from exc


def _texto(valor: Any, limite: int = 200) -> str:
    return re.sub(r"\s+", " ", str(valor or "")).strip()[:limite]


def _lista(bruto: Any, limite: int = MAXIMO_ITENS_LISTA) -> list[str]:
    saida = []
    for item in bruto if isinstance(bruto, list) else []:
        t = _texto(item, 400)
        if t:
            saida.append(t)
    return saida[:limite]


def ler(
    extracao: dict[str, Any],
    pendencias: list[dict[str, str]] | None = None,
    categoria: str = "",
    correcoes: list[dict[str, Any]] | None = None,
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
    if correcoes:
        partes.append(
            "CORREÇÕES ANTERIORES DA EQUIPE NESTA CATEGORIA:\n"
            "Use somente como alerta contra confusões recorrentes; o texto atual continua mandando.\n"
            + "\n".join(
                f"- {int(c.get('quantidade') or 1)} vez(es): '{c.get('tipo_sugerido') or 'indefinido'}' "
                f"foi corrigido para '{c.get('rotulo_correto')}' ({c.get('item_codigo')})."
                for c in correcoes[:8]
            )
        )

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
        serve_para.append({"item": codigo, "porque": _texto(item.get("porque"), 300)})

    achados = []
    vistos: set[tuple[str, str]] = set()
    for item in bruto.get("achados") or []:
        if not isinstance(item, dict):
            continue
        campo, valor = _texto(item.get("campo"), 80), _texto(item.get("valor"), 500)
        chave = (campo.casefold(), valor.casefold())
        if campo and valor and chave not in vistos:
            vistos.add(chave)
            achados.append(
                {
                    "campo": campo,
                    "valor": valor,
                    "importancia": _texto(item.get("importancia"), 300),
                    "relevante_para": _texto(item.get("relevante_para"), 300),
                }
            )

    codigo = _texto(bruto.get("codigo_documento"), 40).lower()
    return {
        "documento": _texto(bruto.get("documento"), 120) or "indefinido",
        "codigo_documento": codigo
        if codigo in CODIGOS_DOCUMENTO
        else "nao_estruturado",
        "resumo": _texto(bruto.get("resumo"), 1500),
        "serve_para": serve_para[:10],
        "achados": achados[:MAXIMO_ACHADOS],
        "atencao": _lista(bruto.get("atencao")),
        "sugere_pedir": _lista(bruto.get("sugere_pedir")),
        "aviso": (
            "Leitura automática do texto do OCR. Descreve o documento — não decide "
            "item do checklist nem avalia o mérito do pedido."
        ),
    }
