"""Pasta para protocolo: a petição em PDF e os documentos do caso, do jeito que vão ao tribunal.

Segue `references/padrao_documentos_protocolo.md` da skill do escritório e a pasta
que o escritório monta à mão:

    Protocolo (Reclamação Trabalhista - Assalto Em Serviço) Nome Do Cliente/
        Petição Inicial.pdf
        Planilha De Cálculo.pdf / .PJC        (se estiverem entre os arquivos do caso)
        Doc 1. CNH.pdf, Doc 2. ...            (um PDF por documento)
        Lista De Documentação Para Protocolo.pdf
        Checklist.pdf

A numeração "Doc N." é a do `document_ledger`, a MESMA que a petição cita como
"Documento NN": renumerar aqui faria a peça apontar para o arquivo errado. Cópias
e documentos internos (checklist, entrevista, contrato de honorários) não entram
e aparecem em "Não juntados" na lista.
"""

from __future__ import annotations

import io
import logging
import re
import tempfile
import uuid
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import armazenamento, casos, conversao_pdf, organizacao_documental, peticao_local

log = logging.getLogger("pacote_protocolo")

ESCRITORIO = "Lara & Melo Advogados Associados"
_PROIBIDOS = str.maketrans({c: "-" for c in '\\/:*?"<>|'})
_PLANILHA = re.compile(r"\.pjc$|planilha|c[aá]lculo|pje-?calc", re.IGNORECASE)
_PREFIXO_DOC = re.compile(r"^\s*doc(?:umento)?\s*0*\d{1,3}\s*[.\-–—]?\s*", re.IGNORECASE)
_COPIA = re.compile(r"\((?:duplicad[oa]|c[óo]pia)[^)]*\)", re.IGNORECASE)
#: Palavras de nome de arquivo gerado por câmera, scanner ou WhatsApp: sozinhas não dizem o que é o documento.
_SEM_SIGNIFICADO = re.compile(
    r"\b(img|dsc|pxl|scan|scanner|whatsapp|image|imagem|foto|photo|screenshot|captura|de|tela|at|"
    r"documento|arquivo|file|pdf|jpe?g|png|copy|copia)\b|[\d_\-.\s()]+",
    re.IGNORECASE,
)


class ErroPacote(ValueError):
    """O pacote não pode ser montado (caso ou petição inexistente, PDF da petição indisponível)."""


@dataclass
class Pacote:
    #: ZIP temporário; quem serve o arquivo apaga depois.
    caminho: Path
    nome: str
    arquivos: int
    #: Documentos citáveis que não puderam entrar no pacote.
    faltando: list[str]


@dataclass
class _Item:
    nome: str
    conteudo: bytes
    descricao: str
    paginas: int | None


def _texto_da_peticao(dados: dict[str, Any]) -> str:
    texto = "\n".join(str(s.get("content") or "") for s in dados.get("sections") or [])
    return texto.replace("**", "").replace("__", "")


def _valor_da_causa(texto: str) -> str:
    achado = re.search(r"valor\s+da\s+causa.{0,160}?(R\$\s*[\d.]+,\d{2})", texto, re.IGNORECASE | re.DOTALL)
    return re.sub(r"\s+", " ", achado.group(1)) if achado else ""


def _reclamada(texto: str) -> str:
    achado = re.search(r"em\s+face\s+d[aeo]s?\s+([^,;\n]{4,140})", texto, re.IGNORECASE)
    return achado.group(1).strip(" .") if achado else ""


def _tipo_da_acao(caso: dict[str, Any], categoria: str, normalizar: Callable[[str], str]) -> str:
    tipo = str(caso.get("tipo_acao") or "").strip() or categoria.strip()
    previdenciaria = re.search(r"previd|inss|benef[ií]cio", f"{tipo} {caso.get('categoria') or ''}", re.IGNORECASE)
    base = "Ação Previdenciária" if previdenciaria else "Reclamação Trabalhista"
    if not tipo:
        return base
    if re.match(r"(reclama[çc][ãa]o|a[çc][ãa]o)\b", tipo, re.IGNORECASE):
        return normalizar(tipo)
    return normalizar(f"{base} - {tipo}")


