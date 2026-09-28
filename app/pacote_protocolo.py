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

import copy
import hashlib
import io
import logging
import re
import tempfile
import time
import uuid
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import (
    analise_documental,
    analise_documentos,
    armazenamento,
    casos,
    conversao_pdf,
    document_ledger,
    organizacao_documental,
    peticao_local,
    skill_de_arquivo,
)

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


class ErroSelecao(ErroPacote):
    """A seleção enviada pela tela de conferência não confere com os arquivos do caso."""


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


def _citados(dados: dict[str, Any]) -> set[int]:
    """Os números de "Documento NN" que a petição cita."""
    numeros: set[int] = set()
    for secao in dados.get("sections") or []:
        for achado in document_ledger._REF.finditer(str(secao.get("content") or "")):  # noqa: SLF001
            numeros.update(document_ledger._numeros(achado.group(1)))  # noqa: SLF001
    return numeros


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


# ------------------------------------------------------------------ conferência (o que vai para o protocolo)


_INSTRUCAO_TRIAGEM = """Você é o advogado responsável por protocolar esta petição inicial e confere, um
por um, os arquivos do caso para decidir o que vai ANEXADO ao processo.

Pense com cuidado em cada documento antes de decidir. Leia o que a petição afirma e pede, e para cada
arquivo pergunte: ele PROVA ou SUSTENTA algo que a petição afirma ou pede? É exigido para a ação
(identidade, CPF, comprovante de residência, procuração, declaração de hipossuficiência, CTPS,
contracheques, TRCT, CAT, laudos, atestados, documentos do INSS, boletim de ocorrência)? Se sim, vai.

NÃO vão ao tribunal: documentos internos do escritório (checklist, triagem, roteiro ou transcrição de
entrevista, anotações, contrato de honorários), cópias repetidas de um documento que já vai, arquivos
sem relação com os fatos da petição (foto aleatória, print sem conteúdo do caso, documento de outra
pessoa), arquivos em branco ou ilegíveis. Documento que a petição cita pelo número SEMPRE vai.

Depois, olhe o conjunto: falta algum documento que a petição menciona, que a ação normalmente exige
ou que provaria um pedido feito? Liste em `faltando` — só o que realmente não está entre os arquivos —
com a classificação e o caminho que a skill documental manda dar a todo documento faltante.

Quando o arquivo vier com "análise documental", use-a: documento ilegível, desatualizado ou duplicado
diz isso no motivo (e ilegível ou cortado vira pendência de reenvio, não PDF "aceitável").

A "Entrevista.pdf" e o "Checklist.pdf" de que a skill fala são entregas INTERNAS ao escritório: não vão
ao tribunal.

Responda APENAS JSON:
{"documentos":[{"id":"id exato da lista","incluir":true,"motivo":"uma frase clara, para o advogado, do porquê"}],
 "faltando":[{"documento":"o que falta","motivo":"por que faz falta nesta petição",
              "classificacao":"COMPROMETE|ERA_MELHOR_TER|NAO_INTERFERE","como_obter":"canal, fundamento e prazo"}]}
Inclua TODOS os ids da lista em `documentos`."""

CLASSIFICACOES_DE_FALTANTE = ("COMPROMETE", "ERA_MELHOR_TER", "NAO_INTERFERE")


def _instrucao_triagem() -> str:
    criterios = skill_de_arquivo.criterios_documentais(
        r"^Regra de ouro", r"^Arquivos duplicados", r"^3\.5\b", r"^3\.7-A", r"^Conexão com a skill",
    )
    return f"{_INSTRUCAO_TRIAGEM}\n\n{criterios}" if criterios else _INSTRUCAO_TRIAGEM


def _analise_da_skill(caso_id: str) -> dict[str, dict[str, Any]]:
    """O que a análise documental (skill) concluiu de cada arquivo, se ela já rodou neste caso."""
    try:
        registro = analise_documental.obter(caso_id)
    except Exception:  # noqa: BLE001 - sem análise documental a triagem segue com a leitura de cada arquivo
        log.warning("conferência do protocolo: análise documental do caso %s indisponível", caso_id, exc_info=True)
        return {}
    if not registro or registro.get("status") != "ready" or not isinstance(registro.get("resultado"), dict):
        return {}
    return {
        str(d.get("documento_id")): d
        for d in registro["resultado"].get("documentos") or [] if isinstance(d, dict)
    }


