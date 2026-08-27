"""Classificação do tipo de documento e extração dos campos."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field, replace
from statistics import median

from . import validators as V

# --------------------------------------------------------------- normalização

# Confusões típicas do OCR quando o contexto é numérico.
_LETRA_PARA_DIGITO = str.maketrans(
    {
        "O": "0", "o": "0", "D": "0", "Q": "0",
        "I": "1", "i": "1", "l": "1", "L": "1", "|": "1",
        "Z": "2", "z": "2",
        "A": "4",
        "S": "5", "s": "5",
        "G": "6", "b": "6",
        "T": "7",
        "B": "8",
        "g": "9", "q": "9",
    }
)


def sem_acento(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalizar(texto: str) -> str:
    """Maiúsculas, sem acento, espaços colapsados — usado para busca de rótulos."""
    return re.sub(r"\s+", " ", sem_acento(texto or "").upper()).strip()


def digitos_corrigidos(trecho: str) -> str:
    """Converte letras que o OCR confundiu com dígitos e devolve só os dígitos."""
    return V.only_digits(trecho.translate(_LETRA_PARA_DIGITO))


# ------------------------------------------------------------------- modelo


@dataclass
class Campo:
    nome: str
    rotulo: str
    valor: str
    valor_bruto: str = ""
    confianca: float = 0.0
    valido: bool | None = None
    observacao: str = ""
    origem: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["confianca"] = round(self.confianca, 4)
        return d


@dataclass
class Linha:
    texto: str
    confianca: float
    y: float
    x: float
    largura: float = 0.0
    altura: float = 0.0

    @property
    def norm(self) -> str:
        return normalizar(self.texto)


# ------------------------------------------------------- tipos de documento

ROTULOS_TIPO = {
    "cpf": "CPF (Cadastro de Pessoa Física)",
    "rg": "RG (Carteira de Identidade)",
    "cin": "CIN (Carteira de Identidade Nacional)",
    "cnh": "CNH (Carteira Nacional de Habilitação)",
    "ctps": "CTPS (Carteira de Trabalho)",
    "titulo_eleitor": "Título de Eleitor",
    "cartao_sus": "Cartão Nacional de Saúde (SUS)",
    "comprovante_residencia": "Comprovante de Residência",
    "certidao": "Certidão (Nascimento/Casamento/Óbito)",
    "desconhecido": "Documento não identificado",
}

# (palavra-chave normalizada, peso)
PALAVRAS_TIPO: dict[str, list[tuple[str, int]]] = {
    "cnh": [
        ("CARTEIRA NACIONAL DE HABILITACAO", 12), ("HABILITACAO", 6), ("PERMISSAO PARA DIRIGIR", 8),
        ("N REGISTRO", 5), ("N.REGISTRO", 5), ("REGISTRO", 2), ("1 HABILITACAO", 7),
        ("PRIMEIRA HABILITACAO", 7), ("VALIDADE", 3), ("CAT. HAB", 6), ("CAT HAB", 6),
        ("ACC", 3), ("RENACH", 8), ("DETRAN", 6), ("CODIGO DE SEGURANCA", 5),
        ("OBSERVACOES", 2), ("LOCAL", 1), ("DENATRAN", 6), ("MOTORISTA", 4),
    ],
    "ctps": [
        ("CARTEIRA DE TRABALHO", 12), ("PREVIDENCIA SOCIAL", 8), ("CTPS", 8),
        ("MINISTERIO DO TRABALHO", 8), ("SERIE", 4), ("CONTRATO DE TRABALHO", 6),
        ("PIS", 4), ("PIS/PASEP", 6), ("NIT", 3), ("SECRETARIA DE INSPECAO DO TRABALHO", 6),
        ("N DA CARTEIRA", 4), ("QUALIFICACAO CIVIL", 6),
    ],
    "rg": [
        ("CARTEIRA DE IDENTIDADE", 10), ("REGISTRO GERAL", 10), ("SECRETARIA DE SEGURANCA PUBLICA", 8),
        ("SSP", 4), ("DATA DE EXPEDICAO", 5), ("NATURALIDADE", 4), ("DOC. ORIGEM", 5),
        ("DOC ORIGEM", 5), ("INSTITUTO DE IDENTIFICACAO", 8), ("VALIDA EM TODO O TERRITORIO NACIONAL", 6),
        ("FILIACAO", 3), ("LEI N 7.116", 6),
    ],
    "cin": [
        ("CARTEIRA DE IDENTIDADE NACIONAL", 14), ("IDENTIDADE NACIONAL", 8),
        ("REPUBLICA FEDERATIVA DO BRASIL", 3), ("NUMERO UNICO", 5), ("CIN", 4),
    ],
    "cpf": [
        ("CADASTRO DE PESSOAS FISICAS", 12), ("CADASTRO DE PESSOA FISICA", 12),
        ("MINISTERIO DA FAZENDA", 6), ("RECEITA FEDERAL", 8), ("CPF", 4),
        ("SECRETARIA DA RECEITA FEDERAL", 8), ("COMPROVANTE DE INSCRICAO", 6),
    ],
    "titulo_eleitor": [
        ("TITULO DE ELEITOR", 12), ("JUSTICA ELEITORAL", 10), ("TRIBUNAL SUPERIOR ELEITORAL", 10),
        ("INSCRICAO", 4), ("ZONA", 4), ("SECAO", 4), ("ELEITORAL", 4),
    ],
    "cartao_sus": [
        ("CARTAO NACIONAL DE SAUDE", 14), ("SISTEMA UNICO DE SAUDE", 10), ("SUS", 5),
        ("MINISTERIO DA SAUDE", 8), ("CNS", 4),
    ],
    "comprovante_residencia": [
        ("FATURA", 6), ("CONTA DE LUZ", 8), ("CONTA DE ENERGIA", 8), ("ENERGIA ELETRICA", 8),
        ("VENCIMENTO", 4), ("INSTALACAO", 5), ("CONSUMO", 4), ("KWH", 6), ("CEMIG", 8),
        ("ENEL", 8), ("COPASA", 8), ("SABESP", 8), ("LIGHT", 5), ("EQUATORIAL", 8),
        ("NOTA FISCAL", 4), ("CODIGO DE BARRAS", 3), ("TOTAL A PAGAR", 5), ("CEP", 3),
        ("CLIENTE", 2), ("UNIDADE CONSUMIDORA", 8),
    ],
    "certidao": [
        ("CERTIDAO", 10), ("REGISTRO CIVIL", 8), ("NASCIMENTO", 4), ("CASAMENTO", 4),
        ("OBITO", 4), ("CARTORIO", 8), ("OFICIAL DE REGISTRO", 6), ("LIVRO", 3),
        ("FOLHA", 3), ("TERMO", 3), ("MATRICULA", 3),
    ],
}

# Campos que cada tipo deve conter para ser considerado "completo".
CAMPOS_ESPERADOS: dict[str, list[str]] = {
    "cpf": ["cpf", "nome"],
    "rg": ["rg", "nome", "data_nascimento"],
    "cin": ["cpf", "nome", "data_nascimento"],
    "cnh": ["cpf", "nome", "cnh", "data_nascimento", "data_validade"],
    "ctps": ["nome", "pis", "data_nascimento"],
    "titulo_eleitor": ["titulo_eleitor", "nome"],
    "cartao_sus": ["cns", "nome"],
    "comprovante_residencia": ["cep", "endereco"],
    "certidao": ["nome", "data_nascimento"],
    "desconhecido": [],
}

TIPOS_COM_TITULAR = frozenset(
    {"rg", "cnh", "ctps", "cin", "cpf", "titulo_eleitor", "cartao_sus", "certidao"}
)
TIPOS_COM_FILIACAO = frozenset({"rg", "cnh", "cin", "certidao"})
# CPF só sai da foto do documento de identificação que o imprime de verdade.
# CTPS, comprovante, título etc. podem citar um CPF no texto — isso não é a
# foto do documento do cliente, e misturar esses números no dossiê já gerou
# CPF errado. Nome, endereço e demais campos seguem a regra por tipo.
TIPOS_COM_CPF = frozenset({"cpf", "cnh", "cin"})


def classificar(texto_norm: str) -> tuple[str, int, dict[str, int]]:
    pontos: dict[str, int] = {}
    for tipo, palavras in PALAVRAS_TIPO.items():
        total = sum(peso for palavra, peso in palavras if palavra in texto_norm)
        if total:
            pontos[tipo] = total

    if not pontos:
        return "desconhecido", 0, {}

    tipo = max(pontos, key=lambda k: pontos[k])
    return (tipo, pontos[tipo], pontos) if pontos[tipo] >= 10 else ("desconhecido", pontos[tipo], pontos)


# -------------------------------------------------------- geometria da página

# Documentos são diagramados em colunas, e o rótulo quase sempre fica logo acima
# (ou imediatamente à esquerda) do valor. Associar por índice de linha erra sempre
# que duas colunas dividem a mesma altura — então tudo aqui é resolvido por posição.


def _fim_x(ln: Linha) -> float:
    return ln.x + max(ln.largura, 1.0)


def _sobrepoe_x(a: Linha, b: Linha, folga: float) -> bool:
    return a.x - folga < _fim_x(b) and b.x - folga < _fim_x(a)


def altura_tipica(linhas: list[Linha]) -> float:
    alturas = [ln.altura for ln in linhas if ln.altura > 0]
    return float(median(alturas)) if alturas else 16.0


def _escala(linhas: list[Linha], ref: Linha) -> float:
    """Altura de referência: a do próprio bloco ou a mediana da página, o que for maior.

    Sem isso um rótulo em fonte miúda encolheria demais a janela de busca.
    """
    return max(ref.altura if ref.altura > 0 else 0.0, altura_tipica(linhas))


def indices_abaixo(linhas: list[Linha], i: int, fator_y: float = 3.5) -> list[int]:
    """Índices das linhas logo abaixo de `i` que dividem a mesma coluna, em ordem."""
    ref = linhas[i]
    alt = _escala(linhas, ref)
    achados = []
    for j, ln in enumerate(linhas):
        if j == i:
            continue
        dy = ln.y - ref.y
        if 0 < dy <= alt * fator_y and _sobrepoe_x(ref, ln, alt):
            achados.append((ln.y, j))
    return [j for _, j in sorted(achados)]


def contexto_de(linhas: list[Linha], i: int, fator_y: float = 3.5, fator_x: float = 8.0) -> str:
    """Texto das linhas relacionadas a `i`: mesma coluna acima/abaixo + vizinhas de lado."""
    ref = linhas[i]
    alt = _escala(linhas, ref)
    partes = [ref.norm]
    for j, ln in enumerate(linhas):
        if j == i:
            continue
        dy = abs(ln.y - ref.y)
        if dy <= alt * 0.6:
            # Mesma faixa: só conta se estiver ao lado, não numa coluna distante.
            folga = max(ref.x - _fim_x(ln), ln.x - _fim_x(ref), 0.0)
            if folga <= alt * fator_x:
                partes.append(ln.norm)
        elif dy <= alt * fator_y and _sobrepoe_x(ref, ln, alt):
            partes.append(ln.norm)
    return " ".join(partes)


# ------------------------------------------------------------ nomes próprios

_PARTICULAS = {"DE", "DA", "DO", "DAS", "DOS", "E", "DI", "DEL", "D"}
_RUIDO_NOME = {
    "NOME", "FILIACAO", "PAI", "MAE", "NATURALIDADE", "ASSINATURA", "DOCUMENTO", "IDENTIDADE",
    "REPUBLICA", "FEDERATIVA", "BRASIL", "MINISTERIO", "SECRETARIA", "ESTADO", "VALIDADE",
    "REGISTRO", "GERAL", "CARTEIRA", "TRABALHO", "PREVIDENCIA", "SOCIAL", "NACIONAL",
    "HABILITACAO", "CATEGORIA", "EMISSAO", "EXPEDICAO", "NASCIMENTO", "CPF", "RG", "PIS",
    "PASEP", "SERIE", "TITULAR", "PORTADOR", "SAUDE", "SISTEMA", "UNICO", "ELEITOR",
    "JUSTICA", "ELEITORAL", "TRIBUNAL", "SUPERIOR", "LOCAL", "DATA", "NUMERO", "SEGURANCA",
    "PUBLICA", "INSTITUTO", "IDENTIFICACAO", "OBSERVACOES", "PERMISSAO", "DIRIGIR", "SEXO",
    "ORGAO", "EMISSOR", "UF", "VIA", "FAZENDA", "RECEITA", "FEDERAL", "CADASTRO", "PESSOAS",
    "FISICAS", "FISICA", "INSCRICAO", "COMPROVANTE", "CERTIDAO", "CARTORIO", "MATRICULA",
}


def parece_nome(texto: str) -> bool:
    n = normalizar(texto)
    if not (6 <= len(n) <= 70):
        return False
    if not re.fullmatch(r"[A-Z' ]+", n):
        return False

    palavras = [p for p in n.split() if p]
    if len(palavras) < 2:
        return False

    # Descarta linhas que são, na verdade, rótulos do documento.
    ruidosas = sum(1 for p in palavras if p in _RUIDO_NOME)
    if ruidosas >= max(1, len(palavras) // 2):
        return False
    if palavras[0] in _RUIDO_NOME:
        return False

    substantivas = [p for p in palavras if p not in _PARTICULAS]
    if len(substantivas) < 2:
        return False
    return all(len(p) >= 2 for p in substantivas)


def limpar_nome(texto: str) -> str:
    n = re.sub(r"\s+", " ", (texto or "").strip().upper())
    return re.sub(r"[^A-ZÁÀÂÃÉÊÍÓÔÕÚÇ' ]", "", n).strip()


def _valor_apos_rotulo(linha_norm: str, linha_orig: str, rotulos: list[str]) -> str | None:
    """Se a linha começa com um rótulo, devolve o que vem depois dele."""
    for rot in rotulos:
        idx = linha_norm.find(rot)
        if idx == -1:
            continue
        if idx > 0 and linha_norm[idx - 1].isalpha():
            continue
        fim = idx + len(rot)
        if fim < len(linha_norm) and linha_norm[fim].isalpha():
            continue
        resto_norm = linha_norm[idx + len(rot):].lstrip(" :.-/")
        if not resto_norm:
            return ""  # rótulo isolado: o valor está na linha seguinte
        # Recorta a mesma quantidade de caracteres no texto original (com acento).
        corte = len(linha_orig) - len(resto_norm)
        candidato = linha_orig[corte:].lstrip(" :.-/") if 0 <= corte < len(linha_orig) else resto_norm
        return candidato.strip()
    return None


def buscar_nome(linhas: list[Linha], rotulos: list[str], usados: set[int]) -> tuple[str, float, str, int] | None:
    """Procura um nome logo após um rótulo (mesma linha ou linhas seguintes)."""
    for i, ln in enumerate(linhas):
        valor = _valor_apos_rotulo(ln.norm, ln.texto, rotulos)
        if valor is None:
            continue

        if valor and parece_nome(valor):
            if i not in usados:
                return limpar_nome(valor), ln.confianca, ln.texto, i

        # Rótulo isolado (ou valor inválido): olha logo abaixo, na mesma coluna.
        for j in indices_abaixo(linhas, i):
            if j in usados:
                continue
            if parece_nome(linhas[j].texto):
                return limpar_nome(linhas[j].texto), linhas[j].confianca, linhas[j].texto, j
    return None


def valor_por_rotulo(linhas: list[Linha], rotulos: list[str], padrao: str) -> tuple[str, Linha] | tuple[None, None]:
    """Acha um rótulo e devolve o 1º valor que casa `padrao` nele mesmo ou logo abaixo."""
    for i, ln in enumerate(linhas):
        if not any(r in ln.norm for r in rotulos):
            continue
        depois = _valor_apos_rotulo(ln.norm, ln.texto, rotulos)
        if depois:
            m = re.search(padrao, normalizar(depois))
            if m:
                return m.group(1), ln
        for j in indices_abaixo(linhas, i):
            m = re.search(padrao, linhas[j].norm)
            if m:
                return m.group(1), linhas[j]
    return None, None


# --------------------------------------------------------- números e datas

RE_CPF = re.compile(r"(?<!\d)(\d{3})[.\s]?(\d{3})[.\s]?(\d{3})[-.\s]?(\d{2})(?!\d)")
RE_CNPJ = re.compile(r"(?<!\d)(\d{2})[.\s]?(\d{3})[.\s]?(\d{3})[/\s]?(\d{4})[-.\s]?(\d{2})(?!\d)")
RE_PIS = re.compile(r"(?<!\d)(\d{3})[.\s]?(\d{5})[.\s]?(\d{2})[-.\s]?(\d)(?!\d)")
RE_11_DIGITOS = re.compile(r"(?<!\d)\d{11}(?!\d)")
# Título vem impresso em blocos ("1234 5678 0191"), então aceitamos separadores.
RE_TITULO = re.compile(r"(?<!\d)(\d{4})[.\s]?(\d{4})[.\s]?(\d{4})(?!\d)")
RE_CNS = re.compile(r"(?<!\d)(\d{3})[\s.]?(\d{4})[\s.]?(\d{4})[\s.]?(\d{4})(?!\d)")
# Além do formato oficial 12345-678, concessionárias imprimem 12.345-678.
# O valor é normalizado só com dígitos antes da validação.
RE_CEP = re.compile(r"(?<!\d)(?:\d{5}|\d{2}[.\s]\d{3})[-.\s]?\d{3}(?!\d)")
# O DV do RG só é aceito com separador explícito ("12.345.678-X"); sem isso o
# regex engolia a inicial da sigla do órgão emissor ("12.345.678 SSP/MG").
RE_RG = re.compile(r"(?<!\d)(\d[\d.\s]{4,16}\d)(?:\s*[-/]\s*([0-9Xx]))?(?![\d\-/])")
RE_DATA = re.compile(r"(?<!\d)(\d{1,2})[/\-. ](\d{1,2})[/\-. ](\d{2,4})(?!\d)")
RE_CATEGORIA_CNH = re.compile(r"\b(ACC|A|B|C|D|E|AB|AC|AD|AE)\b")


def _achar_com_correcao(regex: re.Pattern, texto: str, validador) -> list[tuple[str, str]]:
    """Casa o regex no texto e, se falhar, tenta de novo corrigindo letras→dígitos."""
    achados: list[tuple[str, str]] = []
    for m in regex.finditer(texto):
        bruto = m.group(0)
        d = V.only_digits(bruto)
        if validador(d):
            achados.append((d, bruto))
    if achados:
        return achados

    corrigido = texto.translate(_LETRA_PARA_DIGITO)
    for m in regex.finditer(corrigido):
        d = V.only_digits(m.group(0))
        if validador(d):
            achados.append((d, m.group(0)))
    return achados


def _contexto(linhas: list[Linha], agulha: str) -> tuple[float, str]:
    """Confiança e texto da linha onde o valor apareceu."""
    alvo = V.only_digits(agulha)
    for ln in linhas:
        if alvo and alvo in V.only_digits(ln.texto):
            return ln.confianca, ln.texto
        if alvo and alvo in V.only_digits(ln.texto.translate(_LETRA_PARA_DIGITO)):
            return ln.confianca, ln.texto
    return 0.0, ""


def _rotulo_proximo(linhas: list[Linha], valor: str, rotulos: list[str]) -> bool:
    """Verifica se algum rótulo aparece na linha do valor ou nas vizinhas geométricas."""
    alvo = V.only_digits(valor)
    for i, ln in enumerate(linhas):
        if alvo not in V.only_digits(ln.texto.translate(_LETRA_PARA_DIGITO)):
            continue
        contexto = contexto_de(linhas, i)
        return any(r in contexto for r in rotulos)
    return False


def _sem_marcador_de_campo(m: re.Match, origem: str) -> str:
    """Descarta o número do campo da CNH que veio grudado no valor.

    A CNH numera os campos no próprio impresso ("4a", "4b", "4c", "5", "9"), e o
    OCR devolve tudo numa linha só:

        "3935705 4c DOC IDENTIDADE SESP DF /ORG EMISSOR/UF"

    O RG ali é 3935705, mas a regex aceita espaço interno e levava o "4" do
    "4c" junto. O sinal de que aquele dígito é marcador, e não parte do número,
    é a letra colada logo depois dele.
    """
    bruto = m.group(0).strip()
    resto = origem[m.end():]
    letra_colada = bool(re.match(r"[a-zA-Z]", resto))
    if letra_colada:
        sem_ultimo = re.sub(r"[\s.]*\d\s*$", "", bruto).strip()
        # Só vale se ainda sobrar número suficiente para ser um RG.
        if len(V.only_digits(sem_ultimo)) >= 5:
            return sem_ultimo
    return bruto


def extrair_datas(linhas: list[Linha], texto_norm: str) -> dict[str, Campo]:
    """Associa cada data encontrada ao rótulo mais próximo."""
    rotulos_data = {
        "data_nascimento": (["DATA DE NASCIMENTO", "DATA NASCIMENTO", "NASCIMENTO", "DT NASC", "NASC"], "Data de nascimento"),
        "data_validade": (["VALIDADE", "VALIDO ATE", "VENCIMENTO"], "Validade"),
        "data_emissao": (["DATA DE EMISSAO", "EMISSAO", "DATA DE EXPEDICAO", "EXPEDICAO", "DATA DE INSCRICAO", "EMITIDO EM"], "Data de emissão"),
        "data_admissao": (["ADMISSAO", "DATA DE ADMISSAO"], "Data de admissão"),
        "data_primeira_habilitacao": (["1 HABILITACAO", "PRIMEIRA HABILITACAO", "1A HABILITACAO"], "1ª habilitação"),
    }

    # Cada data candidata vira (chave_do_rotulo, distancia, ...). A distancia é o
    # que resolve o caso da CNH, onde uma linha só carrega dois pares:
    #   "4a 27/12/2022 DATA EMISSAO 4b 10/08/2023 VALIDADE"
    # Casar por "existe o rótulo no contexto" pegava VALIDADE para a primeira
    # data e trocava emissão com validade. Aqui vence o rótulo mais perto, e
    # rótulo na mesma linha ganha de rótulo em linha vizinha.
    PESO_OUTRA_LINHA = 10_000

    candidatos: list[tuple[int, str, str, str, float, str]] = []

    for i, ln in enumerate(linhas):
        norm_linha = ln.norm
        contexto = None  # só calculado se precisar — é caro

        for m in RE_DATA.finditer(ln.texto):
            dia, mes, ano = m.groups()
            if len(ano) == 2:
                ano = ("19" + ano) if int(ano) > 30 else ("20" + ano)
            texto_data = f"{int(dia):02d}/{int(mes):02d}/{ano}"
            if not V.validar_data_generica(texto_data):
                continue

            for nome, (rots, rotulo) in rotulos_data.items():
                melhor = None

                # 1) rótulo na própria linha: distância em caracteres.
                for r in rots:
                    pos = norm_linha.find(r)
                    while pos != -1:
                        d = min(abs(pos - m.start()), abs(pos - m.end()))
                        melhor = d if melhor is None else min(melhor, d)
                        pos = norm_linha.find(r, pos + 1)

                # 2) só se não houver na linha, aceita o contexto ao redor.
                if melhor is None:
                    if contexto is None:
                        contexto = contexto_de(linhas, i)
                    if any(r in contexto for r in rots):
                        melhor = PESO_OUTRA_LINHA

                if melhor is not None:
                    candidatos.append((melhor, nome, rotulo, texto_data, ln.confianca, ln.texto))

    # Menor distância primeiro: cada data fica com o rótulo mais próximo, e cada
    # rótulo é preenchido uma vez só.
    campos: dict[str, Campo] = {}
    datas_usadas: set[str] = set()

    for _, nome, rotulo, texto_data, conf, origem in sorted(candidatos, key=lambda c: c[0]):
        if nome in campos or texto_data in datas_usadas:
            continue
        validador = V.VALIDADORES.get(nome, V.validar_data_generica)
        campos[nome] = Campo(
            nome=nome,
            rotulo=rotulo,
            valor=texto_data,
            valor_bruto=texto_data,
            confianca=conf,
            valido=validador(texto_data),
            origem=origem,
        )
        datas_usadas.add(texto_data)

    _conferir_coerencia_das_datas(campos)
    return campos


def _conferir_coerencia_das_datas(campos: dict[str, Campo]) -> None:
    """Uma data pode ser válida sozinha e impossível junto das outras.

    Uma CNH com validade anterior à emissão, ou emitida antes de o titular
    nascer, denuncia que os rótulos foram trocados na leitura. Sem esta
    conferência, os três campos saíam marcados como VÁLIDO.
    """
    from datetime import datetime

    def data(nome: str):
        campo = campos.get(nome)
        if campo is None:
            return None
        try:
            return datetime.strptime(campo.valor, "%d/%m/%Y")
        except ValueError:
            return None

    nasc, emis, val = data("data_nascimento"), data("data_emissao"), data("data_validade")

    def reprovar(nome: str, motivo: str) -> None:
        campo = campos.get(nome)
        if campo is None:
            return
        campos[nome] = replace(campo, valido=False, observacao=motivo)

    if emis and val and val < emis:
        reprovar("data_validade", "Validade anterior à emissão — datas provavelmente trocadas.")
        reprovar("data_emissao", "Emissão posterior à validade — datas provavelmente trocadas.")

    if nasc and emis and emis < nasc:
        reprovar("data_nascimento", "Nascimento posterior à emissão do documento.")
        reprovar("data_emissao", "Emissão anterior ao nascimento do titular.")

    if nasc and val and val < nasc:
        reprovar("data_validade", "Validade anterior ao nascimento do titular.")


# ------------------------------------------------------------ extração geral


def extrair_campos(linhas: list[Linha], tipo: str) -> list[Campo]:
    # Tipo não estruturado não ganha campos cadastrais por coincidência textual.
    # Um laudo pode trazer o CEP da clínica no rodapé, CPF do médico ou datas;
    # nenhum deles é automaticamente um dado do cliente. O texto integral segue
    # para classificação semântica depois do OCR.
    if tipo == "desconhecido":
        return []
    texto_bruto = "\n".join(ln.texto for ln in linhas)
    texto_norm = "\n".join(ln.norm for ln in linhas)
    campos: dict[str, Campo] = {}

    # --- CPF ---------------------------------------------------------------
    # Só na foto do cartão CPF / CNH / CIN. Em outros tipos o número pode
    # aparecer (médico, cônjuge, empregador) e NÃO deve virar o CPF do cliente.
    if tipo in TIPOS_COM_CPF:
        cpfs = _achar_com_correcao(RE_CPF, texto_bruto, V.validar_cpf)
        if not cpfs:
            cpfs = [(d, d) for d in RE_11_DIGITOS.findall(texto_bruto) if V.validar_cpf(d)]
        if cpfs:
            # Se houver mais de um, prefere o que tem o rótulo "CPF" por perto.
            escolhido = next((c for c in cpfs if _rotulo_proximo(linhas, c[0], ["CPF"])), cpfs[0])
            conf, origem = _contexto(linhas, escolhido[0])
            campos["cpf"] = Campo("cpf", "CPF", V.formatar_cpf(escolhido[0]), escolhido[1], conf, True,
                                  "Dígitos verificadores conferem.", origem)

    cpf_digitos = V.only_digits(campos["cpf"].valor) if "cpf" in campos else ""

    # --- CNH ---------------------------------------------------------------
    # Extraída antes do PIS: os dois têm 11 dígitos e um número pode passar nos
    # dois checksums, então o que já virou CNH não pode virar PIS também.
    cnh_digitos = ""
    if tipo == "cnh":
        candidatos_cnh = [d for d in RE_11_DIGITOS.findall(texto_bruto) if V.validar_cnh(d)]
        if not candidatos_cnh:
            corrigido = texto_bruto.translate(_LETRA_PARA_DIGITO)
            candidatos_cnh = [d for d in RE_11_DIGITOS.findall(corrigido) if V.validar_cnh(d)]

        # Nunca use o CPF impresso na CNH como nº de registro — o checksum do
        # Denatran às vezes passa em número que também é CPF válido.
        def _candidato_registro(c: str) -> bool:
            return c != cpf_digitos and not V.validar_cpf(c)

        rotulos_cnh = ["N REGISTRO", "N. REGISTRO", "REGISTRO", "RENACH"]
        cnh = next((c for c in candidatos_cnh
                    if _candidato_registro(c) and _rotulo_proximo(linhas, c, rotulos_cnh)), None)
        if cnh is None:
            cnh = next((c for c in candidatos_cnh if _candidato_registro(c)), None)
        if cnh:
            cnh_digitos = cnh
            conf, origem = _contexto(linhas, cnh)
            campos["cnh"] = Campo("cnh", "Nº de registro da CNH", cnh, cnh, conf, True,
                                  "Dígitos verificadores conferem (Denatran).", origem)

        valor, origem_ln = valor_por_rotulo(
            linhas, ["CAT. HAB", "CAT HAB", "CATEGORIA"], r"\b(ACC|[A-E]{1,2})\b")
        if valor:
            campos["categoria_cnh"] = Campo("categoria_cnh", "Categoria", valor, valor,
                                            origem_ln.confianca, True, origem=origem_ln.texto)

    # --- PIS/PASEP ---------------------------------------------------------
    candidatos_pis = [d for d in RE_11_DIGITOS.findall(texto_bruto) if V.validar_pis(d)]
    candidatos_pis += [V.only_digits(m.group(0)) for m in RE_PIS.finditer(texto_bruto)
                       if V.validar_pis(V.only_digits(m.group(0)))]
    if not candidatos_pis:
        corrigido = texto_bruto.translate(_LETRA_PARA_DIGITO)
        candidatos_pis = [d for d in RE_11_DIGITOS.findall(corrigido) if V.validar_pis(d)]

    ja_usados = {cpf_digitos, cnh_digitos} - {""}
    candidatos_pis = [p for p in candidatos_pis if p not in ja_usados]

    rotulos_pis = ["PIS", "PASEP", "NIT", "INSS"]
    pis = next((p for p in candidatos_pis if _rotulo_proximo(linhas, p, rotulos_pis)), None)
    if pis is None and tipo == "ctps":
        # Só na CTPS um 11 dígitos sem rótulo é presumido PIS — nos demais
        # documentos seria chute em cima de um número qualquer.
        pis = next((p for p in candidatos_pis if not V.validar_cpf(p)), None)
    if pis:
        conf, origem = _contexto(linhas, pis)
        campos["pis"] = Campo("pis", "PIS/PASEP/NIT", V.formatar_pis(pis), pis, conf, True,
                              "Dígito verificador confere.", origem)

    # --- Título de eleitor -------------------------------------------------
    if tipo == "titulo_eleitor" or "TITULO" in texto_norm or "ELEITOR" in texto_norm:
        candidatos = _achar_com_correcao(RE_TITULO, texto_bruto, V.validar_titulo_eleitor)
        if candidatos:
            numero, bruto = candidatos[0]
            conf, origem = _contexto(linhas, numero)
            campos["titulo_eleitor"] = Campo("titulo_eleitor", "Inscrição eleitoral", numero,
                                             bruto, conf, True, "Dígitos verificadores conferem.", origem)

        for chave, rot, rotulos in (("zona", "Zona eleitoral", ["ZONA"]),
                                    ("secao", "Seção eleitoral", ["SECAO"])):
            valor, linha_origem = valor_por_rotulo(linhas, rotulos, r"(?<!\d)(\d{1,4})(?!\d)")
            if valor:
                campos[chave] = Campo(chave, rot, valor, valor, linha_origem.confianca, True,
                                      origem=linha_origem.texto)

    # --- Cartão SUS (CNS) --------------------------------------------------
    if tipo == "cartao_sus" or "SAUDE" in texto_norm:
        for m in RE_CNS.finditer(texto_bruto):
            d = V.only_digits(m.group(0))
            if V.validar_cns(d):
                conf, origem = _contexto(linhas, d)
                campos["cns"] = Campo("cns", "Cartão Nacional de Saúde", V.formatar_cns(d), m.group(0),
                                      conf, True, "Dígito verificador confere.", origem)
                break

    # --- CNPJ (comprovantes) ----------------------------------------------
    cnpjs = _achar_com_correcao(RE_CNPJ, texto_bruto, V.validar_cnpj)
    if cnpjs:
        conf, origem = _contexto(linhas, cnpjs[0][0])
        campos["cnpj"] = Campo("cnpj", "CNPJ", V.formatar_cnpj(cnpjs[0][0]), cnpjs[0][1], conf, True,
                               "Dígitos verificadores conferem.", origem)

    # --- RG ----------------------------------------------------------------
    if tipo in ("rg", "cnh", "ctps", "cin", "desconhecido"):
        rotulos_rg = ["REGISTRO GERAL", "RG", "IDENTIDADE", "DOC. IDENTIDADE", "DOC IDENTIDADE", "CARTEIRA DE IDENTIDADE"]
        for i, ln in enumerate(linhas):
            if not any(r in ln.norm for r in rotulos_rg):
                continue
            alvo = ln.texto
            m = re.search(RE_RG, alvo)
            for j in ([] if m else indices_abaixo(linhas, i)):
                m = re.search(RE_RG, linhas[j].texto)
                if m:
                    alvo = linhas[j].texto
                    break
            if m:
                bruto = _sem_marcador_de_campo(m, alvo)
                d = V.only_digits(bruto)
                if V.validar_rg(d) and d != cpf_digitos and not V.validar_cpf(d):
                    campos["rg"] = Campo("rg", "RG / Registro Geral", bruto, bruto, ln.confianca, True,
                                         "RG não possui DV padronizado nacionalmente — validado apenas o formato.",
                                         alvo)
                    break

        m = re.search(r"\b(SSP|SESP|SDS|PC|IFP|IIRGD|DETRAN|MTE)[\s/\-]*([A-Z]{2})\b", texto_norm)
        if m:
            # A busca é no texto inteiro e perdia a linha de origem, então a
            # confiança saía 0.0 — e a tela ainda assim exibia "VÁLIDO", que é
            # afirmar certeza sobre uma leitura sem nenhuma. Recupera a linha.
            conf = next((ln.confianca for ln in linhas if m.group(0) in ln.norm), 0.0)
            campos["orgao_emissor"] = Campo("orgao_emissor", "Órgão emissor", f"{m.group(1)}/{m.group(2)}",
                                            m.group(0), conf, True if conf > 0 else None,
                                            "" if conf > 0 else "Não foi possível medir a confiança desta leitura.",
                                            origem=m.group(0))

    # --- CTPS --------------------------------------------------------------
    if tipo == "ctps":
        valor, origem_ln = valor_por_rotulo(
            linhas, ["N DA CARTEIRA", "N. DA CARTEIRA", "N CARTEIRA", "CTPS"], r"(?<!\d)(\d{5,8})(?!\d)")
        if valor:
            campos["numero_ctps"] = Campo("numero_ctps", "Nº da CTPS", valor, valor,
                                          origem_ln.confianca, True, origem=origem_ln.texto)

        valor, origem_ln = valor_por_rotulo(
            linhas, ["SERIE"], r"(?<!\d)(\d{3,5}(?:\s*[-/]\s*[A-Z]{2})?)")
        if valor:
            campos["serie_ctps"] = Campo("serie_ctps", "Série da CTPS", valor.replace(" ", ""), valor,
                                         origem_ln.confianca, True, origem=origem_ln.texto)

    # --- CEP e endereço ----------------------------------------------------
    for m in RE_CEP.finditer(texto_bruto):
        d = V.only_digits(m.group(0))
        if V.validar_cep(d) and (tipo == "comprovante_residencia" or "CEP" in texto_norm):
            conf, origem = _contexto(linhas, d)
            campos["cep"] = Campo("cep", "CEP", f"{d[:5]}-{d[5:]}", m.group(0), conf, True, origem=origem)
            break

    if tipo == "comprovante_residencia":
        # Contas de consumo quase sempre trazem um rótulo explícito. Ele é mais
        # confiável que tentar adivinhar o logradouro pela primeira palavra:
        # endereços reais aparecem como "R 26", "QD 12", "CJ A" e outras
        # abreviações que não começam literalmente por RUA/AVENIDA.
        for i, ln in enumerate(linhas):
            if not re.search(r"\bENDEREC(?:O|0)\b", ln.norm):
                continue

            apos_rotulo = re.sub(
                r"^.*?ENDERE[CÇ](?:O|0)\s*[:\-]?\s*",
                "",
                ln.texto,
                flags=re.IGNORECASE,
            ).strip()
            partes = [apos_rotulo] if apos_rotulo else []
            confiancas = [ln.confianca]
            # No retorno linear da Mistral as linhas mantêm a ordem de leitura.
            # O CEP encerra o bloco; se ele não vier, limitamos a três linhas
            # para não engolir REF./vencimento e o restante da fatura.
            for j in range(i + 1, min(len(linhas), i + 5)):
                candidata = linhas[j].texto.strip()
                norm_candidata = linhas[j].norm
                if not candidata:
                    continue
                if re.search(r"\b(CPF|CNPJ|CODIGO|INSTALACAO|REF|VENCIMENTO|TOTAL)\b", norm_candidata):
                    break
                partes.append(candidata)
                confiancas.append(linhas[j].confianca)
                if RE_CEP.search(candidata) or "CEP" in norm_candidata:
                    break

            trecho = " ".join(partes).strip()
            if trecho:
                campos["endereco"] = Campo(
                    "endereco", "Endereço", trecho, trecho,
                    min(confiancas), True,
                    "Endereço extraído a partir do rótulo da conta — confira manualmente.",
                    ln.texto,
                )
                break

    if tipo == "comprovante_residencia" and "endereco" not in campos:
        for i, ln in enumerate(linhas):
            if re.search(r"\b(RUA|R|AV|AVENIDA|TRAVESSA|ALAMEDA|PRACA|ROD|RODOVIA|ESTRADA|QUADRA|QD)\b", ln.norm):
                trecho = ln.texto.strip()
                # O CEP costuma vir na linha de baixo, na mesma coluna do logradouro.
                for j in indices_abaixo(linhas, i):
                    if RE_CEP.search(linhas[j].texto):
                        trecho += " " + linhas[j].texto.strip()
                        break
                campos["endereco"] = Campo("endereco", "Endereço", trecho, trecho, ln.confianca, True,
                                           "Endereço extraído por heurística — confira manualmente.", ln.texto)
                break

    # --- Nomes -------------------------------------------------------------
    usados: set[int] = set()

    achado = buscar_nome(linhas, ["NOME COMPLETO", "NOME SOCIAL", "NOME DO TITULAR", "NOME"], usados)
    if achado is None and tipo in TIPOS_COM_TITULAR:
        # Sem rótulo: usa a linha de maior altura que pareça um nome (nome vem em destaque).
        candidatas = [(i, ln) for i, ln in enumerate(linhas) if parece_nome(ln.texto)]
        if candidatas:
            i, ln = max(candidatas, key=lambda t: (t[1].altura, t[1].confianca))
            achado = (limpar_nome(ln.texto), ln.confianca, ln.texto, i)
    if achado:
        valor, conf, origem, idx = achado
        usados.add(idx)
        campos["nome"] = Campo("nome", "Nome completo", valor, origem, conf, True,
                               "Nome não possui validação formal — confira com o documento.", origem)

    achado_mae = achado_pai = None
    if tipo in TIPOS_COM_FILIACAO:
        achado_mae = buscar_nome(linhas, ["NOME DA MAE", "MAE"], usados)
        achado_pai = buscar_nome(linhas, ["NOME DO PAI", "PAI"], usados)

    # "FILIAÇÃO" é seguido por dois nomes, mas o documento não diz qual é qual e
    # a ordem varia entre emissores. Antes o primeiro virava "mãe" e o segundo
    # "pai" — numa CNH real isso saiu invertido, com nome masculino no campo da
    # mãe. Agora os dois viram "Filiação", numerados, com a ressalva de que o
    # papel não foi identificado. Melhor um rótulo neutro que um fato errado.
    filiacao: list[tuple[str, float, str, int]] = []
    if tipo in TIPOS_COM_FILIACAO and achado_mae is None and achado_pai is None:
        for i, ln in enumerate(linhas):
            if "FILIACAO" not in ln.norm:
                continue
            seguintes = [(j, linhas[j]) for j in indices_abaixo(linhas, i, fator_y=4.5)
                         if j not in usados and parece_nome(linhas[j].texto)]
            for j, l in seguintes[:2]:
                filiacao.append((limpar_nome(l.texto), l.confianca, l.texto, j))
            break

    for n, (valor, conf, origem, idx) in enumerate(filiacao, start=1):
        if idx in usados:
            continue
        usados.add(idx)
        campos[f"filiacao_{n}"] = Campo(
            f"filiacao_{n}", f"Filiação {n}", valor, origem, conf, None,
            "O documento não identifica se é mãe ou pai — confira antes de usar.",
            origem,
        )

    for chave, rot, achado_f in (("nome_mae", "Nome da mãe", achado_mae), ("nome_pai", "Nome do pai", achado_pai)):
        if achado_f:
            valor, conf, origem, idx = achado_f
            if idx in usados:
                continue
            usados.add(idx)
            campos[chave] = Campo(chave, rot, valor, origem, conf, True, origem=origem)

    # --- Naturalidade / sexo ----------------------------------------------
    for i, ln in enumerate(linhas):
        if "NATURALIDADE" in ln.norm:
            valor = _valor_apos_rotulo(ln.norm, ln.texto, ["NATURALIDADE"]) or ""
            if not valor:
                abaixo = indices_abaixo(linhas, i)
                valor = linhas[abaixo[0]].texto if abaixo else ""
            valor = valor.strip()
            if valor:
                campos["naturalidade"] = Campo("naturalidade", "Naturalidade", valor, valor, ln.confianca, True,
                                               origem=ln.texto)
            break

    valor, origem_ln = valor_por_rotulo(linhas, ["SEXO"], r"\b([MF])\b")
    if valor:
        campos["sexo"] = Campo("sexo", "Sexo", valor, valor, origem_ln.confianca, True,
                               origem=origem_ln.texto)

    # --- Datas -------------------------------------------------------------
    campos.update({k: v for k, v in extrair_datas(linhas, texto_norm).items() if k not in campos})

    ordem = ["nome", "cpf", "rg", "orgao_emissor", "cnh", "categoria_cnh", "pis", "numero_ctps", "serie_ctps",
             "titulo_eleitor", "zona", "secao", "cns", "cnpj", "data_nascimento", "data_emissao",
             "data_validade", "data_admissao", "data_primeira_habilitacao", "nome_mae", "nome_pai",
             "filiacao_1", "filiacao_2",
             "naturalidade", "sexo", "endereco", "cep"]
    return [campos[k] for k in ordem if k in campos] + [v for k, v in campos.items() if k not in ordem]
