"""Monta o relatório da entrevista para a equipe jurídica.

É a entrega que o próprio roteiro promete ao cliente, no oitavo parágrafo da
saudação:

    "Ao final da entrevista, todas as informações serão encaminhadas para
    análise da equipe jurídica LARA & MELO ADVOGADOS ASSOCIADOS, que avaliarão
    cuidadosamente a viabilidade das medidas cabíveis."

Quem recebe isto não estava na conversa. O relatório precisa dizer o que foi
perguntado, o que foi respondido, e — principalmente — **o que ficou sem
resposta**, porque é isso que o advogado vai ter de correr atrás antes de
peticionar.

O QUE ELE NÃO FAZ, E POR QUÊ

Não conclui, não classifica juridicamente e não avalia viabilidade. O roteiro
reserva essa análise à equipe jurídica, e ela é o próximo passo do fluxo — não o
anterior. Um relatório que já chegasse dizendo "caso viável, acidente típico com
nexo estabelecido" faria o advogado ler para conferir uma conclusão em vez de ler
para formar a sua.

O que sai daqui é organização: as respostas na ordem do roteiro, os módulos que o
rastreio abriu, as lacunas, e os impedimentos que o escritório mandou observar.
Nada é reescrito — o texto do cliente vai como foi transcrito, porque a palavra
que ele usou para descrever a dor é dado, não rascunho.

POR QUE .docx E NÃO PDF OU TEXTO

É o formato que o escritório usa: o relatório entra na pasta do caso, é anexado,
comentado e recortado para a petição. PDF fecharia isso, e texto puro perderia a
hierarquia que faz um documento de 86 respostas ser navegável.

O arquivo é montado à mão, sem biblioteca: um .docx é um zip com XML dentro, e as
quatro partes obrigatórias estão em `_PARTES`. `python-docx` resolveria o mesmo
com uma dependência a mais num projeto que já carrega PaddleOCR e CTranslate2.
"""

from __future__ import annotations

import io
import logging
import zipfile
from datetime import datetime
from typing import Any
from xml.sax.saxutils import escape

from . import marca, roteiros

log = logging.getLogger("relatorio")

#: Cabeçalho que o Word espera. O `standalone="yes"` e o CRLF são os que ele
#: próprio escreve — a mesma razão documentada em `contrato.py`.
DECLARACAO = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

#: Os namespaces que a imagem inline (o emblema) exige, além do `w`. Declarados
#: no elemento raiz para não repetir em cada nó do desenho.
NS_DESENHO = (
    ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    ' xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"'
    ' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
    ' xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"'
)

#: Largura do emblema no papel: 5 das ~6,5 polegadas úteis, centralizado. O Word
#: mede em EMU (914400 por polegada); a altura vem da proporção do PNG.
LARGURA_EMBLEMA_EMU = int(5.0 * 914400)


class ErroRelatorio(Exception):
    """Falha que o usuário precisa ver."""


# ------------------------------------------------------------------ conteúdo


def _respondida(valor: Any) -> bool:
    if isinstance(valor, list):
        return len(valor) > 0
    return bool(str(valor or "").strip())


def _texto_resposta(valor: Any) -> str:
    if isinstance(valor, list):
        return ", ".join(str(v) for v in valor)
    return str(valor or "").strip()