def _resumo_da_skill(doc: dict[str, Any]) -> str:
    partes = []
    if doc.get("tipo") and doc["tipo"] != "NÃO IDENTIFICADO":
        partes.append(f"é {doc['tipo']}")
    if doc.get("data"):
        partes.append(f"data {doc['data']}")
    if doc.get("legivel") is False:
        partes.append("ILEGÍVEL" + (f" ({doc['problema']})" if doc.get("problema") else ""))
    if doc.get("atualizacao") == "DESATUALIZADO":
        partes.append("DESATUALIZADO" + (f" ({doc['motivo_atualizacao']})" if doc.get("motivo_atualizacao") else ""))
    if doc.get("duplicado_de"):
        partes.append(f"duplicado de id={doc['duplicado_de']}")
    for chave, rotulo in (("pontos_fortes", "prova"), ("vulnerabilidades", "fraqueza")):
        itens = [str(x) for x in doc.get(chave) or [] if str(x).strip()]
        if itens:
            partes.append(f"{rotulo}: " + "; ".join(itens[:3]))
    return " | ".join(partes)[:600]

def _leitura_curta(extracao: dict[str, Any], limite: int = 700) -> str:
    leitura = peticao_local.leitura_da_ia(extracao)
    if not leitura:
        leitura = " ".join(str(extracao.get("texto_completo") or "").split())[:500]
    return leitura[:limite]


def _inventario(caso_id: str) -> dict[str, Any]:
    caso = armazenamento.obter_caso(caso_id)
    if not caso:
        raise ErroPacote("Caso não encontrado.")
    dados = peticao_local.carregar(caso_id)
    if not dados:
        raise ErroPacote("Gere a petição antes de conferir os documentos para protocolo.")
    entregas = armazenamento.listar_entregas(caso_id)
    ledger, _ = peticao_local.documentos_logicos(caso_id)
    try:
        extracoes = {str(e.get("id")): e.get("extracao") or {} for e in armazenamento.listar_extracoes_do_caso(caso_id)}
    except Exception:  # noqa: BLE001 - sem leitura, a conferência segue pelas regras e pelo nome do arquivo
        log.warning("conferência do protocolo: extrações do caso %s indisponíveis", caso_id, exc_info=True)
        extracoes = {}
    return {"caso": caso, "dados": dados, "entregas": entregas, "ledger": ledger, "extracoes": extracoes,
            "analise_skill": _analise_da_skill(caso_id)}


def _candidatos(inventario: dict[str, Any]) -> list[dict[str, Any]]:
    """Todos os arquivos do caso, com a sugestão pelas REGRAS (sem modelo)."""
    ledger = inventario["ledger"]
    canonicos = {doc["canonical_file"]: doc for doc in ledger}
    copias = {arquivo: doc for doc in ledger for arquivo in doc["source_files"][1:]}
    citados = _citados(inventario["dados"])
    normalizar = organizacao_documental._scripts()[0].normalizar_nome
    saida = []
    for entrega in inventario["entregas"]:
        arquivo = str(entrega.get("arquivo") or "")
        entrega_id = str(entrega.get("id"))
        extracao = inventario["extracoes"].get(entrega_id) or {}
        doc = canonicos.get(arquivo)
        copia = copias.get(arquivo)
        numero = int(doc["numero"]) if doc else None
        tipo = str(
            entrega.get("identificacao_ia")
            or (doc or {}).get("document_type")
            or (extracao.get("classificacao_semantica") or {}).get("tipo_semantico")
            or ""
        ).strip()
        if tipo.lower() == "indefinido":
            tipo = ""
        citado = numero is not None and numero in citados
        if _PLANILHA.search(arquivo) and not copia:
            categoria, sugerido, motivo = "planilha", True, "Planilha de cálculo: vai como «Planilha De Cálculo»."
        elif doc:
            categoria, sugerido = "documento", True
            motivo = (
                f"A petição cita este arquivo como Documento {numero:02d}."
                if citado else f"Documento de prova do caso (Documento {numero:02d})."
            )
        elif copia:
            categoria, sugerido = "copia", False
            motivo = f"Cópia repetida do Documento {int(copia['numero']):02d}, que já vai na pasta."
        else:
            categoria, sugerido = "interno", False
            motivo = "Parece documento interno do escritório (checklist, entrevista, honorários): não vai ao tribunal."
        if categoria == "planilha":
            rotulo = "Planilha De Cálculo"
        else:
            nome = _nome_do_documento(doc or {"canonical_file": arquivo, "document_type": tipo}, entrega, normalizar)
            if nome == "Documento" and not doc:
                nome = f"Cópia do Doc {int(copia['numero'])}" if copia else (Path(arquivo).stem or nome)
            rotulo = f"Doc {numero}. {nome}" if numero is not None else nome
        da_skill = inventario.get("analise_skill", {}).get(entrega_id) or {}
        if da_skill.get("legivel") is False:
            motivo += " Atenção: a análise documental achou o arquivo ilegível — confira e peça reenvio se preciso."
        elif da_skill.get("atualizacao") == "DESATUALIZADO":
            motivo += " Atenção: a análise documental o considera desatualizado" + (
                f" ({da_skill['motivo_atualizacao']})." if da_skill.get("motivo_atualizacao") else "."
            )
        saida.append({
            "entrega_id": entrega_id,
            "arquivo": arquivo,
            "numero": numero,
            "rotulo": rotulo,
            "tipo": tipo,
            "categoria": categoria,
            "citado_na_peticao": citado,
            "copia_de": int(copia["numero"]) if copia else None,
            "sugerido": sugerido,
            "motivo": motivo,
            "leitura": _leitura_curta(extracao),
            "analise_documental": _resumo_da_skill(da_skill) if da_skill else "",
            "converte_para_pdf": _converte_para_pdf(arquivo),
        })
    return saida