def _paginas(conteudo: bytes) -> int | None:
    if conteudo[:4] != b"%PDF":
        return None
    try:
        import pypdfium2 as pdfium

        return len(pdfium.PdfDocument(conteudo))
    except Exception:  # noqa: BLE001 - só enfeita a lista; PDF ilegível continua no pacote
        return None


def _nome_do_documento(doc: dict[str, Any], entrega: dict[str, Any], normalizar: Callable[[str], str]) -> str:
    """'Doc 3. Procuração.pdf' → 'Procuração'; 'IMG_2031.jpg' → o tipo que a análise identificou."""
    nome = _COPIA.sub("", _PREFIXO_DOC.sub("", Path(doc["canonical_file"]).stem)).replace("_", " ").strip(" .-")
    if not _SEM_SIGNIFICADO.sub("", nome).strip():
        nome = (
            str(doc.get("document_type") or "").strip()
            or str(entrega.get("identificacao_ia") or "").strip()[:60]
            or str(entrega.get("tipo_detectado") or "").replace("_", " ").strip()
            or "Documento"
        )
    return normalizar(nome)


def _arquivo_da_entrega(entrega: dict[str, Any], trabalho: Path) -> tuple[bytes, str]:
    """(bytes, extensão) — em PDF sempre que o formato permitir."""
    nome = str(entrega.get("arquivo") or "documento")
    caminho = armazenamento.caminho_duravel_da_entrega(str(entrega["id"]))
    if not caminho or not caminho.exists():
        conteudo = armazenamento.conteudo_arquivo_entrega(armazenamento.obter_entrega(str(entrega["id"])) or {})
        if conteudo is None:
            raise FileNotFoundError(nome)
        caminho = trabalho / f"{uuid.uuid4().hex}{Path(nome).suffix.lower()}"
        caminho.write_bytes(conteudo)
    try:
        convertido = conversao_pdf.converter_para_pdf(caminho, nome, trabalho / f"{uuid.uuid4().hex}.pdf")
        return convertido.caminho.read_bytes(), ".pdf"
    except conversao_pdf.ErroConversaoPdf:
        return caminho.read_bytes(), (caminho.suffix or Path(nome).suffix).lower()


def _descricao_de(item: Any) -> str:
    if isinstance(item, dict):
        for chave in ("descricao", "texto", "pendencia", "item", "mensagem"):
            if item.get(chave):
                return str(item[chave])
        return ""
    return str(item or "")


def _pendencias_da_peticao(dados: dict[str, Any]) -> list[str]:
    prontidao = dados.get("readiness") or {}
    brutas = [
        *(prontidao.get("blocking_issues") or []),
        *(prontidao.get("pendencias") or []),
        *((dados.get("relatorio_advogado") or {}).get("pendencias") or []),
    ]
    vistas: list[str] = []
    for bruta in brutas:
        texto = " ".join(_descricao_de(bruta).split())[:300]
        if texto and texto not in vistas:
            vistas.append(texto)
    return vistas[:20]


# ------------------------------------------------------------------ PDFs de conferência


def _pdf_de_conferencia(titulo: str, cabecalho: list[str], corpo: Callable[[Any, Any], list[Any]]) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    estilos = getSampleStyleSheet()
    saida = io.BytesIO()
    blocos: list[Any] = [Paragraph(titulo, estilos["Title"])]
    blocos += [Paragraph(_escapar(linha), estilos["Normal"]) for linha in cabecalho]
    blocos.append(Spacer(1, 0.4 * cm))
    blocos += corpo(estilos, cm)
    blocos += [Spacer(1, 0.6 * cm), Paragraph(f"<i>{_escapar(ESCRITORIO)} — documento interno de conferência</i>", estilos["Normal"])]
    SimpleDocTemplate(
        saida, pagesize=A4, title=titulo, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm
    ).build(blocos)
    return saida.getvalue()


