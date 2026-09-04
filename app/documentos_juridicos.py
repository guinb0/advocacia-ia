"""Taxonomia e regras verificáveis para documentos jurídicos do cliente.

A Mistral descreve o documento; este módulo decide o que pode ser aceito. Toda
entidade e todo fato relevante precisam apontar para uma citação existente numa
página do OCR. Confiança do modelo, sozinha, nunca cumpre checklist.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

from . import validators as V

VERSAO_SCHEMA = "documento-universal-v1"


TIPOS: dict[str, dict[str, Any]] = {
    "rg": {"rotulo": "RG", "familia": "identidade", "obrigatorios": ["nome", "numero_documento"]},
    "cin": {"rotulo": "CIN", "familia": "identidade", "obrigatorios": ["nome", "cpf"]},
    "cnh": {"rotulo": "CNH", "familia": "identidade", "obrigatorios": ["nome", "numero_documento"]},
    "cpf": {"rotulo": "CPF", "familia": "identidade", "obrigatorios": ["nome", "cpf"]},
    "ctps": {"rotulo": "CTPS", "familia": "trabalhista", "obrigatorios": ["nome"]},
    "comprovante_residencia": {"rotulo": "Comprovante de residência", "familia": "endereco", "obrigatorios": ["endereco"]},
    "certidao_nascimento": {"rotulo": "Certidão de nascimento", "familia": "civil", "obrigatorios": ["nome", "data_nascimento"]},
    "certidao_casamento": {"rotulo": "Certidão de casamento", "familia": "civil", "obrigatorios": ["nome"]},
    "certidao_obito": {"rotulo": "Certidão de óbito", "familia": "civil", "obrigatorios": ["nome", "data_obito"]},
    "boletim_ocorrencia": {"rotulo": "Boletim de ocorrência", "familia": "policial", "obrigatorios": ["numero_ocorrencia", "data_ocorrencia"]},
    "certidao_ocorrencia_policial": {"rotulo": "Certidão de ocorrência policial", "familia": "policial", "obrigatorios": ["numero_ocorrencia", "data_ocorrencia"]},
    "cat": {"rotulo": "CAT — Comunicação de Acidente de Trabalho", "familia": "acidente", "obrigatorios": ["data_acidente", "trabalhador"]},
    "laudo_medico": {"rotulo": "Laudo médico", "familia": "medico", "obrigatorios": ["paciente", "data_documento", "medico"]},
    "atestado_medico": {"rotulo": "Atestado médico", "familia": "medico", "obrigatorios": ["paciente", "data_documento", "medico"]},
    "exame_medico": {"rotulo": "Exame médico", "familia": "medico", "obrigatorios": ["paciente", "data_documento"]},
    "prontuario_medico": {"rotulo": "Prontuário médico", "familia": "medico", "obrigatorios": ["paciente"]},
    "cnis": {"rotulo": "CNIS", "familia": "previdenciario", "obrigatorios": ["nome", "nit"]},
    "decisao_inss": {"rotulo": "Decisão do INSS", "familia": "previdenciario", "obrigatorios": ["numero_beneficio", "data_documento"]},
    "carta_concessao_inss": {"rotulo": "Carta de concessão do INSS", "familia": "previdenciario", "obrigatorios": ["numero_beneficio"]},
    "holerite": {"rotulo": "Contracheque/Holerite", "familia": "financeiro", "obrigatorios": ["nome", "competencia"]},
    "procuracao": {"rotulo": "Procuração", "familia": "mandato", "obrigatorios": ["outorgante", "outorgado"]},
    "contrato_honorarios": {"rotulo": "Contrato de honorários", "familia": "contrato", "obrigatorios": ["contratante", "contratado"]},
    "declaracao_hipossuficiencia": {"rotulo": "Declaração de hipossuficiência", "familia": "declaracao", "obrigatorios": ["declarante"]},
    "peticao": {"rotulo": "Petição", "familia": "processual", "obrigatorios": []},
    "decisao_judicial": {"rotulo": "Decisão judicial", "familia": "processual", "obrigatorios": []},
    "outro": {"rotulo": "Documento não identificado", "familia": "outro", "obrigatorios": []},
}

ALIASES = {
    "certidao": "outro",
    "certidao policial": "certidao_ocorrencia_policial",
    "certidao de ocorrencia": "certidao_ocorrencia_policial",
    "ocorrencia policial": "certidao_ocorrencia_policial",
    "bo": "boletim_ocorrencia",
    "boletim de ocorrencia policial": "boletim_ocorrencia",
    "comunicacao de acidente de trabalho": "cat",
    "contracheque": "holerite",
    "demonstrativo de pagamento": "holerite",
    "laudo": "laudo_medico",
    "atestado": "atestado_medico",
    "declaracao de pobreza": "declaracao_hipossuficiencia",
}

# Expressões fortes; cada ocorrência vale 35 pontos. Termos deliberadamente
# genéricos como "certidão" não aparecem sozinhos.
REGRAS_TIPO: dict[str, tuple[str, ...]] = {
    "certidao_ocorrencia_policial": (
        "CERTIDAO DE OCORRENCIA POLICIAL", "REGISTRO DO HISTORICO DE PLANTAO",
        "SUPERINTENDENCIA REGIONAL", "OCORRENCIA POLICIAL",
    ),
    "boletim_ocorrencia": ("BOLETIM DE OCORRENCIA", "NATUREZA DA OCORRENCIA", "DELEGACIA DE POLICIA"),
    "cat": ("COMUNICACAO DE ACIDENTE DE TRABALHO", "INFORMACOES DO ACIDENTADO", "CAT"),
    "laudo_medico": ("LAUDO MEDICO", "RELATORIO MEDICO", "DIAGNOSTICO", "CRM"),
    "atestado_medico": ("ATESTADO MEDICO", "ATESTO PARA OS DEVIDOS FINS", "DIAS DE AFASTAMENTO"),
    "prontuario_medico": ("PRONTUARIO", "EVOLUCAO CLINICA", "ANAMNESE"),
    "exame_medico": ("RESULTADO DE EXAME", "EXAME LABORATORIAL", "RESSONANCIA MAGNETICA"),
    "cnis": ("CADASTRO NACIONAL DE INFORMACOES SOCIAIS", "EXTRATO PREVIDENCIARIO", "CNIS"),
    "decisao_inss": ("INSTITUTO NACIONAL DO SEGURO SOCIAL", "DECISAO", "BENEFICIO"),
    "holerite": ("CONTRACHEQUE", "DEMONSTRATIVO DE PAGAMENTO", "REMUNERACAO", "SALARIO BASE"),
    "procuracao": ("PROCURACAO", "OUTORGANTE", "OUTORGADO"),
    "contrato_honorarios": ("CONTRATO DE HONORARIOS", "HONORARIOS ADVOCATICIOS", "CONTRATANTE"),
    "declaracao_hipossuficiencia": ("DECLARACAO DE HIPOSSUFICIENCIA", "HIPOSSUFICIENTE", "POBREZA"),
    "certidao_nascimento": ("CERTIDAO DE NASCIMENTO", "NASCIDO AOS", "NOME DO REGISTRADO"),
    "certidao_casamento": ("CERTIDAO DE CASAMENTO", "REGIME DE BENS", "CONTRAENTES"),
    "certidao_obito": ("CERTIDAO DE OBITO", "DATA DO FALECIMENTO", "DECLARACAO DE OBITO"),
    "ctps": ("CARTEIRA DE TRABALHO", "CTPS", "CONTRATO DE TRABALHO"),
    "cnh": ("CARTEIRA NACIONAL DE HABILITACAO", "PERMISSAO PARA DIRIGIR", "VALIDADE"),
    "cin": ("CARTEIRA DE IDENTIDADE NACIONAL", "REGISTRO GERAL", "CPF"),
    "rg": ("CARTEIRA DE IDENTIDADE", "REGISTRO GERAL", "SECRETARIA DE SEGURANCA"),
}

PADROES_CAMPOS: dict[str, dict[str, str]] = {
    "boletim_ocorrencia": {
        "numero_ocorrencia": r"(?:BO|OCORR[EÊ]NCIA|REGISTRO)\s*(?:N[º°.]|N[ÚU]MERO|:)?\s*([A-Z0-9./-]{6,})",
        "data_ocorrencia": r"(?:DATA\s+(?:DA\s+)?OCORR[EÊ]NCIA|OCORRIDO\s+EM)\s*:?\s*(\d{2}/\d{2}/\d{4})",
    },
    "certidao_ocorrencia_policial": {
        "numero_ocorrencia": r"(?:OCORR[EÊ]NCIA|BO)\s*(?:N[º°.]|N[ÚU]MERO|:)?\s*([A-Z0-9./-]{6,})",
        "data_ocorrencia": r"(?:PLANT[AÃ]O|OCORR[EÊ]NCIA).*?(\d{2}/\d{2}/\d{4})",
    },
    "cat": {
        "numero_cat": r"(?:N[ÚU]MERO\s+(?:DA\s+)?CAT|CAT\s*N[º°.]?)\s*:?\s*([A-Z0-9./-]{5,})",
        "data_acidente": r"(?:DATA\s+(?:DO\s+)?ACIDENTE)\s*:?\s*(\d{2}/\d{2}/\d{4})",
    },
    "laudo_medico": {
        "cid": r"\bCID(?:-?10)?\s*:?\s*([A-Z]\d{2}(?:\.\d{1,2})?)\b",
        "crm": r"\bCRM(?:[-/ ]?[A-Z]{2})?\s*:?\s*(\d{3,8})\b",
        "data_documento": r"\b(\d{2}/\d{2}/\d{4})\b",
    },
    "atestado_medico": {
        "cid": r"\bCID(?:-?10)?\s*:?\s*([A-Z]\d{2}(?:\.\d{1,2})?)\b",
        "crm": r"\bCRM(?:[-/ ]?[A-Z]{2})?\s*:?\s*(\d{3,8})\b",
        "dias_afastamento": r"\b(\d{1,3})\s*(?:DIAS?|DIA\(S\))\b",
        "data_documento": r"\b(\d{2}/\d{2}/\d{4})\b",
    },
    "cnis": {
        "nit": r"\b(?:NIT|PIS|PASEP)\s*:?\s*([0-9.\-/]{11,14})\b",
        "cpf": r"\bCPF\s*:?\s*([0-9.\-]{11,14})\b",
    },
    "holerite": {
        "competencia": r"\bCOMPET[EÊ]NCIA\s*:?\s*(\d{2}/\d{4}|[A-ZÇ]{3,12}/\d{4})\b",
        "cpf": r"\bCPF\s*:?\s*([0-9.\-]{11,14})\b",
    },
}

TERMOS_ORGANIZACAO = (
    "SUPERINTENDENCIA", "MINISTERIO", "POLICIA", "SECRETARIA", "INSTITUTO",
    "EMPRESA", "CORREIOS", "CLINICA", "HOSPITAL", "SERVICO PUBLICO", "TRIBUNAL",
)


#: Campo extraído -> validador determinístico. O nome do campo varia conforme o
#: documento ("nit" no CNIS é o mesmo PIS; "numero_registro" da CNH usa o algoritmo
#: do Denatran), então o mapa traduz para o validador certo em vez de casar por
#: nome exato.
#:
#: Isto existe porque o pipeline Mistral nasceu SEM conferir dígito verificador: o
#: "✓ válido" da tela significava apenas "a citação foi achada no OCR", ou seja, que
#: o modelo não inventou o trecho — nada dizia sobre o valor estar certo. Um CPF com
#: um dígito trocado na digitação, ou lido errado numa foto ruim, passava como
#: "válido 100%". O módulo 11 pega esse erro de graça, sem chamada paga.
CAMPOS_VALIDAVEIS: dict[str, tuple[str, str]] = {
    "cpf": ("cpf", "Dígitos verificadores conferem (módulo 11)."),
    "cnpj": ("cnpj", "Dígitos verificadores conferem."),
    "pis": ("pis", "Dígito verificador do PIS/PASEP confere."),
    "pasep": ("pis", "Dígito verificador do PIS/PASEP confere."),
    "nit": ("pis", "Dígito verificador do NIT confere."),
    "cns": ("cns", "Número do Cartão SUS válido."),
    "cartao_sus": ("cns", "Número do Cartão SUS válido."),
    "titulo_eleitor": ("titulo_eleitor", "Dígitos e faixa de UF conferem."),
    "cep": ("cep", "CEP com formato de 8 dígitos."),
    "numero_registro": ("cnh", "Número de registro válido pelo algoritmo do Denatran."),
    "registro_cnh": ("cnh", "Número de registro válido pelo algoritmo do Denatran."),
    "data_nascimento": ("data_nascimento", "Data real, com idade plausível."),
    "data_emissao": ("data_emissao", "Data real."),
    "data_validade": ("data_validade", "Data real."),
    "data_admissao": ("data_admissao", "Data real."),
    "data_acidente": ("data_emissao", "Data real."),
    "data_documento": ("data_emissao", "Data real."),
    "data_ocorrencia": ("data_emissao", "Data real."),
}

#: Campos sem regra nacional de verificação. Nome, endereço e RG não têm dígito
#: verificador universal — o RG varia por estado. Eles seguem "conferir
#: manualmente" em vez de ganharem um ✓ que não foi conquistado.
CAMPOS_SEM_REGRA = {
    "nome", "nome_mae", "nome_pai", "filiacao", "endereco", "naturalidade",
    "rg", "orgao_emissor", "paciente", "trabalhador", "declarante", "medico",
    "outorgante", "outorgado", "contratante", "contratado",
}


def conferir_campo(nome: str, valor: str) -> tuple[bool | None, str]:
    """Confere um campo pelo validador determinístico. `None` = não há regra.

    A distinção entre `False` e `None` é o ponto: `False` é "este CPF é inválido",
    `None` é "não existe regra nacional para conferir este nome". Colapsar os dois
    em "não aprovado" faria toda certidão com nome de mãe cair em revisão.
    """
    chave = normalizar(nome).lower().replace(" ", "_")
    if chave in CAMPOS_SEM_REGRA:
        return None, "Sem regra de verificação automática — confira manualmente."
    entrada = CAMPOS_VALIDAVEIS.get(chave)
    if entrada is None:
        return None, ""
    codigo, explicacao = entrada
    validador = V.VALIDADORES.get(codigo)
    if validador is None or not str(valor or "").strip():
        return None, ""
    if validador(str(valor)):
        return True, explicacao
    return False, f"Valor não passa na verificação de {codigo.replace('_', ' ')}."


def normalizar(texto: str) -> str:
    base = "".join(
        c for c in unicodedata.normalize("NFKD", str(texto or ""))
        if not unicodedata.combining(c)
    )
    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9\s]", " ", base).upper()).strip()


def schema_anotacao() -> dict[str, Any]:
    """JSON Schema universal: identifica antes de aplicar um schema específico."""
    evidencia = {
        "type": "object",
        "properties": {
            "citacao": {"type": "string"},
            "pagina": {"type": "integer"},
        },
        "required": ["citacao", "pagina"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "tipo_documento": {"type": "string"},
            "subtipo": {"type": "string"},
            "titulo": {"type": "string"},
            "finalidade": {"type": "string"},
            "emissor": {
                "type": "object",
                "properties": {"nome": {"type": "string"}, "tipo": {"type": "string"}, "citacao": {"type": "string"}, "pagina": {"type": "integer"}},
                "required": ["nome", "tipo", "citacao", "pagina"],
                "additionalProperties": False,
            },
            "pessoas": {
                "type": "array",
                # `relacao_com_cliente` só é preenchida quando o PRÓPRIO documento
                # diz o vínculo (filiação, cônjuge, responsável, empregador). O que
                # o documento não afirma fica vazio aqui e é o parecer do caso que
                # infere, cruzando documentos e entrevista — ver `rag.py`.
                "items": {"type": "object", "properties": {
                    "nome": {"type": "string"}, "papel": {"type": "string"},
                    "relacao_com_cliente": {"type": "string"},
                    "citacao": {"type": "string"}, "pagina": {"type": "integer"},
                }, "required": ["nome", "papel", "relacao_com_cliente", "citacao", "pagina"], "additionalProperties": False},
            },
            "organizacoes": {
                "type": "array",
                "items": {"type": "object", "properties": {
                    "nome": {"type": "string"}, "papel": {"type": "string"},
                    "citacao": {"type": "string"}, "pagina": {"type": "integer"},
                }, "required": ["nome", "papel", "citacao", "pagina"], "additionalProperties": False},
            },
            "campos": {
                "type": "array",
                "items": {"type": "object", "properties": {
                    "campo": {"type": "string"}, "valor": {"type": "string"},
                    "citacao": {"type": "string"}, "pagina": {"type": "integer"},
                }, "required": ["campo", "valor", "citacao", "pagina"], "additionalProperties": False},
            },
            "eventos": {
                "type": "array",
                "items": {"type": "object", "properties": {
                    "fato": {"type": "string"}, "data": {"type": "string"},
                    "local": {"type": "string"}, "citacao": {"type": "string"},
                    "pagina": {"type": "integer"},
                }, "required": ["fato", "data", "local", "citacao", "pagina"], "additionalProperties": False},
            },
            "itens_checklist": {
                "type": "array",
                "items": {"type": "object", "properties": {
                    "codigo": {"type": "string"}, "justificativa": {"type": "string"},
                    "citacao": {"type": "string"}, "pagina": {"type": "integer"},
                }, "required": ["codigo", "justificativa", "citacao", "pagina"], "additionalProperties": False},
            },
            "dados_sensiveis": {"type": "array", "items": {"type": "string"}},
            "alertas": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["tipo_documento", "subtipo", "titulo", "finalidade", "emissor", "pessoas", "organizacoes", "campos", "eventos", "itens_checklist", "dados_sensiveis", "alertas"],
        "additionalProperties": False,
    }


def prompt_anotacao(categoria: str, checklist: list[dict[str, str]]) -> str:
    permitidos = "\n".join(f"- {i['codigo']}: {i['nome']}" for i in checklist)
    tipos = ", ".join(k for k in TIPOS if k != "outro")
    return f"""Analise este documento jurídico brasileiro sem fazer juízo de mérito.
