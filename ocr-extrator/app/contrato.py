"""Gera o contrato de honorários a partir do modelo do escritório.

O modelo é o .docx oficial (`docs/CONTRATO oficial.docx`), com o timbre, as
cláusulas, os percentuais e as inscrições na OAB já escritos. Aqui só se
preenchem os campos entre colchetes com o que a entrevista respondeu:

    [nome da pessoa], [nacionalidade], [estado civil], [profissão], inscrito(a)
    no CPF sob o nº [CPF], portador(a) do RG nº [RG – número], ...

POR QUE NÃO SE GERA O DOCUMENTO DO ZERO

Um contrato de honorários é peça jurídica: percentual, foro eleito, cláusula de
rescisão e as OAB do sócio têm efeito legal. Reescrever esse texto — ainda que
com um modelo de linguagem — é assumir responsabilidade por redação que o
escritório revisou e adotou. O programa preenche lacunas; ele não redige
cláusula, não reordena, não resume. O que sai é o modelo, palavra por palavra,
com os dados do cliente nos lugares marcados.

COMO O PREENCHIMENTO PRESERVA A FORMATAÇÃO

Um .docx é um zip com XML dentro. O texto de um parágrafo vive espalhado em
vários `<w:t>`, e o Word os reparte por qualquer motivo — uma correção
ortográfica no meio de "[CPF]" basta para virar "[CP" + "F]". Por isso a troca é
feita por intervalo de caracteres sobre o parágrafo inteiro, e não por
`str.replace` em cada nó: acha-se o marcador no texto concatenado e reescrevem-se
só os nós que ele atravessa. O resto do parágrafo — negrito, fonte, tabulação —
não é tocado.

CAMPO SEM RESPOSTA CONTINUA APARECENDO

Se a entrevista não trouxe o e-mail, o contrato sai com `[e-mail]` à vista. É
proposital: um espaço em branco no meio da qualificação passa despercebido na
revisão e vira contrato assinado com dado faltando. O colchete não passa.
"""

from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from datetime import date
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from . import validators

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

BASE = Path(__file__).resolve().parent.parent
DIR_DOCS = BASE / "docs"

MESES = (
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
)


class ErroContrato(Exception):
    """Falha que o usuário precisa ver — modelo ausente ou ilegível."""


class DadosObrigatoriosContrato(ErroContrato):
    """O contrato foi bloqueado antes de ser criado por falta de identificação."""


def _nome_completo(nome: str) -> bool:
    """Exige prenome e sobrenome escritos, não apenas iniciais ou partículas."""
    partes = " ".join(nome.split()).split(" ")
    permitidos = {"'", "’", "-", "."}
    if not all(
        any(caractere.isalpha() for caractere in parte)
        and all(caractere.isalpha() or caractere in permitidos for caractere in parte)
        for parte in partes
    ):
        return False

    particulas = {"da", "das", "de", "do", "dos", "e"}
    substantivas = [parte for parte in partes if parte.casefold().rstrip(".") not in particulas]
    return len(substantivas) >= 2 and all(
        sum(caractere.isalpha() for caractere in parte) >= 2 for parte in substantivas
    )


def _normalizar_identificacao(nome: object, cpf: object) -> tuple[str, str]:
    nome_limpo = " ".join(nome.split()) if isinstance(nome, str) else ""
    cpf_texto = unicodedata.normalize("NFKC", cpf.strip()) if isinstance(cpf, str) else ""
    cpf_permitido = bool(re.fullmatch(r"[0-9.\-\s]+", cpf_texto))
    cpf_limpo = re.sub(r"[^0-9]", "", cpf_texto) if cpf_permitido else ""

    problemas: list[str] = []
    if not _nome_completo(nome_limpo):
        problemas.append("o nome completo do cliente")
    if not cpf_permitido or not validators.validar_cpf(cpf_limpo):
        problemas.append("um CPF válido")

    if problemas:
        exigencias = " e ".join(problemas)
        raise DadosObrigatoriosContrato(f"Contrato não gerado: informe {exigencias}.")

    return nome_limpo, validators.formatar_cpf(cpf_limpo)


def normalizar_respostas(respostas: dict[str, Any]) -> dict[str, Any]:
    """Copia as respostas e uniformiza a identificação usada em todo o fluxo."""
    nome, cpf = _normalizar_identificacao(respostas.get("nome"), respostas.get("cpf"))
    resultado = dict(respostas)
    resultado["nome"] = nome
    resultado["cpf"] = cpf
    return resultado