def montar(
    respostas: dict[str, Any],
    codigo_roteiro: str = "empregado_publico",
    entrevistador: str = "",
) -> dict[str, Any]:
    """A estrutura do relatório, antes de virar arquivo.

    Separada da geração do .docx de propósito: é ela que a tela mostra para
    conferência antes de gerar, e é ela que o teste examina sem precisar abrir
    um zip.
    """
    roteiro = roteiros.obter(codigo_roteiro)
    if roteiro is None:
        raise ErroRelatorio(f"Roteiro {codigo_roteiro!r} não existe.")

    positivos = {
        modulo
        for pergunta_id, modulo in roteiros.MAPA_RASTREIO.items()
        if str(respostas.get(pergunta_id, "")).strip().lower() == "sim"
    }

    blocos: list[dict[str, Any]] = []
    total = respondidas = 0
    faltando_obrigatorias: list[dict[str, str]] = []

    for bloco in roteiro.blocos:
        # Módulo que o rastreio não abriu não é lacuna: ele não se aplica a este
        # cliente, e listá-lo como pendente mandaria o advogado atrás de resposta
        # para pergunta que nunca deveria ser feita.
        if bloco.modulo and bloco.modulo not in positivos:
            continue

        itens = []
        for pergunta in bloco.perguntas:
            valor = respostas.get(pergunta.id)
            tem = _respondida(valor)
            total += 1
            respondidas += 1 if tem else 0
            if not tem and pergunta.obrigatoria:
                faltando_obrigatorias.append(
                    {"pergunta_id": pergunta.id, "pergunta": pergunta.texto}
                )
            itens.append(
                {
                    "pergunta_id": pergunta.id,
                    "pergunta": pergunta.texto,
                    "resposta": _texto_resposta(valor),
                    "respondida": tem,
                    "obrigatoria": pergunta.obrigatoria,
                }
            )

        blocos.append(
            {
                "id": bloco.id,
                "titulo": bloco.titulo,
                "objetivo": bloco.objetivo,
                "delegado_a": bloco.delegado_a,
                "itens": itens,
            }
        )

    return {
        "roteiro": roteiro.nome,
        "cliente": _texto_resposta(respostas.get("nome")) or "(nome não informado)",
        "cpf": _texto_resposta(respostas.get("cpf")),
        "entrevistador": entrevistador.strip(),
        "gerado_em": datetime.now().strftime("%d/%m/%Y às %H:%M"),
        "modulos_abertos": sorted(positivos),
        "blocos": blocos,
        "progresso": {
            "respondidas": respondidas,
            "total": total,
            "percentual": round(respondidas * 100 / total, 1) if total else 0.0,
        },
        "faltando_obrigatorias": faltando_obrigatorias,
        "impedimentos": roteiros.impedimentos(codigo_roteiro, respostas),
    }


# --------------------------------------------------------------------- .docx


def _p(texto: str, *, estilo: str = "", negrito: bool = False, tamanho: int = 0) -> str:
    """Um parágrafo. `tamanho` em meios-pontos, como o OOXML mede."""
    props = []
    if estilo:
        props.append(f'<w:pStyle w:val="{estilo}"/>')
    corrida = []
    if negrito:
        corrida.append("<w:b/>")
    if tamanho:
        corrida.append(f'<w:sz w:val="{tamanho}"/>')
    rpr = f"<w:rPr>{''.join(corrida)}</w:rPr>" if corrida else ""
    ppr = f"<w:pPr>{''.join(props)}</w:pPr>" if props else ""
    return (
        f"<w:p>{ppr}<w:r>{rpr}"
        f'<w:t xml:space="preserve">{escape(texto)}</w:t>'
        f"</w:r></w:p>"
    )


def _linha_vazia() -> str:
    return "<w:p/>"


def _emblema(dimensao: tuple[int, int]) -> str:
    """O parágrafo centralizado com o símbolo do escritório (imagem inline).

    `dimensao` é (largura, altura) do PNG em px; serve só para a proporção — o
    tamanho no papel é o `LARGURA_EMBLEMA_EMU`. A imagem em si é `rIdLogo`,
    registrada em `word/_rels/document.xml.rels` e gravada em `word/media/`.
    """
    largura_px, altura_px = dimensao
    cx = LARGURA_EMBLEMA_EMU
    cy = int(cx * altura_px / largura_px) if largura_px else cx
    return (
        '<w:p><w:pPr><w:jc w:val="center"/><w:spacing w:after="160"/></w:pPr>'
        "<w:r><w:drawing>"
        '<wp:inline distT="0" distB="0" distL="0" distR="0">'
        f'<wp:extent cx="{cx}" cy="{cy}"/>'
        '<wp:effectExtent l="0" t="0" r="0" b="0"/>'
        '<wp:docPr id="1" name="Emblema do escritório"/>'
        "<wp:cNvGraphicFramePr>"
        '<a:graphicFrameLocks noChangeAspect="1"/>'
        "</wp:cNvGraphicFramePr>"
        "<a:graphic>"
        '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        "<pic:pic>"
        '<pic:nvPicPr><pic:cNvPr id="1" name="Emblema"/><pic:cNvPicPr/></pic:nvPicPr>'
        '<pic:blipFill><a:blip r:embed="rIdLogo"/>'
        "<a:stretch><a:fillRect/></a:stretch></pic:blipFill>"
        "<pic:spPr>"
        f'<a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        "</pic:spPr>"
        "</pic:pic>"
        "</a:graphicData></a:graphic>"
        "</wp:inline>"
        "</w:drawing></w:r></w:p>"
    )


def _precedentes(indices: Any) -> str:
    """Formata as citações `[P1, P3]` que sustentam uma ação ou risco."""
    if not isinstance(indices, list):
        return ""
    limpos = [str(p).strip() for p in indices if str(p).strip()]
    return f" [{', '.join(limpos)}]" if limpos else ""


