"""Petição inicial gerada no Acervo — entrevista + OCR, sem agente."""

from __future__ import annotations

import io
import json
import logging
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import httpx

from . import analise_documentos, armazenamento, rag
from . import casos as casos_ocr

log = logging.getLogger("peticao_local")

ID_LOCAL = "local"
DOCX_STYLE_VERSION = 2
LOGO_LARA_MELO = Path(__file__).with_name("assets") / "lara-melo-logo.png"
SECOES_PADRAO = (
    ("HEADING", "Endereçamento e qualificação"),
    ("FACTS", "Dos fatos"),
    ("LEGAL_GROUNDS", "Do direito"),
    ("CLAIMS", "Dos pedidos"),
    ("EVIDENCE", "Das provas"),
    ("VALUE", "Do valor da causa"),
    ("CLOSING", "Fechamento"),
)


class ErroPeticao(RuntimeError):
    pass


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def existe(caso_id: str) -> bool:
    return armazenamento.obter_peticao_local(caso_id) is not None


def carregar(caso_id: str) -> dict[str, Any] | None:
    dados = armazenamento.obter_peticao_local(caso_id)
    if dados is None:
        return None
    dados.pop("_docx", None)
    return dados


def _salvar(caso_id: str, dados: dict[str, Any]) -> dict[str, Any]:
    dados["updated_at"] = _agora()
    dados["docx_style_version"] = DOCX_STYLE_VERSION
    armazenamento.salvar_peticao_local(
        caso_id,
        dados,
        montar_docx(dados.get("sections") or []),
    )
    return dados


def _llm_json(
    instrucao: str, entrada: str, *, timeout: float = 180.0
) -> dict[str, Any]:
    chave = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not chave:
        raise ErroPeticao("DEEPSEEK_API_KEY ausente — configure no .env.")
    base = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    modelo = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    try:
        resposta = httpx.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {chave}"},
            json={
                "model": modelo,
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": instrucao},
                    {"role": "user", "content": entrada[:120_000]},
                ],
            },
            timeout=timeout,
        )
        resposta.raise_for_status()
        return json.loads(resposta.json()["choices"][0]["message"]["content"])
    except (httpx.HTTPError, json.JSONDecodeError, KeyError) as erro:
        log.warning("petição local: LLM falhou: %s", erro)
        raise ErroPeticao("O modelo não respondeu — tente de novo.") from erro


def _documentos_ocr(caso_id: str) -> list[dict[str, str]]:
    documentos = []
    for entrega in armazenamento.listar_entregas(caso_id):
        detalhe = armazenamento.obter_entrega(entrega["id"])
        if not detalhe:
            continue
        texto = str((detalhe.get("extracao") or {}).get("texto_completo") or "").strip()
        if not texto:
            continue
        documentos.append(
            {
                "arquivo": str(entrega.get("arquivo") or ""),
                "texto": texto[:8000],
            }
        )
    return documentos


