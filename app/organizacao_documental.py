"""Organização física dos documentos (Etapas 4 e 5 da skill documental).

A skill manda: (1) parar e perguntar ANTES de organizar; (2) 1 documento = 1 PDF; (3) nome, ordem e
numeração por regras dela; (4) duplicado nunca é descartado; (5) entregar Entrevista.pdf e Checklist.pdf.

Este módulo é o ADAPTADOR que executa isso:
- o plano nasce da análise (`analise_documental`), não de regra própria;
- ordem, numeração e nome do arquivo vêm dos SCRIPTS da skill (`montar.ordenar_e_numerar`,
  `montar.nome_arquivo`, `montar.montar_documento`), importados do disco;
- o original NUNCA é alterado: as páginas são rasterizadas em pasta de trabalho e o resultado vai
  para `dados/organizado/<caso>/`; guardamos o hash de cada original antes e depois;
- nada roda sem confirmação humana registrada (`confirmar`).

Único desvio do que a skill descreve: `inspecionar.py` rasteriza PDF com `pdftoppm` (poppler), que
a imagem de produção não instala. Aqui a rasterização usa `pypdfium2` (dependência que o projeto já
tem). O tratamento de imagem e a montagem continuam sendo os da skill.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import logging
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import analise_documental, armazenamento, skill_de_arquivo

log = logging.getLogger("organizacao_documental")

_EXT_IMAGEM = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
DIR_ORGANIZADO = armazenamento.DIR_DADOS / "organizado"


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _scripts():
    """Importa `comum` e `montar` da PRÓPRIA skill (a skill é a autoridade de nome/ordem/tratamento)."""
    skill = skill_de_arquivo.carregar(analise_documental.NOME_DA_SKILL)
    pasta = str(skill.scripts())
    if pasta not in sys.path:
        sys.path.insert(0, pasta)
    modulos = {}
    for nome in ("comum", "montar"):
        spec = importlib.util.spec_from_file_location(f"skill_doc_{nome}", skill.scripts() / f"{nome}.py")
        modulo = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        sys.modules[f"skill_doc_{nome}"] = modulo
        if nome == "montar":
            sys.modules["comum"] = modulos["comum"]  # `montar` faz `import comum`
        spec.loader.exec_module(modulo)  # type: ignore[union-attr]
        modulos[nome] = modulo
    return modulos["comum"], modulos["montar"]


def _bytes_do_original(entrega_id: str) -> tuple[bytes, str]:
    caminho = armazenamento.caminho_duravel_da_entrega(entrega_id)
    if caminho and caminho.exists():
        return caminho.read_bytes(), caminho.name
    entrega = armazenamento.obter_entrega(entrega_id) or {}
    conteudo = armazenamento.conteudo_arquivo_entrega(entrega)
    if conteudo is None:
        raise FileNotFoundError(f"original da entrega {entrega_id} indisponível")
    return conteudo, str(entrega.get("arquivo") or entrega_id)


def _paginas_do_original(conteudo: bytes, nome: str, destino: Path, base: str, dpi: int) -> list[Path]:
    """Uma imagem por página, em pasta de trabalho (o original não é tocado)."""
    destino.mkdir(parents=True, exist_ok=True)
    if nome.lower().endswith(".pdf") or conteudo[:4] == b"%PDF":
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(conteudo)
        saidas = []
        for i in range(len(pdf)):
            imagem = pdf[i].render(scale=dpi / 72).to_pil().convert("RGB")
            alvo = destino / f"{base}_p{i + 1:03d}.png"
            imagem.save(alvo)
            saidas.append(alvo)
        return saidas
    alvo = destino / f"{base}_p001{Path(nome).suffix.lower() or '.png'}"
    alvo.write_bytes(conteudo)
    return [alvo]


# ------------------------------------------------------------------ plano + parada obrigatória

def _nomes_com_duplicados(documentos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Plano no formato do `montar.py`: duplicado vira `<nome do principal> (Duplicado[ N])`."""
    por_id = {d["documento_id"]: d for d in documentos}
    contagem: dict[str, int] = {}
    saida = []
    for d in documentos:
        # A skill escreve o nome em Title Case com espaços (SKILL.md/`montar.normalizar_nome`); o
        # `references/nomenclatura.md` dela ainda mostra a forma antiga `NOME_COM_UNDERSCORE` e o
        # modelo às vezes a segue. Sublinhado vira espaço para o script da skill formatar certo.
        nome = (d.get("nome_sugerido") or d.get("tipo") or "Documento").replace("_", " ").strip()
        principal = por_id.get(d.get("duplicado_de") or "")
        if principal:
            base = (principal.get("nome_sugerido") or principal.get("tipo") or "Documento").replace("_", " ").strip()
            contagem[base] = contagem.get(base, 0) + 1
            # minúsculo de propósito: `montar.nome_base` só reconhece "(duplicado" assim; o nome final
            # sai "(Duplicado)" pela normalização da própria skill.
            nome = f"{base} (duplicado{'' if contagem[base] == 1 else f' {contagem[base]}'})"
        saida.append({"nome": nome, "pessoal": bool(d.get("pessoal")) and not principal, "data": d.get("data") or "",
                      "documento_id": d["documento_id"], "arquivo_original": d["arquivo"]})
    return saida