def _converte_para_pdf(arquivo: str) -> bool:
    ext = Path(arquivo).suffix.lower()
    return ext == ".pdf" or ext in conversao_pdf.EXTENSOES_IMAGEM or ext in conversao_pdf.EXTENSOES_DOCX


def _faltando_pelas_regras(inventario: dict[str, Any], candidatos: list[dict[str, Any]]) -> list[dict[str, str]]:
    numeros = {int(d["numero"]) for d in inventario["ledger"]}
    faltando = [
        {"documento": f"Documento {n:02d}", "motivo": "A petição cita esse número, mas ele não existe entre os arquivos do caso.",
         "classificacao": "COMPROMETE", "como_obter": "Anexe o arquivo ao caso ou ajuste a citação na petição."}
        for n in sorted(_citados(inventario["dados"]) - numeros)
    ]
    if not any(c["categoria"] == "planilha" for c in candidatos):
        faltando.append({
            "documento": "Planilha de cálculo (PJe-Calc)",
            "motivo": "Não está entre os arquivos do caso: gere e anexe antes do envio.",
            "classificacao": "COMPROMETE", "como_obter": "Gere no PJe-Calc e anexe ao caso.",
        })
    return faltando


def _julgar_com_ia(inventario: dict[str, Any], candidatos: list[dict[str, Any]]) -> dict[str, Any]:
    texto = _texto_da_peticao(inventario["dados"])
    lista = "\n\n".join(
        f"id={c['entrega_id']} | arquivo={c['arquivo']}"
        + (f" | Documento {c['numero']:02d}" if c["numero"] is not None else "")
        + (" | CITADO NA PETIÇÃO" if c["citado_na_peticao"] else "")
        + (f" | cópia do Documento {c['copia_de']:02d}" if c["copia_de"] else "")
        + (f" | tipo: {c['tipo']}" if c["tipo"] else "")
        + (f"\nanálise documental: {c['analise_documental']}" if c.get("analise_documental") else "")
        + (f"\n{c['leitura']}" if c["leitura"] else "\n(sem texto lido)")
        for c in candidatos
    )
    mensagem = f"PETIÇÃO INICIAL:\n{texto[:40_000]}\n\nARQUIVOS DO CASO:\n{lista[:120_000]}"
    return analise_documentos._chamar_modelo(mensagem, instrucao=_instrucao_triagem(), max_tokens=12_000)  # noqa: SLF001


#: Julgamentos recentes por (caso, petição + arquivos). Abrir e fechar a tela de
#: conferência não pode custar uma nova volta no modelo a cada vez; mudar a
#: petição ou os arquivos muda a assinatura e força um julgamento novo.
_JULGAMENTOS: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
_VALIDADE_JULGAMENTO_S = 600.0


def _assinatura(inventario: dict[str, Any]) -> str:
    base = _texto_da_peticao(inventario["dados"]) + "|" + "|".join(
        f"{e.get('id')}:{e.get('arquivo')}" for e in inventario["entregas"]
    )
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def _julgamento(caso_id: str, inventario: dict[str, Any], candidatos: list[dict[str, Any]]) -> dict[str, Any]:
    chave = (caso_id, _assinatura(inventario))
    agora = time.monotonic()
    salvo = _JULGAMENTOS.get(chave)
    if salvo and agora - salvo[0] < _VALIDADE_JULGAMENTO_S:
        return copy.deepcopy(salvo[1])
    bruto = _julgar_com_ia(inventario, candidatos)
    if len(_JULGAMENTOS) > 64:
        _JULGAMENTOS.clear()
    _JULGAMENTOS[chave] = (agora, bruto)
    return copy.deepcopy(bruto)