def _montar_contexto(caso_id: str, texto_entrevista: str) -> str:
    caso = armazenamento.obter_caso(caso_id) or {}
    situacao = casos_ocr.montar_situacao(caso_id) or {}
    categoria = (
        (situacao.get("categoria") or {}).get("nome") or caso.get("categoria") or ""
    )
    progresso = situacao.get("progresso") or {}

    linhas = [
        f"CLIENTE: {caso.get('cliente', '')}",
        f"CATEGORIA: {categoria}",
        "",
        "=== ENTREVISTA (transcrição) ===",
        texto_entrevista[:55_000],
    ]

    documentos = _documentos_ocr(caso_id)
    if documentos:
        linhas.append("\n=== DOCUMENTOS (texto extraído por OCR) ===")
        for doc in documentos[:20]:
            linhas.append(f"\n--- {doc['arquivo']} ---\n{doc['texto']}")

    try:
        achados = analise_documentos.analisar(caso_id).get("achados") or []
    except Exception as erro:
        log.warning("petição local: análise de documentos: %s", erro)
        achados = []

    if achados:
        linhas.append("\n=== ACHADOS (cruzamento entrevista × documentos) ===")
        for achado in achados[:15]:
            marca = "CONTRADIZ entrevista — " if achado.get("contradiz") else ""
            linhas.append(
                f"- {marca}{achado.get('informacao', '')} "
                f"({achado.get('documento', '')}): "
                f'"{str(achado.get("citacao", ""))[:200]}"'
            )

    # A jurisprudência é apoio jurídico, nunca fonte de fatos do cliente. A busca
    # semântica fica local no Acervo e é melhor-esforço: indisponibilidade da VPN ou do
    # pgvector não pode impedir a minuta.
    consulta_juridica = "\n".join(
        [
            str(caso.get("categoria") or ""),
            texto_entrevista[:10_000],
            *[str(a.get("informacao") or "") for a in achados[:10]],
        ]
    )
    try:
        precedentes = rag.buscar_similares(
            consulta_juridica,
            limite=6,
            timeout=35,
            connect_timeout=5,
            connect_retries=1,
        )
    except Exception as erro:
        log.warning("petição local: jurisprudência indisponível: %s", erro)
        precedentes = []
    if precedentes:
        linhas.append("\n=== PRECEDENTES DO TRIBUNAL (busca por embeddings) ===")
        for precedente in precedentes:
            meta = precedente.metadados or {}
            identificador = (
                precedente.identificador or meta.get("numero_processo") or ""
            )
            linhas.append(
                f"\n--- {precedente.titulo or 'Precedente'} | {identificador} "
                f"| similaridade {precedente.similaridade:.3f} ---\n"
                f"{precedente.texto[:3_500]}"
            )

    obrig = progresso.get("obrigatorios_total")
    entregues = progresso.get("obrigatorios_entregues")
    if obrig is not None:
        linhas.append(
            f"\n=== CHECKLIST ===\n{entregues}/{obrig} obrigatórios entregues"
        )

    return "\n".join(linhas)[:110_000]


def analisar(caso_id: str, *, texto_entrevista: str) -> dict[str, Any]:
    contexto = _montar_contexto(caso_id, texto_entrevista)
    saida = _llm_json(
        """Você é advogado trabalhista. Cruze a ENTREVISTA com os DOCUMENTOS (OCR).
Devolva JSON:
{
  "resumo": "síntese jurídica em 4-8 frases",
  "cruzamento_entrevista_documentos": "o que a entrevista diz vs. documentos",
  "pontos_fortes": ["pontos com prova ou relato consistente"],
  "lacunas": ["o que falta provar ou documentar"],
  "fatos_confirmados": ["fatos sustentados por documento"],
  "fatos_so_na_entrevista": ["alegações sem prova documental"],
  "observacoes": "alertas ao advogado"
}
Não invente fatos. Diferencie alegação de fato documentado.""",
        contexto,
    )
    return {
        "resumo": str(saida.get("resumo") or "").strip(),
        "cruzamento_entrevista_documentos": str(
            saida.get("cruzamento_entrevista_documentos") or ""
        ).strip(),
        "pontos_fortes": [
            str(x) for x in (saida.get("pontos_fortes") or []) if str(x).strip()
        ],
        "lacunas": [str(x) for x in (saida.get("lacunas") or []) if str(x).strip()],
        "fatos_confirmados": [
            str(x) for x in (saida.get("fatos_confirmados") or []) if str(x).strip()
        ],
        "fatos_so_na_entrevista": [
            str(x)
            for x in (saida.get("fatos_so_na_entrevista") or [])
            if str(x).strip()
        ],
        "observacoes": str(saida.get("observacoes") or "").strip(),
        "contexto": contexto[:80_000],
    }