def _validar_e_normalizar_obrigatorios(valores: dict[str, Any]) -> dict[str, str]:
    """Valida os dois dados sem os quais nenhum contrato pode ser produzido.

    Esta barreira mora abaixo das rotas e dos serviços de assinatura de propósito:
    até uma chamada direta a :func:`preencher` precisa respeitá-la.
    """
    originais = {_chave(f"[{k}]"): v for k, v in valores.items()}
    nome, cpf = _normalizar_identificacao(
        originais.get("nome da pessoa"), originais.get("cpf")
    )
    normalizados = {k: str(v or "").strip() for k, v in originais.items()}

    normalizados["nome da pessoa"] = nome
    normalizados["cpf"] = cpf
    # Os modelos repetem o nome no bloco de assinatura, cada um com o seu
    # rótulo: contratante no contrato, outorgante na procuração, declarante na
    # declaração. Todos recebem o nome JÁ VALIDADO — se um deles ficasse com a
    # cópia crua, o mesmo documento sairia com duas grafias do mesmo cliente.
    for apelido in _APELIDOS_DO_NOME:
        if apelido in normalizados:
            normalizados[apelido] = nome
    return normalizados


#: Como cada modelo chama o cliente. Ver `_validar_e_normalizar_obrigatorios`.
_APELIDOS_DO_NOME = (
    "nome completo",
    "nome do contratante",
    "nome do outorgante",
    "nome do declarante",
)


# ------------------------------------------------------------------ modelo


#: Os documentos que o cliente assina, na ordem em que o escritório os junta.
#:
#: São TRÊS e não um: sem procuração o advogado não peticiona, e sem declaração
#: de hipossuficiência não há gratuidade de justiça. Gerar só o contrato deixava
#: o atendimento pela metade — a papelada seguia sendo montada à mão depois,
#: fora do sistema, que é onde ela se perde.
#:
#: `prefixo` é comparado sem acento e sem caixa contra o nome do arquivo em
#: `docs/`: o escritório versiona pelo próprio nome ("CONTRATO oficial.docx") e
#: renomeia sem avisar ninguém.
MODELOS: tuple[dict[str, str], ...] = (
    {
        "codigo": "contrato",
        "rotulo": "Contrato de honorários",
        "prefixo": "contrato",
        "arquivo": "Contrato",
    },
    {
        "codigo": "procuracao",
        "rotulo": "Procuração ad judicia",
        "prefixo": "procuracao",
        "arquivo": "Procuração",
    },
    {
        "codigo": "hipossuficiencia",
        "rotulo": "Declaração de hipossuficiência",
        "prefixo": "declaracao",
        "arquivo": "Declaração de hipossuficiência",
    },
)

CODIGOS = tuple(m["codigo"] for m in MODELOS)


def modelo(codigo: str) -> dict[str, str]:
    for m in MODELOS:
        if m["codigo"] == codigo:
            return m
    raise ErroContrato(f"Documento {codigo!r} não existe. Conhecidos: {', '.join(CODIGOS)}.")


def _sem_acento(texto: str) -> str:
    sem = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in sem if not unicodedata.combining(c)).casefold()


def caminho_modelo(codigo: str = "contrato") -> Path:
    """O .docx oficial. Trocar de versão é soltar o arquivo novo em `docs/`.

    O nome não é fixo de propósito: o escritório versiona pela data no próprio
    nome do arquivo, como já faz com os checklists. A comparação ignora acento e
    caixa porque "Procuração.docx" e "PROCURACAO.docx" são o mesmo documento
    para quem salvou, e um `glob` literal acharia só um dos dois.
    """
    alvo = modelo(codigo)
    candidatos = [
        p
        for p in DIR_DOCS.glob("*.docx")
        if _sem_acento(p.name).startswith(alvo["prefixo"])
    ]
    if not candidatos:
        raise ErroContrato(
            f"Modelo de {alvo['rotulo'].lower()} não encontrado em docs/ "
            f"(esperado um arquivo começando por {alvo['prefixo'].upper()})."
        )
    # O mais recente vence, para a versão nova entrar sem mexer no código.
    return max(candidatos, key=lambda p: p.stat().st_mtime)


# -------------------------------------------------------------- marcadores


def _chave(marcador: str) -> str:
    """Normaliza "[RG – órgão + UF]" em "rg orgao uf".

    Assim o preenchimento sobrevive ao modelo ser reeditado no Word, que troca
    hífen por travessão, duplica espaço e alterna maiúsculas sem avisar.
    """
    s = marcador.strip("[]").strip().lower()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