def _escapar(texto: str) -> str:
    return str(texto).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _lista_de_documentacao(cabecalho: list[str], itens: list[_Item], nao_juntados: list[str]) -> bytes:
    def corpo(estilos: Any, cm: float) -> list[Any]:
        from reportlab.lib import colors
        from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

        normal = estilos["Normal"]
        linhas = [[Paragraph("<b>Arquivo</b>", normal), Paragraph("<b>Conteúdo</b>", normal), Paragraph("<b>Págs.</b>", normal)]]
        for item in itens:
            linhas.append([
                Paragraph(_escapar(item.nome.rsplit(".", 1)[0] if item.nome.endswith(".pdf") else item.nome), normal),
                Paragraph(_escapar(item.descricao or "—"), normal),
                Paragraph(str(item.paginas) if item.paginas else "—", normal),
            ])
        tabela = Table(linhas, colWidths=[6 * cm, 9 * cm, 2 * cm], repeatRows=1)
        tabela.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        blocos: list[Any] = [tabela]
        if nao_juntados:
            blocos += [Spacer(1, 0.4 * cm), Paragraph(
                "<b>Não juntados (uso interno):</b> " + _escapar("; ".join(nao_juntados)) + ".", normal
            )]
        return blocos

    return _pdf_de_conferencia("LISTA DE DOCUMENTAÇÃO PARA PROTOCOLO", cabecalho, corpo)


def _checklist(cabecalho: list[str], secoes: list[tuple[str, list[str]]]) -> bytes:
    def corpo(estilos: Any, cm: float) -> list[Any]:
        from reportlab.platypus import Flowable, Paragraph, Table, TableStyle

        class Quadrado(Flowable):
            """Campo marcável: o ☐ não existe nas fontes padrão do PDF."""

            def wrap(self, *_args: Any) -> tuple[float, float]:
                return 9, 9

            def draw(self) -> None:
                self.canv.rect(0, 0, 9, 9)

        blocos: list[Any] = []
        for titulo, itens in secoes:
            if not itens:
                continue
            blocos.append(Paragraph(f"<b>{_escapar(titulo)}</b>", estilos["Heading3"]))
            tabela = Table(
                [[Quadrado(), Paragraph(_escapar(item), estilos["Normal"])] for item in itens],
                colWidths=[0.7 * cm, 16.3 * cm],
            )
            tabela.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (0, -1), 4)]))
            blocos.append(tabela)
        return blocos

    return _pdf_de_conferencia("CHECKLIST PARA PROTOCOLO", cabecalho, corpo)


# ------------------------------------------------------------------ montagem