def _secao_analise(analise: dict[str, Any]) -> list[str]:
    """A análise assistida por precedentes, quando a base respondeu.

    Vem depois das pendências e ANTES das respostas em detalhe: é a síntese que
    o advogado lê primeiro. Cada sugestão carrega o índice do precedente que a
    sustenta, e o rodapé lembra que a decisão é dele — o mesmo contrato do
    `/api/estrategia`, de onde estes dados vêm.
    """
    # A base fora do ar não impede o relatório: sai a nota, e o resto segue.
    if analise.get("indisponivel"):
        return [
            _linha_vazia(),
            _p("ANÁLISE ASSISTIDA POR PRECEDENTES", negrito=True, tamanho=26),
            _p(str(analise["indisponivel"]), tamanho=20),
        ]

    partes = [
        _linha_vazia(),
        _p("ANÁLISE ASSISTIDA POR PRECEDENTES", negrito=True, tamanho=26),
    ]

    if resumo := str(analise.get("resumo", "")).strip():
        partes.append(_p(resumo))

    acoes = [a for a in (analise.get("acoes") or []) if isinstance(a, dict)]
    if acoes:
        partes.append(_p("Ações sugeridas", negrito=True))
        for a in acoes:
            acao = str(a.get("acao", "")).strip()
            if not acao:
                continue
            partes.append(_p(f"• {acao}{_precedentes(a.get('precedentes'))}", negrito=True))
            if porque := str(a.get("porque", "")).strip():
                partes.append(_p(porque))

    riscos = [r for r in (analise.get("riscos") or []) if isinstance(r, dict)]
    if riscos:
        partes.append(_p("Riscos observados", negrito=True))
        for r in riscos:
            risco = str(r.get("risco", "")).strip()
            if risco:
                partes.append(_p(f"• {risco}{_precedentes(r.get('precedentes'))}"))

    lacunas = [str(x).strip() for x in (analise.get("lacunas") or []) if str(x).strip()]
    if lacunas:
        partes.append(_p("Lacunas a preencher", negrito=True))
        partes += [_p(f"• {lac}") for lac in lacunas]

    precedentes = [p for p in (analise.get("precedentes") or []) if isinstance(p, dict)]
    if precedentes:
        partes.append(_p("Precedentes consultados", negrito=True))
        for p in precedentes:
            partes.append(
                _p(
                    f"{p.get('indice', '')} — processo {p.get('processo', '?')} "
                    f"({p.get('resultado', '—')}) · {p.get('fonte', '—')} · "
                    f"similaridade {p.get('similaridade', '—')}",
                    tamanho=18,
                )
            )

    aviso = str(analise.get("aviso", "")).strip() or (
        "Análise assistiva, gerada a partir de precedentes públicos; requer "
        "revisão do advogado. Não prevê resultado nem substitui o parecer jurídico."
    )
    partes.append(_p(aviso, tamanho=18))
    return partes