def _normalizar_secoes(brutas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    por_codigo = {str(s.get("code") or ""): s for s in brutas}
    secoes: list[dict[str, Any]] = []
    for codigo, rotulo in SECOES_PADRAO:
        item = por_codigo.get(codigo) or {}
        conteudo = str(item.get("content") or "").strip()
        if not conteudo and codigo in por_codigo:
            conteudo = str(por_codigo[codigo].get("texto") or "").strip()
        secoes.append(
            {
                "code": codigo,
                "label": str(item.get("label") or rotulo),
                "content": conteudo,
                "written_by": "agent",
                "supporting_fact_ids": [],
                "cited_precedent_ids": [],
            }
        )
    return secoes


def redigir(
    caso_id: str, *, analise: dict[str, Any], texto_entrevista: str
) -> tuple[list[dict[str, Any]], list[str]]:
    contexto = analise.get("contexto") or _montar_contexto(caso_id, texto_entrevista)
    saida = _llm_json(
        """Redija uma PETIÇÃO INICIAL trabalhista completa em português formal.
Use SOMENTE fatos da entrevista e documentos — não invente.
Marque com [PENDENTE: motivo] o que depender só de alegação sem prova.
JSON:
{
  "secoes": [
    {"code": "HEADING", "label": "Endereçamento e qualificação", "content": "..."},
    {"code": "FACTS", "label": "Dos fatos", "content": "..."},
    {"code": "LEGAL_GROUNDS", "label": "Do direito", "content": "..."},
    {"code": "CLAIMS", "label": "Dos pedidos", "content": "..."},
    {"code": "EVIDENCE", "label": "Das provas", "content": "..."},
    {"code": "VALUE", "label": "Do valor da causa", "content": "..."},
    {"code": "CLOSING", "label": "Fechamento", "content": "..."}
  ],
  "pendencias": ["fatos sem comprovação documental"]
}
Cada content em parágrafos separados por linha em branco.""",
        (
            f"ANÁLISE:\n{analise.get('resumo', '')}\n"
            f"Cruzamento: {analise.get('cruzamento_entrevista_documentos', '')}\n"
            f"Lacunas: {', '.join(analise.get('lacunas') or [])}\n"
            f"Confirmados: {', '.join(analise.get('fatos_confirmados') or [])}\n\n"
            f"MATERIAL:\n{contexto[:90_000]}"
        ),
        timeout=240.0,
    )
    secoes = _normalizar_secoes(saida.get("secoes") or [])
    if not any(s["content"] for s in secoes):
        raise ErroPeticao("O modelo não devolveu texto da petição.")
    return secoes, [str(p) for p in (saida.get("pendencias") or []) if str(p).strip()]


def gerar(caso_id: str, *, texto_entrevista: str) -> dict[str, Any]:
    """Analisa e redige em uma chamada única à DeepSeek."""
    contexto = _montar_contexto(caso_id, texto_entrevista)
    saida = _llm_json(
        """Você é advogado trabalhista e redator de petições iniciais.
Em UMA resposta, organize o material do caso e redija uma minuta completa.
Use a entrevista como ALEGAÇÃO e os documentos como prova. Não invente fatos.
Os PRECEDENTES DO TRIBUNAL servem apenas de fundamento jurídico: nunca extraia deles
fatos ou nomes para o caso. Só cite precedente quando houver identificador no material.
Onde faltar dado indispensável, escreva [PENDENTE: explicação].

Devolva JSON exatamente com:
{
  "analise": {
    "resumo": "síntese jurídica",
    "cruzamento_entrevista_documentos": "confronto entre relato e provas",
    "pontos_fortes": ["..."], "lacunas": ["..."],
    "fatos_confirmados": ["..."], "fatos_so_na_entrevista": ["..."],
    "observacoes": "alertas para revisão"
  },
  "secoes": [
    {"code":"HEADING","label":"Endereçamento e qualificação","content":"..."},
    {"code":"FACTS","label":"Dos fatos","content":"..."},
    {"code":"LEGAL_GROUNDS","label":"Do direito","content":"..."},
    {"code":"CLAIMS","label":"Dos pedidos","content":"..."},
    {"code":"EVIDENCE","label":"Das provas","content":"..."},
    {"code":"VALUE","label":"Do valor da causa","content":"..."},
    {"code":"CLOSING","label":"Fechamento","content":"..."}
  ],
  "pendencias": ["..."]
}
Cada content deve conter parágrafos separados por linha em branco.""",
        contexto,
        timeout=240.0,
    )
    bruto_analise = saida.get("analise") or {}
    analise = {
        "resumo": str(bruto_analise.get("resumo") or "").strip(),
        "cruzamento_entrevista_documentos": str(
            bruto_analise.get("cruzamento_entrevista_documentos") or ""
        ).strip(),
        "pontos_fortes": [str(x) for x in bruto_analise.get("pontos_fortes") or []],
        "lacunas": [str(x) for x in bruto_analise.get("lacunas") or []],
        "fatos_confirmados": [
            str(x) for x in bruto_analise.get("fatos_confirmados") or []
        ],
        "fatos_so_na_entrevista": [
            str(x) for x in bruto_analise.get("fatos_so_na_entrevista") or []
        ],
        "observacoes": str(bruto_analise.get("observacoes") or "").strip(),
    }
    secoes = _normalizar_secoes(saida.get("secoes") or [])
    if not any(secao["content"] for secao in secoes):
        raise ErroPeticao("O modelo não devolveu texto da petição.")
    pendencias = [str(p) for p in saida.get("pendencias") or [] if str(p).strip()]
    agora = _agora()
    anterior = carregar(caso_id) or {}
    versao = int(anterior.get("version") or 0) + 1
    dados = {
        "id": ID_LOCAL,
        "document_type": "INITIAL_PETITION",
        "status": "IN_REVIEW",
        "version": versao,
        "title": "Petição inicial",
        "created_at": anterior.get("created_at") or agora,
        "updated_at": agora,
        "analise": analise,
        "sections": secoes,
        "readiness": {
            "ready": True,
            "blocking_issues": [],
            "warnings": analise.get("lacunas") or [],
            "pendencias": pendencias or analise.get("fatos_so_na_entrevista") or [],
            "completo": not pendencias and not analise.get("lacunas"),
        },
        "review": {
            "findings": [],
            "summary": analise.get("observacoes", ""),
            "blocking": 0,
        },
        "blocking_findings": 0,
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
    }
    _salvar(caso_id, dados)
    return dados


def salvar_secoes(caso_id: str, secoes: list[dict[str, str]]) -> dict[str, Any]:
    dados = carregar(caso_id)
    if not dados:
        raise ErroPeticao("Nenhuma petição gerada para este caso.")
    por_codigo = {s["code"]: s.get("content", "") for s in secoes if s.get("code")}
    for secao in dados.get("sections") or []:
        if secao["code"] in por_codigo:
            secao["content"] = por_codigo[secao["code"]]
    return _salvar(caso_id, dados)


def atualizar_status(caso_id: str, *, status: str) -> dict[str, Any]:
    dados = carregar(caso_id)
    if not dados:
        raise ErroPeticao("Nenhuma petição gerada para este caso.")
    dados["status"] = status
    return _salvar(caso_id, dados)


def para_api(dados: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": dados.get("id", ID_LOCAL),
        "document_type": dados.get("document_type", "INITIAL_PETITION"),
        "status": dados.get("status", "IN_REVIEW"),
        "version": dados.get("version", 1),
        "title": dados.get("title", "Petição inicial"),
        "readiness": dados.get("readiness") or {},
        "review": dados.get("review") or {},
        "blocking_findings": dados.get("blocking_findings", 0),
        "model": dados.get("model"),
        "created_at": dados.get("created_at", _agora()),
        "sections": dados.get("sections") or [],
    }


def progresso(caso_id: str, desde: str) -> dict[str, Any]:
    dados = carregar(caso_id)
    if not dados:
        return {
            "status": "RUNNING",
            "completed_steps": 0,
            "generation_id": None,
            "blocking_findings": 0,
        }
    criado = str(dados.get("updated_at") or dados.get("created_at") or "")
    if criado and criado >= desde:
        return {
            "status": "DONE",
            "completed_steps": len(dados.get("sections") or []),
            "generation_id": ID_LOCAL,
            "blocking_findings": dados.get("blocking_findings", 0),
        }
    return {
        "status": "RUNNING",
        "completed_steps": 0,
        "generation_id": None,
        "blocking_findings": 0,
    }


def _paragrafo_xml(texto: str, *, negrito: bool = False) -> str:
    linhas = texto.split("\n")
    partes: list[str] = []
    for linha in linhas:
        if not linha.strip():
            partes.append("<w:p/>")
            continue
        texto_xml = escape(linha)
        if negrito:
            partes.append(
                f'<w:p><w:pPr><w:jc w:val="center"/></w:pPr>'
                f'<w:r><w:rPr><w:b/></w:rPr><w:t xml:space="preserve">{texto_xml}</w:t></w:r></w:p>'
            )
        else:
            partes.append(
                f'<w:p><w:r><w:t xml:space="preserve">{texto_xml}</w:t></w:r></w:p>'
            )
    return "".join(partes)


def montar_docx(secoes: list[dict[str, Any]]) -> bytes:
    corpo: list[str] = []
    for secao in secoes:
        rotulo = str(secao.get("label") or secao.get("code") or "").strip()
        conteudo = str(secao.get("content") or "").strip()
        if rotulo and secao.get("code") not in ("HEADING",):
            corpo.append(_paragrafo_xml(rotulo.upper(), negrito=True))
        if conteudo:
            corpo.append(_paragrafo_xml(conteudo))
        corpo.append("<w:p/>")

    documento_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
 xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    {"".join(corpo)}
    <w:sectPr>
      <w:headerReference w:type="default" r:id="rIdHeader"/>
      <w:pgSz w:w="11906" w:h="16838"/>
      <w:pgMar w:top="1985" w:right="1417" w:bottom="1417" w:left="1701" w:header="360"/>
    </w:sectPr>
  </w:body>
</w:document>"""

    cabecalho_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
 xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
 xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
 xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">
  <w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:drawing>
    <wp:inline distT="0" distB="0" distL="0" distR="0">
      <wp:extent cx="1600200" cy="905010"/><wp:docPr id="1" name="Lara e Melo"/>
      <a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
        <pic:pic><pic:nvPicPr><pic:cNvPr id="1" name="lara-melo-logo.png"/><pic:cNvPicPr/></pic:nvPicPr>
          <pic:blipFill><a:blip r:embed="rIdLogo"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>
          <pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="1600200" cy="905010"/></a:xfrm>
            <a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>
        </pic:pic>
      </a:graphicData></a:graphic>
    </wp:inline>
  </w:drawing></w:r></w:p>
</w:hdr>"""

    estilos_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:docDefaults>
    <w:rPrDefault><w:rPr>
      <w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:eastAsia="Arial" w:cs="Arial"/>
      <w:sz w:val="24"/><w:szCs w:val="24"/><w:lang w:val="pt-BR"/>
    </w:rPr></w:rPrDefault>
    <w:pPrDefault><w:pPr><w:jc w:val="both"/><w:spacing w:line="360" w:lineRule="auto"/></w:pPr></w:pPrDefault>
  </w:docDefaults>
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
</w:styles>"""

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as arquivo:
        arquivo.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="png" ContentType="image/png"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>""",
        )
        arquivo.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>""",
        )
        arquivo.writestr("word/document.xml", documento_xml)
        arquivo.writestr("word/header1.xml", cabecalho_xml)
        arquivo.writestr("word/styles.xml", estilos_xml)
        arquivo.writestr("word/media/lara-melo-logo.png", LOGO_LARA_MELO.read_bytes())
        arquivo.writestr(
            "word/_rels/document.xml.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rIdHeader" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>
  <Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>""",
        )
        arquivo.writestr(
            "word/_rels/header1.xml.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rIdLogo" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/lara-melo-logo.png"/>
</Relationships>""",
        )
    return buffer.getvalue()


def ler_docx(caso_id: str) -> bytes:
    dados = armazenamento.obter_peticao_local(caso_id)
    if not dados:
        raise ErroPeticao("Petição não encontrada.")
    conteudo = bytes(dados.get("_docx") or b"")
    if int(dados.get("docx_style_version") or 0) < DOCX_STYLE_VERSION:
        return montar_docx(dados.get("sections") or [])
    return conteudo or montar_docx(dados.get("sections") or [])


def ler_pdf(caso_id: str) -> bytes:
    from . import docx_pdf

    try:
        return docx_pdf.converter(ler_docx(caso_id))
    except docx_pdf.ErroConversaoDocx as erro:
        raise ErroPeticao(str(erro)) from erro