_MARCADOR = re.compile(r"\[[^\[\]\n]{1,60}\]")

#: Rótulos que o modelo deixa em branco para completar à mão, sem colchete.
#:
#: No bloco de assinatura o cliente aparece como "[Nome do Contratante]" seguido
#: de "CPF:" — o nome tem marcador, o CPF não. Preenchendo só os colchetes, o
#: contrato sai com o CPF na qualificação e um "CPF:" vazio embaixo da linha de
#: assinatura, que é justamente onde o cartório e a parte contrária olham.
#:
#: A expressão exige que o rótulo esteja no FIM do parágrafo (aceitando um
#: tracejado de preenchimento). É o que o separa do "inscrito(a) no CPF sob o nº"
#: da qualificação, que não leva dois-pontos e não termina o parágrafo.
ROTULOS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"CPF:\s*_*\s*$"), "CPF"),
)


def _definir_texto(no: ET.Element, texto: str) -> None:
    no.text = texto
    # Sem isto o Word come espaço no começo e no fim do nó, e a qualificação
    # sai com as palavras grudadas.
    no.set(XML_SPACE, "preserve")


def _reescrever(nos: list[ET.Element], partes: list[str], ini: int, fim: int, valor: str) -> None:
    """Substitui o intervalo [ini, fim) do texto do parágrafo por `valor`.

    Os deslocamentos são sobre o texto CONCATENADO; aqui eles voltam a ser
    posições dentro de cada nó, e só os nós atravessados pelo intervalo são
    tocados. É isso que preserva negrito, fonte e tabulação em volta.
    """
    primeiro = ultimo = 0
    desloc_ini = desloc_fim = 0
    acumulado = 0
    for i, parte in enumerate(partes):
        comeco, termino = acumulado, acumulado + len(parte)
        if comeco <= ini < termino:
            primeiro, desloc_ini = i, ini - comeco
        if comeco < fim <= termino:
            ultimo, desloc_fim = i, fim - comeco
        acumulado = termino

    if primeiro == ultimo:
        _definir_texto(
            nos[primeiro], partes[primeiro][:desloc_ini] + valor + partes[primeiro][desloc_fim:]
        )
        return

    # O valor herda a formatação do nó onde o trecho COMEÇA — que é a do próprio
    # marcador, e portanto a que o escritório desenhou.
    _definir_texto(nos[primeiro], partes[primeiro][:desloc_ini] + valor)
    for k in range(primeiro + 1, ultimo):
        _definir_texto(nos[k], "")
    _definir_texto(nos[ultimo], partes[ultimo][desloc_fim:])


def _preencher_paragrafo(nos: list[ET.Element], valores: dict[str, str]) -> tuple[int, set[str]]:
    """Troca os marcadores de um parágrafo. Devolve (trocas, não preenchidos)."""
    trocas = 0
    faltando: set[str] = set()
    inteiro_original = "".join(n.text or "" for n in nos)

    # Da direita para a esquerda, as posições originais dos marcadores que ainda
    # faltam continuam válidas. Cada lacuna é visitada uma vez: se um usuário
    # digitou literalmente "[e-mail]", esse texto vira valor, não um novo marcador
    # a ser processado para sempre.
    for marcador in reversed(list(_MARCADOR.finditer(inteiro_original))):
        chave = _chave(marcador.group(0))
        valor = valores.get(chave, "").strip()
        if not valor:
            if chave:
                faltando.add(chave)
            continue
        partes = [n.text or "" for n in nos]
        _reescrever(nos, partes, marcador.start(), marcador.end(), valor)
        trocas += 1

    trocas += _preencher_rotulos(nos, valores)
    return trocas, faltando


def _preencher_rotulos(nos: list[ET.Element], valores: dict[str, str]) -> int:
    """Completa rótulo sem colchete — hoje, o "CPF:" da linha de assinatura."""
    trocas = 0
    for expressao, campo in ROTULOS:
        valor = valores.get(_chave(f"[{campo}]"), "").strip()
        if not valor:
            continue
        partes = [n.text or "" for n in nos]
        m = expressao.search("".join(partes))
        if m is None:
            continue
        _reescrever(nos, partes, m.start(), m.end(), f"{campo}: {valor}")
        trocas += 1
    return trocas


#: Cabeçalho que o Word espera. O `standalone="yes"` e o CRLF são os que ele
#: próprio escreve; o ElementTree não sabe emitir nenhum dos dois.
DECLARACAO = b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'