def sugerir(caso_id: str, *, usar_ia: bool = True) -> dict[str, Any]:
    """A lista que a tela de conferência mostra: o que a IA acha que vai para o
    protocolo, o que fica de fora (com o motivo de cada um) e o que falta.

    Documento que a petição cita pelo número vai sempre marcado: tirá-lo quebra
    a referência da peça, e a decisão de tirar é do advogado, não do modelo.
    """
    inventario = _inventario(caso_id)
    candidatos = _candidatos(inventario)
    faltando = _faltando_pelas_regras(inventario, candidatos)
    analisado_por, aviso = "regras", ""
    if usar_ia and candidatos:
        try:
            bruto = _julgamento(caso_id, inventario, candidatos)
            por_id = {
                str(item.get("id")): item
                for item in bruto.get("documentos") or [] if isinstance(item, dict)
            }
            for candidato in candidatos:
                decisao = por_id.get(candidato["entrega_id"])
                if not decisao:
                    continue
                motivo = " ".join(str(decisao.get("motivo") or "").split())[:400]
                incluir = bool(decisao.get("incluir"))
                if candidato["citado_na_peticao"]:
                    candidato["sugerido"] = True
                    if motivo:
                        candidato["motivo"] = f"{candidato['motivo']} {motivo}"
                    continue
                candidato["sugerido"] = incluir
                if motivo:
                    candidato["motivo"] = motivo
            vistos = {f["documento"].casefold() for f in faltando}
            for item in bruto.get("faltando") or []:
                if not isinstance(item, dict):
                    continue
                documento = " ".join(str(item.get("documento") or "").split())[:160]
                if documento and documento.casefold() not in vistos:
                    vistos.add(documento.casefold())
                    classificacao = str(item.get("classificacao") or "").strip().upper().replace(" ", "_")
                    faltando.append({
                        "documento": documento,
                        "motivo": " ".join(str(item.get("motivo") or "").split())[:400],
                        "classificacao": classificacao if classificacao in CLASSIFICACOES_DE_FALTANTE else "",
                        "como_obter": " ".join(str(item.get("como_obter") or "").split())[:300],
                    })
            analisado_por = "ia"
        except Exception as erro:  # noqa: BLE001 - sem o modelo, a conferência segue pelas regras
            log.warning("conferência do protocolo do caso %s sem IA: %s", caso_id, erro)
            aviso = "A IA não respondeu agora; a lista abaixo segue as regras do escritório. Confira com atenção."
    return {
        "documentos": candidatos,
        "faltando": faltando,
        "pendencias": _pendencias_da_peticao(inventario["dados"]),
        "analisado_por": analisado_por,
        "aviso": aviso,
    }


# ------------------------------------------------------------------ montagem