def montar(caso_id: str) -> Pacote:
    caso = armazenamento.obter_caso(caso_id)
    if not caso:
        raise ErroPacote("Caso não encontrado.")
    dados = peticao_local.carregar(caso_id)
    if not dados:
        raise ErroPacote("Gere a petição antes de montar a pasta para protocolo.")
    try:
        peticao_pdf = peticao_local.ler_pdf(caso_id)
    except peticao_local.ErroPeticao as erro:
        raise ErroPacote(f"Não foi possível gerar o PDF da petição: {erro}") from erro

    normalizar = organizacao_documental._scripts()[0].normalizar_nome
    entregas = armazenamento.listar_entregas(caso_id)
    try:
        categoria = str((casos.situacao_de(caso, entregas).get("categoria") or {}).get("nome") or "")
    except Exception:  # noqa: BLE001 - categoria só compõe o nome da pasta
        categoria = ""
    cliente = normalizar(str(caso.get("cliente") or "Cliente"))
    tipo = _tipo_da_acao(caso, categoria, normalizar)
    texto = _texto_da_peticao(dados)
    valor = _valor_da_causa(texto)
    reclamada = _reclamada(texto)
    cabecalho = [f"{cliente} × {reclamada}" if reclamada else cliente, tipo]

    ledger, _ = peticao_local.documentos_logicos(caso_id)
    por_nome: dict[str, dict[str, Any]] = {}
    for entrega in entregas:
        por_nome.setdefault(str(entrega.get("arquivo") or ""), entrega)
    canonicos = {doc["canonical_file"]: doc for doc in ledger}
    copias = {arquivo: doc for doc in ledger for arquivo in doc["source_files"][1:]}

    itens: list[_Item] = [_Item("Petição Inicial.pdf", peticao_pdf, f"Petição inicial{f' — valor da causa {valor}' if valor else ''}", _paginas(peticao_pdf))]
    planilhas: list[_Item] = []
    documentos: list[_Item] = []
    faltando: list[str] = []
    avisos_de_formato: list[str] = []
    with tempfile.TemporaryDirectory(prefix="protocolo_") as pasta:
        trabalho = Path(pasta)
        for entrega in entregas:
            arquivo = str(entrega.get("arquivo") or "")
            if not _PLANILHA.search(arquivo) or arquivo in copias:
                continue
            try:
                conteudo, ext = _arquivo_da_entrega(entrega, trabalho)
            except FileNotFoundError:
                faltando.append(arquivo)
                continue
            ext = ".PJC" if ext == ".pjc" else ext
            base = "Planilha De Cálculo"
            nome = f"{base}{ext}" if not any(p.nome == f"{base}{ext}" for p in planilhas) else f"{base} {len(planilhas) + 1}{ext}"
            descricao = "Arquivo do PJe-Calc para importação no PJe" if ext == ".PJC" else "Relatório do cálculo"
            planilhas.append(_Item(nome, conteudo, descricao, _paginas(conteudo)))
        for doc in ledger:
            arquivo = doc["canonical_file"]
            if _PLANILHA.search(arquivo):
                continue
            entrega = por_nome.get(arquivo)
            if entrega is None:
                faltando.append(arquivo)
                continue
            try:
                conteudo, ext = _arquivo_da_entrega(entrega, trabalho)
            except FileNotFoundError:
                faltando.append(arquivo)
                continue
            nome = f"Doc {doc['numero']}. {_nome_do_documento(doc, entrega, normalizar)}".translate(_PROIBIDOS)
            if ext != ".pdf":
                avisos_de_formato.append(f"{nome}{ext} não pôde ser convertido para PDF: converta ou retire antes do envio")
            descricao = str(entrega.get("identificacao_ia") or doc.get("document_type") or "").strip()
            documentos.append(_Item(f"{nome}{ext}", conteudo, descricao, _paginas(conteudo)))

    nao_juntados = []
    for entrega in entregas:
        arquivo = str(entrega.get("arquivo") or "")
        if arquivo in canonicos or (_PLANILHA.search(arquivo) and arquivo not in copias):
            continue
        origem = copias.get(arquivo)
        nao_juntados.append(f"{arquivo} (cópia do Doc {origem['numero']})" if origem else f"{arquivo} (uso interno)")

    conferencias = [
        f"Valor da causa conferido — {valor}" if valor else "Valor da causa conferido",
        "Vara do Trabalho competente conferida" if "Trabalhista" in tipo else "Juízo competente conferido",
        "Prescrição (bienal/quinquenal) conferida",
        "Tamanho e formato dos arquivos conferidos conforme o padrão do PJe/TRT",
    ]
    pendencias = [
        *(f"«{arquivo}» não pôde ser incluído na pasta: anexe manualmente" for arquivo in faltando),
        *avisos_de_formato,
        *([] if planilhas else ["Planilha de cálculo (PJe-Calc) não está entre os arquivos do caso: gere e anexe antes do envio"]),
        *_pendencias_da_peticao(dados),
    ]
    anexos = [*planilhas, *documentos]
    lista = _lista_de_documentacao(cabecalho, [itens[0], *anexos], nao_juntados)
    checklist = _checklist(cabecalho, [
        ("Peça e documentos", [
            "Petição inicial revisada e assinada (conferir no Word antes de exportar o PDF final)",
            *(item.nome.removesuffix(".pdf") for item in anexos),
        ]),
        ("Conferências", conferencias),
        ("Pendências antes do envio", pendencias),
    ])

    pasta_zip = f"Protocolo ({tipo}) {cliente}".translate(_PROIBIDOS).strip(" .")[:150]
    fd, bruto = tempfile.mkstemp(prefix="protocolo_", suffix=".zip")
    destino = Path(bruto)
    with open(fd, "wb") as saida, zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as zipado:
        for item in [*itens, *anexos]:
            zipado.writestr(f"{pasta_zip}/{item.nome}", item.conteudo)
        zipado.writestr(f"{pasta_zip}/Lista De Documentação Para Protocolo.pdf", lista)
        zipado.writestr(f"{pasta_zip}/Checklist.pdf", checklist)
    log.info("pasta para protocolo do caso %s: %d arquivo(s), %d faltando", caso_id, len(itens) + len(anexos) + 2, len(faltando))
    return Pacote(destino, f"{pasta_zip}.zip", len(itens) + len(anexos) + 2, faltando)