def preparar(caso_id: str, *, store: analise_documental.Armazenamento | None = None) -> dict[str, Any]:
    """Monta o plano e PARA: status `aguardando_confirmacao`. Nada é gerado aqui."""
    store = store or analise_documental.armazenamento_padrao()
    registro = analise_documental.obter(caso_id, store=store)
    if not registro or registro.get("status") != "ready" or not isinstance(registro.get("resultado"), dict):
        raise ValueError("A análise documental ainda não está pronta.")
    resultado = registro["resultado"]
    comum, montar = _scripts()
    plano_docs = _nomes_com_duplicados(resultado["documentos"])
    numerados = montar.ordenar_e_numerar([dict(d) for d in plano_docs])
    itens = [{
        "documento_id": d["documento_id"], "arquivo_original": d["arquivo_original"],
        "nome_final": montar.nome_arquivo(d) + ".pdf", "duplicado": montar.eh_duplicado(d),
        "pessoal": d.get("pessoal", False), "data": d.get("data", ""),
    } for d in numerados]
    ident = {d["documento_id"]: d for d in resultado["documentos"]}
    resumo = {
        "documentos": itens,
        "duplicados": [i for i in itens if i["duplicado"]],
        "problemas": [{"documento_id": d["documento_id"], "arquivo": d["arquivo"], "problema": d.get("problema") or "sem texto lido"}
                      for d in resultado["documentos"] if not d.get("legivel")],
        "nao_identificados": [d["arquivo"] for d in resultado["documentos"] if d.get("tipo") == "NÃO IDENTIFICADO"],
        "arquivos_extras": ["Entrevista.pdf", "Checklist.pdf"],
        "exclusoes": "Nenhum documento será excluído; duplicados são mantidos como arquivo próprio. Exclusão só com autorização expressa.",
    }
    registro_org = {"caso_id": caso_id, "analise_id": registro["id"], "status": "aguardando_confirmacao",
                    "plano": {"documentos": plano_docs, "resumo": resumo}, "resultado": None}
    store.salvar_organizacao(registro_org)
    return registro_org


# ------------------------------------------------------------------ execução (só após confirmação)

def confirmar(caso_id: str, usuario: str, *, store: analise_documental.Armazenamento | None = None) -> dict[str, Any]:
    store = store or analise_documental.armazenamento_padrao()
    org = store.organizacao(caso_id)
    if not org or org.get("status") not in ("aguardando_confirmacao", "confirmada", "erro"):
        raise ValueError("Não há organização aguardando confirmação. Gere o plano primeiro.")
    plano = org["plano"]
    if isinstance(plano, str):
        import json as _json
        plano = _json.loads(plano)
    org = {**org, "plano": plano, "status": "confirmada", "confirmada_por": usuario, "confirmada_em": _agora()}
    store.salvar_organizacao(org)
    try:
        resultado = executar(caso_id, plano["documentos"], store=store)
    except Exception as erro:  # noqa: BLE001
        log.exception("organização do caso %s falhou", caso_id)
        store.salvar_organizacao({**org, "status": "erro", "resultado": {"erro": f"{type(erro).__name__}: {erro}"}})
        raise
    concluida = {**org, "status": "concluida", "resultado": resultado}
    store.salvar_organizacao(concluida)
    return concluida


def executar(caso_id: str, plano_docs: list[dict[str, Any]], *, store: analise_documental.Armazenamento | None = None) -> dict[str, Any]:
    comum, montar = _scripts()
    saida = DIR_ORGANIZADO / caso_id
    if saida.exists():
        shutil.rmtree(saida)  # só a pasta de DERIVADOS; nunca os originais
    saida.mkdir(parents=True)
    hashes_antes: dict[str, str] = {}
    documentos_montar: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="orgdoc_") as tmp:
        trabalho = Path(tmp)
        for d in plano_docs:
            conteudo, nome = _bytes_do_original(d["documento_id"])
            hashes_antes[d["documento_id"]] = hashlib.sha256(conteudo).hexdigest()
            paginas = _paginas_do_original(conteudo, nome, trabalho / "paginas", comum.normalizar_nome(d["documento_id"])[:20].replace(" ", "_"), comum.DPI_PADRAO)
            documentos_montar.append({"nome": d["nome"], "pessoal": d.get("pessoal", False), "data": d.get("data", ""),
                                      "paginas": [{"arquivo": str(p)} for p in paginas], "_id": d["documento_id"]})
        ordenados = montar.ordenar_e_numerar(documentos_montar)
        nomes = [montar.nome_arquivo(d) for d in ordenados]
        repetidos = {n for n in nomes if nomes.count(n) > 1}
        if repetidos:
            raise ValueError(f"nomes de arquivo repetidos no plano: {sorted(repetidos)}")
        padroes = dict(montar.PADROES)
        gerados = [montar.montar_documento(d, padroes, saida) for d in ordenados]
    for d, g in zip(ordenados, gerados):
        g["documento_id"] = d["_id"]
        g["arquivo"] = g["arquivo"].name if g.get("arquivo") else None
    # o original não pode ter mudado
    hashes_depois = {i: hashlib.sha256(_bytes_do_original(i)[0]).hexdigest() for i in hashes_antes}
    extras = _gerar_extras(caso_id, saida, [g["arquivo"] for g in gerados if g["arquivo"]], store=store)
    return {"pasta": str(saida), "arquivos": gerados, "extras": extras, "originais_preservados": hashes_antes == hashes_depois,
            "hashes_originais": hashes_antes, "gerado_em": _agora()}