def montar(
    caso_id: str,
    selecionados: list[str] | None = None,
    faltando_informado: list[str] | None = None,
) -> Pacote:
    """Monta o ZIP. `selecionados` são as entregas conferidas na tela; sem ele,
    vai o padrão (documentos do ledger e planilhas).

    Documento do ledger conserva o número que a petição cita, mesmo que outro
    tenha sido retirado — renumerar faria a peça apontar para o arquivo errado.
    Documento acrescentado na conferência recebe o próximo número livre.
    """
    caso = armazenamento.obter_caso(caso_id)
    if not caso:
        raise ErroPacote("Caso não encontrado.")
    dados = peticao_local.carregar(caso_id)
    if not dados:
        raise ErroPacote("Gere a petição antes de montar a pasta para protocolo.")
    entregas = armazenamento.listar_entregas(caso_id)
    escolhidos = None if selecionados is None else {str(i) for i in selecionados}
    if escolhidos is not None:
        conhecidos = {str(e.get("id")) for e in entregas}
        estranhos = escolhidos - conhecidos
        if estranhos:
            raise ErroSelecao("Um dos documentos marcados não pertence a este caso. Recarregue a conferência.")
    try:
        peticao_pdf = peticao_local.ler_pdf(caso_id)
    except peticao_local.ErroPeticao as erro:
        raise ErroPacote(f"Não foi possível gerar o PDF da petição: {erro}") from erro

    normalizar = organizacao_documental._scripts()[0].normalizar_nome
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

    def vai(entrega: dict[str, Any] | None, padrao: bool) -> bool:
        if escolhidos is None:
            return padrao
        return entrega is not None and str(entrega.get("id")) in escolhidos

    itens: list[_Item] = [_Item("Petição Inicial.pdf", peticao_pdf, f"Petição inicial{f' — valor da causa {valor}' if valor else ''}", _paginas(peticao_pdf))]
    planilhas: list[_Item] = []
    documentos: list[_Item] = []
    faltando: list[str] = []
    avisos_de_formato: list[str] = []
    incluidos: set[str] = set()
    with tempfile.TemporaryDirectory(prefix="protocolo_") as pasta:
        trabalho = Path(pasta)
        for entrega in entregas:
            arquivo = str(entrega.get("arquivo") or "")
            if not _PLANILHA.search(arquivo) or not vai(entrega, arquivo not in copias):
                continue
            incluidos.add(str(entrega.get("id")))
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
        a_juntar: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
        for doc in ledger:
            arquivo = doc["canonical_file"]
            if _PLANILHA.search(arquivo):
                continue
            entrega = por_nome.get(arquivo)
            if not vai(entrega, True):
                continue
            if entrega is None:
                faltando.append(arquivo)
                continue
            a_juntar.append((int(doc["numero"]), doc, entrega))
        if escolhidos is not None:
            proximo = max((int(d["numero"]) for d in ledger), default=0) + 1
            for entrega in entregas:
                arquivo = str(entrega.get("arquivo") or "")
                if str(entrega.get("id")) not in escolhidos or arquivo in canonicos or _PLANILHA.search(arquivo):
                    continue
                a_juntar.append((proximo, {"canonical_file": arquivo, "document_type": ""}, entrega))
                proximo += 1
        for numero, doc, entrega in a_juntar:
            arquivo = str(entrega.get("arquivo") or "")
            incluidos.add(str(entrega.get("id")))
            try:
                conteudo, ext = _arquivo_da_entrega(entrega, trabalho)
            except FileNotFoundError:
                faltando.append(arquivo)
                continue
            nome = f"Doc {numero}. {_nome_do_documento(doc, entrega, normalizar)}".translate(_PROIBIDOS)
            if ext != ".pdf":
                avisos_de_formato.append(f"{nome}{ext} não pôde ser convertido para PDF: converta ou retire antes do envio")
            descricao = str(entrega.get("identificacao_ia") or doc.get("document_type") or "").strip()
            documentos.append(_Item(f"{nome}{ext}", conteudo, descricao, _paginas(conteudo)))

    nao_juntados = []
    for entrega in entregas:
        arquivo = str(entrega.get("arquivo") or "")
        if str(entrega.get("id")) in incluidos:
            continue
        if escolhidos is None and arquivo in canonicos:
            continue
        origem = copias.get(arquivo)
        if origem:
            nao_juntados.append(f"{arquivo} (cópia do Doc {origem['numero']})")
        elif arquivo in canonicos or _PLANILHA.search(arquivo):
            nao_juntados.append(f"{arquivo} (retirado na conferência)")
        else:
            nao_juntados.append(f"{arquivo} (uso interno)")

    retirados_citados = []
    if escolhidos is not None:
        citados = _citados(dados)
        for doc in ledger:
            entrega = por_nome.get(doc["canonical_file"])
            if int(doc["numero"]) in citados and (entrega is None or str(entrega.get("id")) not in incluidos):
                retirados_citados.append(
                    f"A petição cita o Documento {int(doc['numero']):02d} («{doc['canonical_file']}»), "
                    "mas ele ficou fora da pasta: inclua o documento ou ajuste a petição"
                )

    conferencias = [
        f"Valor da causa conferido — {valor}" if valor else "Valor da causa conferido",
        "Vara do Trabalho competente conferida" if "Trabalhista" in tipo else "Juízo competente conferido",
        "Prescrição (bienal/quinquenal) conferida",
        "Tamanho e formato dos arquivos conferidos conforme o padrão do PJe/TRT",
    ]
    pendencias = [
        *(f"«{arquivo}» não pôde ser incluído na pasta: anexe manualmente" for arquivo in faltando),
        *retirados_citados,
        *(f"Falta providenciar: {item}" for item in (faltando_informado or []) if str(item).strip()),
        *avisos_de_formato,
        *([] if planilhas else [
            "Planilha de cálculo (PJe-Calc) ficou fora da pasta: anexe antes do envio"
            if any(_PLANILHA.search(str(e.get("arquivo") or "")) for e in entregas)
            else "Planilha de cálculo (PJe-Calc) não está entre os arquivos do caso: gere e anexe antes do envio"
        ]),
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