def _registrar_prefixos(xml: bytes) -> None:
    """Mantém os prefixos originais (w, mc, wp14…) na hora de reserializar.

    Sem isto o ElementTree renomeia tudo para ns0, ns1, ns2 — e aí o atributo
    `mc:Ignorable="w14 wp14"`, que cita prefixos pelo NOME, passa a apontar para
    prefixos que não existem mais. O arquivo continua sendo XML válido, mas o
    Word o recusa como corrompido, e a mensagem não diz por quê.
    """
    for _, (prefixo, uri) in ET.iterparse(io.BytesIO(xml), events=["start-ns"]):
        ET.register_namespace(prefixo, uri)


def _serializar(raiz: ET.Element) -> bytes:
    return DECLARACAO + ET.tostring(raiz, encoding="utf-8", xml_declaration=False)


def _partes_com_texto(zf: zipfile.ZipFile) -> list[str]:
    """Documento, cabeçalhos e rodapés — o timbre também tem marcador."""
    return [
        n
        for n in zf.namelist()
        if re.fullmatch(r"word/(document|header\d*|footer\d*)\.xml", n)
    ]


def preencher(valores: dict[str, Any], modelo: Path | None = None) -> tuple[bytes, list[str]]:
    """Devolve o DOCX preenchido, somente com nome completo e CPF válido."""
    normalizados = _validar_e_normalizar_obrigatorios(valores)
    caminho = modelo or caminho_modelo()
    try:
        origem = zipfile.ZipFile(caminho)
    except Exception as exc:
        raise ErroContrato(f"Não foi possível abrir o modelo: {exc}") from exc

    faltando: set[str] = set()

    with origem:
        editados: dict[str, bytes] = {}
        for nome in _partes_com_texto(origem):
            bruto = origem.read(nome)
            _registrar_prefixos(bruto)
            raiz = ET.fromstring(bruto)
            mudou = 0
            # `iter` alcança também os parágrafos dentro de caixas de texto, que
            # é onde mora o cabeçalho deste modelo — um percurso só pelos filhos
            # diretos deixaria o nome do contratante sem preencher.
            for paragrafo in raiz.iter(W + "p"):
                nos = paragrafo.findall(f".//{W}t")
                if not nos:
                    continue
                trocas, ausentes = _preencher_paragrafo(nos, normalizados)
                mudou += trocas
                faltando |= ausentes
            if mudou:
                editados[nome] = _serializar(raiz)

        destino = io.BytesIO()
        # Reescreve o zip inteiro preservando o que não foi tocado: estilos,
        # fontes embutidas, imagens do timbre.
        with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as saida:
            for item in origem.infolist():
                saida.writestr(item, editados.get(item.filename) or origem.read(item.filename))

    return destino.getvalue(), sorted(faltando)


def marcadores_do_modelo(modelo: Path | None = None) -> list[str]:
    """Todos os campos que o modelo pede. Serve para conferir o mapeamento."""
    caminho = modelo or caminho_modelo()
    achados: set[str] = set()
    with zipfile.ZipFile(caminho) as zf:
        for nome in _partes_com_texto(zf):
            raiz = ET.fromstring(zf.read(nome))
            for paragrafo in raiz.iter(W + "p"):
                texto = "".join(t.text or "" for t in paragrafo.iter(W + "t"))
                achados.update(_chave(m.group(0)) for m in _MARCADOR.finditer(texto))
    return sorted(c for c in achados if c)


# ------------------------------------------------- entrevista -> contrato


def _partir_rg(bruto: str) -> tuple[str, str]:
    """Separa "1234567 SSP/PA" em número e órgão expedidor.

    Rede de segurança para quando o número vier com o órgão colado no mesmo
    campo — o roteiro pergunta as duas coisas separadas, mas nada impede alguém
    de digitar tudo junto. Não dando para separar com segurança, o número leva
    tudo e o órgão fica em branco: melhor o colchete aparecendo no contrato do
    que um órgão expedidor deduzido de um palpite de regex.
    """
    texto = (bruto or "").strip()
    if not texto:
        return "", ""
    m = re.match(r"^\s*([\d][\d.\-\s]*[\dxX]?)\s*(.*)$", texto)
    if not m:
        return texto, ""
    numero = m.group(1).strip(" -")
    resto = m.group(2).strip(" -–,")
    return numero, resto