def _corpo(dados: dict[str, Any], dimensao_emblema: tuple[int, int] | None) -> str:
    partes: list[str] = []
    # O símbolo do escritório abre o documento. Só entra se o PNG foi montado —
    # falha ao desenhar não pode impedir a entrega do relatório.
    if dimensao_emblema:
        partes.append(_emblema(dimensao_emblema))
    partes += [
        _p("RELATÓRIO DE ENTREVISTA", negrito=True, tamanho=32),
        _p(dados["roteiro"], tamanho=22),
        _linha_vazia(),
        _p(f"Cliente: {dados['cliente']}", negrito=True),
    ]
    if dados["cpf"]:
        partes.append(_p(f"CPF: {dados['cpf']}"))
    if dados["entrevistador"]:
        partes.append(_p(f"Entrevistadora: {dados['entrevistador']}"))
    partes.append(_p(f"Gerado em {dados['gerado_em']}"))

    p = dados["progresso"]
    partes.append(
        _p(f"Respondidas {p['respondidas']} de {p['total']} perguntas ({p['percentual']}%).")
    )

    # O que impede o prosseguimento vem ANTES de tudo. Quem abre este arquivo
    # precisa ver isso na primeira tela, não na página quatro.
    if dados["impedimentos"]:
        partes += [_linha_vazia(), _p("ATENÇÃO — IMPEDIMENTO", negrito=True, tamanho=26)]
        for imp in dados["impedimentos"]:
            partes.append(_p(f"{imp['pergunta']} — respondido: {imp['resposta']}"))
            if imp["motivo"]:
                partes.append(_p(imp["motivo"]))

    if dados["faltando_obrigatorias"]:
        partes += [
            _linha_vazia(),
            _p(
                f"PENDÊNCIAS OBRIGATÓRIAS ({len(dados['faltando_obrigatorias'])})",
                negrito=True,
                tamanho=26,
            ),
        ]
        for f in dados["faltando_obrigatorias"]:
            partes.append(_p(f"• {f['pergunta']}"))

    # A síntese vem antes das 86 respostas em detalhe: é o que se lê primeiro.
    if dados.get("analise"):
        partes += _secao_analise(dados["analise"])

    for bloco in dados["blocos"]:
        partes += [_linha_vazia(), _p(bloco["titulo"].upper(), negrito=True, tamanho=26)]
        if bloco["delegado_a"]:
            partes.append(_p(f"(a cargo do {bloco['delegado_a']})"))
        if bloco["objetivo"]:
            partes.append(_p(bloco["objetivo"]))
        for item in bloco["itens"]:
            partes.append(_p(item["pergunta"], negrito=True))
            if item["respondida"]:
                partes.append(_p(item["resposta"]))
            else:
                # Sem resposta fica ESCRITO, não em branco. Um espaço vazio no
                # meio de 86 perguntas passa despercebido; "não respondido" não.
                marca = "não respondido" + (" — OBRIGATÓRIA" if item["obrigatoria"] else "")
                partes.append(_p(f"[{marca}]"))

    rodape = (
        "Relatório gerado automaticamente a partir das respostas da entrevista. "
        "Organiza o que foi dito"
    )
    rodape += (
        " e traz uma análise assistida por precedentes, que é apoio à decisão e "
        "não conclui pela viabilidade da ação — a classificação jurídica é da "
        "equipe."
        if dados.get("analise") and not dados["analise"].get("indisponivel")
        else "; não conclui pela viabilidade da ação nem classifica juridicamente "
        "o caso — essa análise é da equipe jurídica."
    )
    partes += [_linha_vazia(), _p(rodape, tamanho=18)]
    return "".join(partes)


#: As quatro partes que fazem um .docx abrir no Word. Menos que isto, ele acusa
#: arquivo corrompido sem dizer o que falta. Com emblema, entram mais duas: o
#: tipo `png` no manifesto e a relação que liga `rIdLogo` ao arquivo em `media/`.
def _partes(corpo: str, com_emblema: bool) -> dict[str, str]:
    tipo_png = '<Default Extension="png" ContentType="image/png"/>' if com_emblema else ""
    rel_logo = (
        '<Relationship Id="rIdLogo" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
        'Target="media/logo.png"/>'
        if com_emblema
        else ""
    )
    return {
        "[Content_Types].xml": (
            DECLARACAO
            + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            + tipo_png
            + '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            DECLARACAO
            + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="word/document.xml"/></Relationships>'
        ),
        "word/_rels/document.xml.rels": (
            DECLARACAO
            + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + rel_logo
            + "</Relationships>"
        ),
        "word/document.xml": (
            DECLARACAO
            + f'<w:document xmlns:w="{W}"{NS_DESENHO}><w:body>{corpo}</w:body></w:document>'
        ),
    }


def gerar_docx(
    respostas: dict[str, Any],
    codigo_roteiro: str = "empregado_publico",
    entrevistador: str = "",
    analise: dict[str, Any] | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """Devolve (arquivo, estrutura). A estrutura serve para a tela conferir.

    `analise` é o resultado do `/api/estrategia` (ver `_secao_analise`); quando
    presente, o relatório sai analisado. Ausente, sai só organizado — como antes.
    """
    dados = montar(respostas, codigo_roteiro, entrevistador)
    dados["analise"] = analise

    # O emblema é o único ponto que pode falhar por fora (PIL, fonte ausente).
    # Falhar aqui não pode custar o relatório: sem símbolo, ele ainda vale.
    emblema_png: bytes | None
    dimensao: tuple[int, int] | None
    try:
        emblema_png = marca.emblema_png()
        dimensao = marca.dimensao_emblema()
    except Exception:
        log.warning("Não foi possível montar o emblema; relatório sai sem símbolo.", exc_info=True)
        emblema_png = dimensao = None

    corpo = _corpo(dados, dimensao)
    destino = io.BytesIO()
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as saida:
        for nome, conteudo in _partes(corpo, com_emblema=emblema_png is not None).items():
            saida.writestr(nome, conteudo.encode("utf-8"))
        if emblema_png is not None:
            saida.writestr("word/media/logo.png", emblema_png)
    return destino.getvalue(), dados