Classifique `tipo_documento` usando somente um destes códigos: {tipos}, outro.
Não use `certidao` genericamente: diferencie certidão civil, certidão de ocorrência
policial e boletim de ocorrência. Instituição nunca é pessoa. Para cada pessoa,
campo, evento e item do checklist, copie uma citação literal contínua e informe a
página (começando em 1). Se não houver evidência, omita o item. Strings desconhecidas
devem ser vazias; não invente.

`papel` é a função da pessoa NESTE documento (paciente, vítima, declarante, médico,
condutor, empregador, testemunha). `relacao_com_cliente` é o vínculo dela com o
cliente do escritório — parentesco (esposa, filho, pai), vínculo de trabalho (chefe,
colega) ou de processo (agressor, assaltante, preposto). Preencha
`relacao_com_cliente` SOMENTE quando o próprio documento afirmar o vínculo (campo de
filiação, cônjuge, responsável legal, empregador). Se o documento não disser, deixe
vazio: quem cruza documentos e infere parentesco é o parecer do caso, não você.

Categoria do caso: {categoria or 'não informada'}.
Itens permitidos do checklist:\n{permitidos or '- nenhum'}"""


def paginas_texto(ocr: dict[str, Any]) -> list[tuple[int, str]]:
    paginas = []
    for i, pagina in enumerate(ocr.get("paginas") or []):
        paginas.append((int(pagina.get("numero") or i + 1), str(pagina.get("markdown") or "")))
    return paginas


def localizar_citacao(ocr: dict[str, Any], citacao: str, pagina: int | None = None) -> int | None:
    alvo = normalizar(citacao)
    if len(alvo) < 4:
        return None
    candidatas = paginas_texto(ocr)
    if pagina:
        candidatas.sort(key=lambda item: item[0] != pagina)
    for numero, texto in candidatas:
        if alvo in normalizar(texto):
            return numero
    return None


def normalizar_tipo(valor: str) -> str:
    cru = normalizar(valor).lower()
    snake = re.sub(r"[^a-z0-9]+", "_", cru).strip("_")
    if snake in TIPOS:
        return snake
    sem_sep = cru.replace("_", " ")
    for alias, codigo in ALIASES.items():
        if normalizar(alias).lower() in sem_sep:
            return codigo
    return "outro"


def classificar(ocr: dict[str, Any]) -> dict[str, Any]:
    texto = normalizar(str(ocr.get("texto_completo") or ""))
    anotacao = ocr.get("anotacao") if isinstance(ocr.get("anotacao"), dict) else {}
    candidato_mistral = normalizar_tipo(str(anotacao.get("tipo_documento") or ""))
    pontuacoes = {
        tipo: min(100, sum(35 for termo in termos if normalizar(termo) in texto))
        for tipo, termos in REGRAS_TIPO.items()
    }
    deterministico = max(pontuacoes, key=pontuacoes.get) if pontuacoes else "outro"
    pontos = pontuacoes.get(deterministico, 0)
    conflito = candidato_mistral != "outro" and pontos >= 70 and candidato_mistral != deterministico
    if pontos >= 70:
        tipo = deterministico
        fonte = "mistral+regras" if candidato_mistral == tipo else "regras"
        confianca = 96 if candidato_mistral == tipo else 88
    elif candidato_mistral != "outro":
        tipo, fonte, confianca = candidato_mistral, "mistral", 82
    elif pontos >= 35:
        tipo, fonte, confianca = deterministico, "regras", 72
    else:
        tipo, fonte, confianca = "outro", "indefinido", 0
    config = TIPOS[tipo]
    evidencias = [
        termo for termo in REGRAS_TIPO.get(tipo, ()) if normalizar(termo) in texto
    ][:4]
    return {
        "tipo": tipo,
        "subtipo": str(anotacao.get("subtipo") or "")[:120],
        "rotulo": config["rotulo"],
        "familia": config["familia"],
        "confianca": confianca,
        "fonte": fonte,
        "conflito": conflito,
        "tipo_sugerido_mistral": candidato_mistral,
        "pontuacoes": pontuacoes,
        "evidencias": evidencias,
    }


def _item_com_citacao(ocr: dict[str, Any], item: dict[str, Any]) -> dict[str, Any] | None:
    citacao = re.sub(r"\s+", " ", str(item.get("citacao") or "")).strip()
    pagina = localizar_citacao(ocr, citacao, int(item.get("pagina") or 0) or None)
    if pagina is None:
        return None
    return {**item, "citacao": citacao[:500], "pagina": pagina, "evidencia_verificada": True}


def extrair(ocr: dict[str, Any], classificacao: dict[str, Any]) -> dict[str, Any]:
    anotacao = ocr.get("anotacao") if isinstance(ocr.get("anotacao"), dict) else {}
    recusados: list[dict[str, Any]] = []

    def verificados(chave: str) -> list[dict[str, Any]]:
        saida = []
        for item in anotacao.get(chave) or []:
            if not isinstance(item, dict):
                continue
            valido = _item_com_citacao(ocr, item)
            if valido:
                saida.append(valido)
            else:
                recusados.append({"origem": chave, "valor": str(item)[:300], "motivo": "citação não encontrada"})
        return saida

    pessoas, organizacoes = verificados("pessoas"), verificados("organizacoes")
    pessoas_validas = []
    for pessoa in pessoas:
        nome = normalizar(str(pessoa.get("nome") or ""))
        if any(termo in nome for termo in TERMOS_ORGANIZACAO):
            organizacoes.append({**pessoa, "papel": pessoa.get("papel") or "instituição", "corrigido_de_pessoa": True})
            recusados.append({"origem": "pessoas", "valor": pessoa.get("nome"), "motivo": "entidade institucional"})
        elif len(nome.split()) >= 2:
            pessoas_validas.append(pessoa)

    campos = verificados("campos")
    existentes = {normalizar(str(c.get("campo") or "")).lower().replace(" ", "_") for c in campos}

    # A anotacao universal descreve pessoas separadamente dos campos. Promover
    # uma pessoa citada para o schema especifico evita perder nome/paciente/etc.
    campos_por_papel = {
        "nome": {"titular", "cliente", "registrado", "segurado"},
        "paciente": {"paciente"},
        "trabalhador": {"trabalhador", "empregado", "acidentado"},
        "outorgante": {"outorgante"},
        "outorgado": {"outorgado"},
        "contratante": {"contratante"},
        "contratado": {"contratado"},
        "declarante": {"declarante"},
        "medico": {"medico"},
    }
    for campo, papeis in campos_por_papel.items():
        if campo in existentes:
            continue
        papeis_normalizados = {normalizar(papel).lower() for papel in papeis}
        pessoa = next(
            (p for p in pessoas_validas if normalizar(str(p.get("papel") or "")).lower() in papeis_normalizados),
            None,
        )
        if pessoa:
            campos.append({
                "campo": campo,
                "valor": pessoa.get("nome") or "",
                "citacao": pessoa.get("citacao") or "",
                "pagina": pessoa.get("pagina"),
                "evidencia_verificada": True,
                "origem": "pessoa_citada",
            })
            existentes.add(campo)
    texto = str(ocr.get("texto_completo") or "")
    tipo = classificacao["tipo"]
    for campo, padrao in PADROES_CAMPOS.get(tipo, {}).items():
        if campo in existentes:
            continue
        achado = re.search(padrao, texto, flags=re.I | re.S)
        if not achado:
            continue
        valor = achado.group(1).strip()
        citacao = re.sub(r"\s+", " ", achado.group(0)).strip()
        pagina = localizar_citacao(ocr, citacao) or 1
        campos.append({"campo": campo, "valor": valor, "citacao": citacao[:500], "pagina": pagina, "evidencia_verificada": True, "origem": "regra"})
        existentes.add(campo)

    emissor = anotacao.get("emissor") if isinstance(anotacao.get("emissor"), dict) else {}
    emissor_valido = _item_com_citacao(ocr, emissor) if emissor.get("nome") else None
    eventos = verificados("eventos")
    itens = verificados("itens_checklist")
    return {
        "schema": f"{tipo}-v1",
        "tipo": tipo,
        "titulo": str(anotacao.get("titulo") or classificacao["rotulo"])[:200],
        "finalidade": str(anotacao.get("finalidade") or "")[:500],
        "emissor": emissor_valido or {},
        "pessoas": pessoas_validas,
        "organizacoes": organizacoes,
        "campos": campos,
        "eventos": eventos,
        "itens_checklist": itens,
        "dados_sensiveis": [str(x)[:120] for x in anotacao.get("dados_sensiveis") or [] if str(x).strip()][:12],
        "alertas_mistral": [str(x)[:300] for x in anotacao.get("alertas") or [] if str(x).strip()][:12],
        "recusados": recusados,
    }


def sugerir_itens_checklist(
    classificacao: dict[str, Any], checklist: list[dict[str, Any]]
) -> list[str]:
    """Relaciona tipo confirmado ao checklist sem depender do palpite do LLM."""
    tipo = str(classificacao.get("tipo") or "outro")
    if classificacao.get("confianca", 0) < 80 or tipo == "outro":
        return []
    exatos = [
        str(item["codigo"])
        for item in checklist
        if str(item.get("tipo_ocr") or "") == tipo
    ]
    if exatos:
        return exatos

    termos_por_tipo = {
        "procuracao": ("PROCURACAO",),
        "declaracao_hipossuficiencia": ("HIPOSSUFICIENCIA",),
        "holerite": ("CONTRACHEQUE", "HOLERITE"),
        "cnis": ("CNIS",),
        "cat": ("COMUNICACAO DE ACIDENTE",),
        "boletim_ocorrencia": ("BOLETIM DE OCORRENCIA",),
        "certidao_ocorrencia_policial": ("BOLETIM DE OCORRENCIA", "OCORRENCIA POLICIAL"),
        "atestado_medico": ("ATESTADO MEDICO",),
        "laudo_medico": ("LAUDO MEDICO",),
        "prontuario_medico": ("PRONTUARIO",),
        "exame_medico": ("EXAME",),
        "decisao_inss": ("DECISAO DO INSS", "COMUNICACAO DE DECISAO"),
        "carta_concessao_inss": ("CARTA DE CONCESSAO",),
        "ctps": ("CTPS", "CARTEIRA DE TRABALHO"),
        "comprovante_residencia": ("COMPROVANTE DE RESIDENCIA",),
    }
    termos = termos_por_tipo.get(tipo, ())
    return [
        str(item["codigo"])
        for item in checklist
        if any(normalizar(termo) in normalizar(str(item.get("nome") or "")) for termo in termos)
    ][:3]


def _similaridade_nome(a: str, b: str) -> float:
    na, nb = normalizar(a), normalizar(b)
    if not na or not nb:
        return 0.0
    if na in nb or nb in na:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def validar(
    ocr: dict[str, Any],
    classificacao: dict[str, Any],
    extracao: dict[str, Any],
    *,
    cliente: str,
    checklist: list[dict[str, str]],
    item_escolhido: str | None,
) -> dict[str, Any]:
    texto = str(ocr.get("texto_completo") or "")
    scores = []
    for pagina in ocr.get("paginas") or []:
        if isinstance(pagina.get("confianca"), (int, float)):
            scores.append(float(pagina["confianca"]))
        for bloco in pagina.get("blocos") or []:
            if isinstance(bloco.get("confianca"), (int, float)):
                scores.append(float(bloco["confianca"]))
    confianca_ocr = sum(scores) / len(scores) if scores else (0.75 if len(texto) >= 80 else 0.0)
    legivel = len(texto.strip()) >= 60 and confianca_ocr >= 0.55
    tipo_confirmado = classificacao["confianca"] >= 80 and not classificacao.get("conflito")

    campos_por_nome = {
        normalizar(str(c.get("campo") or "")).lower().replace(" ", "_"): c
        for c in extracao.get("campos") or []
    }
    obrigatorios = list(TIPOS[classificacao["tipo"]].get("obrigatorios") or [])
    presentes = [nome for nome in obrigatorios if nome in campos_por_nome]
    cobertura = 100 if not obrigatorios else round(100 * len(presentes) / len(obrigatorios))

    # Conferência determinística, sobre o valor já extraído. Não custa chamada e
    # pega o que o modelo não tem como pegar: dígito verificador que não fecha.
    # O veredito de cada campo volta ANEXADO ao campo, porque a tela mostra campo a
    # campo — e um "✓ válido" que só significava "a citação existe no OCR" era a
    # informação errada no lugar de maior confiança do advogado.
    campos_invalidos: list[str] = []
    for campo in extracao.get("campos") or []:
        nome_campo = str(campo.get("campo") or "")
        veredito, observacao = conferir_campo(nome_campo, str(campo.get("valor") or ""))
        campo["valido_regra"] = veredito
        if observacao:
            campo["observacao_regra"] = observacao
        if veredito is False:
            campos_invalidos.append(normalizar(nome_campo).lower().replace(" ", "_"))

    papeis_sujeito = {"titular", "cliente", "vitima", "vítima", "paciente", "trabalhador", "segurado", "declarante", "outorgante", "contratante"}
    sujeitos = [
        p for p in extracao.get("pessoas") or []
        if normalizar(str(p.get("papel") or "")).lower() in {normalizar(x).lower() for x in papeis_sujeito}
    ]

    # TODAS as pessoas citadas no documento, com o papel que a leitura lhes deu —
    # é o material que a tela mostra como "partes" e que o parecer do caso usa para
    # contextualizar quem é quem (cliente, agressor, chefe, perito...).
    partes = [
        {
            "nome": str(p.get("nome") or "").strip(),
            "papel": str(p.get("papel") or "").strip() or "não informado",
            "relacao_com_cliente": str(p.get("relacao_com_cliente") or "").strip(),
            "pagina": p.get("pagina"),
        }
        for p in extracao.get("pessoas") or []
        if str(p.get("nome") or "").strip()
    ]

    # O nome que NÃO bate com o cliente deixou de ser "problema": num acidente, o
    # documento traz vítima, agressor, motorista, perito — gente que não é o
    # cliente e cuja presença é esperada. Em vez de reprovar, o sistema identifica
    # a pessoa principal e seu papel; a divergência de nome vira informação (a tela
    # a mostra em amarelo), não uma ressalva que trava a revisão.
    pessoa_principal: dict[str, Any] | None = None
    pessoa_principal_confere: bool | None = None
    if sujeitos:
        if cliente:
            principal = max(sujeitos, key=lambda p: _similaridade_nome(cliente, str(p.get("nome") or "")))
            pessoa_principal_confere = (
                _similaridade_nome(cliente, str(principal.get("nome") or "")) >= 0.72
            )
        else:
            principal = sujeitos[0]
        pessoa_principal = {
            "nome": str(principal.get("nome") or "").strip(),
            "papel": str(principal.get("papel") or "").strip() or "não informado",
            "relacao_com_cliente": str(principal.get("relacao_com_cliente") or "").strip(),
            "pagina": principal.get("pagina"),
        }

    divergencias: list[str] = []

    validos = {i["codigo"] for i in checklist}
    sugeridos = list(dict.fromkeys(
        str(i.get("codigo")) for i in extracao.get("itens_checklist") or []
        if str(i.get("codigo") or "") in validos
    ))
    if not sugeridos:
        sugeridos = sugerir_itens_checklist(classificacao, checklist)
    if item_escolhido and item_escolhido in validos and not sugeridos:
        sugeridos = [item_escolhido]

    motivos_revisao = []
    if not legivel:
        motivos_revisao.append("OCR com texto insuficiente ou baixa confiança.")
    if not tipo_confirmado:
        motivos_revisao.append("Tipo documental não confirmado com segurança.")
    if classificacao.get("conflito"):
        motivos_revisao.append("Classificador e evidências textuais discordam sobre o tipo.")
    if obrigatorios and cobertura < 60:
        motivos_revisao.append("Campos mínimos do tipo documental não foram encontrados.")
    if extracao.get("recusados"):
        motivos_revisao.append("Parte da interpretação foi recusada por falta de citação verificável.")
    if campos_invalidos:
        motivos_revisao.append(
            "Campo com dígito verificador que não fecha: "
            + ", ".join(sorted(set(campos_invalidos)))
            + ". Confira o valor no documento."
        )
    motivos_revisao.extend(divergencias)
    if not sugeridos:
        motivos_revisao.append("Nenhum item do checklist foi sustentado por evidência.")

    # Dígito verificador que não fecha derruba `campos_validados`, e com ele
    # `dados_utilizaveis`: um CPF errado não pode ser consumido por fluxo
    # automatizado nem preencher contrato. É a diferença entre "o modelo leu" e
    # "o número está certo".
    campos_validados = bool((not obrigatorios or cobertura >= 80) and not campos_invalidos)
    atende_checklist = bool(sugeridos and legivel and tipo_confirmado)
    status = "REPROVADO" if not legivel else (
        "APROVADO" if tipo_confirmado and campos_validados and atende_checklist and not motivos_revisao else "APROVADO_COM_RESSALVAS"
    )
    return {
        "veredito": status,
        "resumo": (
            "Leitura técnica concluída; tipo, campos e destino foram confirmados."
            if status == "APROVADO"
            else "Leitura técnica concluída, mas há pontos que exigem conferência humana."
            if legivel else "Não foi possível obter leitura técnica confiável do arquivo."
        ),
        "estados": {
            "arquivo_legivel": legivel,
            "tipo_confirmado": tipo_confirmado,
            "campos_validados": campos_validados,
            "atende_checklist": atende_checklist,
            "evidencias_extraidas": False,
        },
        "confianca_ocr": round(confianca_ocr, 4),
        "score_legibilidade": round(confianca_ocr * 100),
        "texto_utilizavel": legivel,
        "dados_utilizaveis": bool(legivel and tipo_confirmado and campos_validados),
        "cobertura_campos_percentual": cobertura,
        "campos_obrigatorios": obrigatorios,
        "campos_presentes": presentes,
        "campos_invalidos": sorted(set(campos_invalidos)),
        "itens_atendidos": sugeridos[:3],
        "divergencias": divergencias,
        "partes": partes,
        "pessoa_principal": pessoa_principal,
        "pessoa_principal_confere": pessoa_principal_confere,
        "revisao_necessaria": bool(motivos_revisao),
        "motivos_revisao": list(dict.fromkeys(motivos_revisao)),
        "erros": list(dict.fromkeys(motivos_revisao if not legivel else divergencias)),
        "avisos": list(dict.fromkeys((extracao.get("alertas_mistral") or []) + motivos_revisao)),
    }


def extrair_evidencias(
    ocr: dict[str, Any], extracao: dict[str, Any], validacao: dict[str, Any]
) -> dict[str, Any]:
    evidencias = []
    sensiveis = {normalizar(x) for x in extracao.get("dados_sensiveis") or []}
    for campo in extracao.get("campos") or []:
        citacao = str(campo.get("citacao") or "")
        pagina = localizar_citacao(ocr, citacao, int(campo.get("pagina") or 0) or None)
        if pagina is None:
            continue
        nome = str(campo.get("campo") or "dado")
        valor = str(campo.get("valor") or "")
        categoria = "saude" if normalizar(nome) in {"CID", "DIAGNOSTICO", "AFASTAMENTO"} else "identificacao"
        evidencias.append({
            "categoria": categoria,
            "fato": f"{nome}: {valor}",
            "citacao": citacao[:500],
            "pagina": pagina,
            "sensivel": categoria == "saude" or any(s and s in normalizar(citacao) for s in sensiveis),
            "origem": "campo_verificado",
        })
    for evento in extracao.get("eventos") or []:
        citacao = str(evento.get("citacao") or "")
        pagina = localizar_citacao(ocr, citacao, int(evento.get("pagina") or 0) or None)
        if pagina is None:
            continue
        evidencias.append({
            "categoria": "evento",
            "fato": str(evento.get("fato") or "")[:400],
            "citacao": citacao[:500],
            "pagina": pagina,
            "sensivel": any(s and s in normalizar(citacao) for s in sensiveis),
            "origem": "evento_verificado",
        })
    validacao.setdefault("estados", {})["evidencias_extraidas"] = bool(evidencias)
    return {
        "evidencias": evidencias[:30],
        "quantidade": len(evidencias[:30]),
        "dados_sensiveis": extracao.get("dados_sensiveis") or [],
        "aviso": "Somente fatos com citação localizada no OCR foram incluídos.",
    }


def resumo_documento(
    classificacao: dict[str, Any], extracao: dict[str, Any],
    validacao: dict[str, Any], evidencias: dict[str, Any],
) -> dict[str, Any]:
    principais = [e["fato"] for e in evidencias.get("evidencias") or []][:8]
    return {
        "tipo": classificacao["rotulo"],
        "confianca_tipo": classificacao["confianca"],
        "finalidade": extracao.get("finalidade") or "",
        "pontos_principais": principais,
        "alertas": list(dict.fromkeys(validacao.get("avisos") or []))[:10],
        "itens_atendidos": validacao.get("itens_atendidos") or [],
        "revisao_necessaria": bool(validacao.get("revisao_necessaria")),
        "dados_sensiveis": extracao.get("dados_sensiveis") or [],
        "aviso": "Resumo derivado exclusivamente de evidências citadas; exige revisão profissional.",
    }