# ------------------------------------------------------------------ Entrevista.pdf e Checklist.pdf

def _gerar_extras(caso_id: str, saida: Path, arquivos_doc: list[str], *, store) -> list[str]:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table

    registro = analise_documental.obter(caso_id, store=store)
    r = (registro or {}).get("resultado") or {}
    estilos = getSampleStyleSheet()

    def p(texto: str, estilo: str = "BodyText") -> Paragraph:
        seguro = str(texto).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return Paragraph(seguro, estilos[estilo])

    def pdf(nome: str, blocos: list[Any]) -> None:
        SimpleDocTemplate(str(saida / nome), pagesize=A4, title=nome.removesuffix(".pdf")).build(blocos)

    # ---- Entrevista.pdf: a análise completa (conteúdo integral da Etapa 3)
    b: list[Any] = [p("Análise do caso", "Title")]
    resumo = r.get("resumo_do_caso") or {}
    b += [p("1. Resumo executivo", "Heading2"), p(resumo.get("questao_central") or ""), p("Objetivo do cliente: " + (resumo.get("objetivo_do_cliente") or ""))]
    for c in resumo.get("fatos_cronologicos") or []:
        b.append(p(f"{c.get('data', '')} — {c.get('fato', '')}"))
    b.append(p("2. Possibilidades jurídicas", "Heading2"))
    for h in r.get("hipoteses_juridicas") or []:
        b += [p(h.get("hipotese") or "", "Heading3"), p("Objeto: " + str(h.get("objeto") or "")),
              p("Fundamento legal (a confirmar): " + str(h.get("fundamento_legal") or "")),
              p("Pontos fortes: " + "; ".join(map(str, h.get("pontos_fortes") or []))),
              p("Pontos fracos: " + "; ".join(map(str, h.get("pontos_fracos") or []))),
              p("Probabilidade prática: " + str(h.get("probabilidade_pratica") or ""))]
    b.append(p("3. Riscos", "Heading2"))
    b += [p(f"{x.get('nivel', '')}: {x.get('risco', '')}") for x in r.get("riscos") or []]
    b.append(p("4. Análise documento a documento", "Heading2"))
    for d in r.get("documentos") or []:
        b += [p(f"{d['tipo']} — {d['arquivo']}", "Heading3"), p("Pontos fortes: " + "; ".join(d["pontos_fortes"])),
              p("Vulnerabilidades: " + "; ".join(d["vulnerabilidades"])), p(f"Atualização: {d['atualizacao']} — {d['motivo_atualizacao']}")]
    b.append(p("5. Próximos passos", "Heading2"))
    b += [p("• " + x) for x in r.get("proximos_passos") or []]
    pdf("Entrevista.pdf", b)

    # ---- Checklist.pdf: lista marcável + observações por hipótese
    b = [p("Checklist de documentação", "Title")]
    linhas = []
    por_arquivo = {d["arquivo"]: d for d in r.get("documentos") or []}
    for arq in arquivos_doc:
        b.append(p(f"☐ {arq.removesuffix('.pdf')} — presente"))
    for f in r.get("documentos_faltantes") or []:
        marca = {"COMPROMETE": "COMPROMETE", "ERA_MELHOR_TER": "ERA MELHOR TER, MAS PODE PASSAR", "NAO_INTERFERE": "NÃO INTERFERE"}[f["classificacao"]]
        b.append(p(f"☐ {f['documento']} — faltando ({marca}) — para: {f['hipotese']}. Como obter: {f['como_obter']}"))
    b.append(Spacer(1, 12))
    b.append(p("OBSERVAÇÕES", "Heading2"))
    for h in r.get("hipoteses_juridicas") or []:
        faltam = [f["documento"] for f in r.get("documentos_faltantes") or [] if f["hipotese"].lower() in str(h.get("hipotese") or "").lower() or str(h.get("hipotese") or "").lower() in f["hipotese"].lower()]
        b.append(p(f"[{h.get('hipotese')}]", "Heading3"))
        b.append(p("Documentação completa para o protocolo." if not faltam else "Cabe, mas é preciso obter: " + "; ".join(faltam)))
    pdf("Checklist.pdf", b)
    return ["Entrevista.pdf", "Checklist.pdf"]