def _municipio_do_endereco(endereco: str) -> str:
    """Tira "Belém/PA" de um endereço completo — é onde o contrato é assinado.

    Casa com o formato que a consulta de CEP monta (ver `consultas.py`). Não
    achando, devolve vazio e o campo fica visível para preencher à mão.
    """
    m = re.search(r"([A-Za-zÀ-ÿ'.\s]{2,40})/([A-Z]{2})\b", endereco or "")
    return f"{m.group(1).strip()}/{m.group(2)}" if m else ""


def por_extenso(dia: date) -> str:
    return f"{dia.day} de {MESES[dia.month - 1]} de {dia.year}"


def valores_da_entrevista(
    respostas: dict[str, Any], municipio: str = "", quando: date | None = None
) -> dict[str, str]:
    """Traduz as respostas do roteiro para os campos do modelo."""
    def r(chave: str) -> str:
        valor = respostas.get(chave, "")
        if isinstance(valor, list):
            valor = ", ".join(str(v) for v in valor)
        return str(valor or "").strip()

    endereco = r("endereco")

    # O roteiro pergunta número, órgão e UF em campos próprios. Se o órgão vier
    # vazio, ainda se tenta separar do número — entrevista feita às pressas põe
    # "1234567 SSP/PA" tudo na primeira caixa.
    numero_rg = r("rg")
    orgao_rg = "/".join(p for p in (r("rg_orgao"), r("rg_uf")) if p)
    if not orgao_rg:
        numero_rg, orgao_rg = _partir_rg(numero_rg)

    return {
        "nome da pessoa": r("nome"),
        # Os três modelos pedem o mesmo dado com nomes diferentes. Um dicionário
        # só serve aos três: `preencher` troca o que encontra e ignora o resto,
        # então a chave que sobra não custa nada — e evita três mapeamentos para
        # manter em dia quando a entrevista mudar de campo.
        "nome completo": r("nome"),
        "nome do outorgante": r("nome"),
        "nome do declarante": r("nome"),
        # A procuração e a declaração pedem o RG num campo só; o contrato o
        # separa em número e órgão. Vão os dois formatos.
        "rg": numero_rg,
        "órgão/UF": orgao_rg,
        "nacionalidade": r("nacionalidade"),
        # O roteiro oferece "Casado(a)" com maiúscula, que é como se lê num
        # botão; no meio da qualificação ("brasileira, casado(a), carteira") a
        # maiúscula destoa. A forma "(a)" fica: é a mesma do modelo, que já
        # escreve "inscrito(a)" e "residente e domiciliado(a)" — e não temos o
        # gênero do cliente para flexionar sem chutar.
        "estado civil": r("estado_civil").lower(),
        "profissão": r("profissao"),
        "CPF": r("cpf"),
        "RG – número": numero_rg,
        "RG – órgão + UF": orgao_rg,
        "endereço completo": endereco,
        "telefone": r("telefone"),
        "e-mail": r("email"),
        "Município": municipio.strip() or _municipio_do_endereco(endereco),
        "data": por_extenso(quando or date.today()),
        "Nome do Contratante": r("nome"),
    }


def gerar(
    respostas: dict[str, Any],
    municipio: str = "",
    quando: date | None = None,
    codigo: str = "contrato",
) -> tuple[bytes, list[str]]:
    respostas_normalizadas = normalizar_respostas(respostas)
    return preencher(
        valores_da_entrevista(respostas_normalizadas, municipio, quando),
        caminho_modelo(codigo),
    )


def gerar_todos(
    respostas: dict[str, Any], municipio: str = "", quando: date | None = None
) -> list[dict[str, Any]]:
    """Os três documentos que o cliente assina, do mesmo conjunto de respostas.

    Sai tudo de uma vez porque é assim que o escritório usa: contrato,
    procuração e declaração de hipossuficiência formam UMA papelada, assinada na
    mesma sessão. Gerar um de cada vez convidava a esquecer os outros dois — e
    sem procuração não se peticiona.

    Cada item traz o seu `faltando`: o que a entrevista não respondeu continua
    entre colchetes no documento, e a lista é diferente por modelo (o contrato
    pede telefone e e-mail; a procuração, não).
    """
    respostas_normalizadas = normalizar_respostas(respostas)
    valores = valores_da_entrevista(respostas_normalizadas, municipio, quando)

    documentos: list[dict[str, Any]] = []
    for alvo in MODELOS:
        docx, faltando = preencher(valores, caminho_modelo(alvo["codigo"]))
        documentos.append(
            {
                "codigo": alvo["codigo"],
                "rotulo": alvo["rotulo"],
                "arquivo": alvo["arquivo"],
                "docx": docx,
                "faltando": faltando,
            }
        )
    return documentos
