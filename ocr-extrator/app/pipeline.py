"""Pipeline completo: imagem -> OCR -> campos -> validação -> JSON/XML temporário."""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from xml.dom import minidom
from xml.etree import ElementTree as ET

import cv2
import numpy as np

from . import quality
from .extractors import CAMPOS_ESPERADOS, ROTULOS_TIPO, Campo, Linha, classificar, normalizar
from .ocr_engine import rodar_ocr

log = logging.getLogger("pipeline")

TMP_DIR = Path(__file__).resolve().parent.parent / "tmp"
TMP_DIR.mkdir(exist_ok=True)
TTL_SEGUNDOS = 30 * 60  # arquivos temporários expiram em 30 min


# --------------------------------------------------------------- decodificação


def decodificar(conteudo: bytes) -> np.ndarray:
    arr = np.frombuffer(conteudo, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Arquivo não é uma imagem válida ou está corrompido.")
    return img


def _pontuar_linhas(linhas: list[Linha]) -> float:
    """Heurística para escolher a melhor rotação: caracteres ponderados pela confiança."""
    return sum(len(ln.texto) * ln.confianca for ln in linhas)


def ocr_com_rotacao(img: np.ndarray, lang: str) -> tuple[list[Linha], int]:
    """Roda o OCR na orientação original; se render pouco texto, testa 90/180/270.

    O PaddleOCR já endireita a página sozinho (`use_doc_orientation_classify`);
    isto aqui é a rede de segurança para quando o classificador erra.
    """
    linhas = rodar_ocr(img, lang)
    melhor, melhor_rot, melhor_pt = linhas, 0, _pontuar_linhas(linhas)

    if melhor_pt < 60:  # provavelmente a foto está deitada
        for rot, code in ((90, cv2.ROTATE_90_CLOCKWISE),
                          (180, cv2.ROTATE_180),
                          (270, cv2.ROTATE_90_COUNTERCLOCKWISE)):
            try:
                cand = rodar_ocr(cv2.rotate(img, code), lang)
            except Exception as exc:
                log.warning("Falha no OCR com rotação %s: %s", rot, exc)
                continue
            pt = _pontuar_linhas(cand)
            if pt > melhor_pt:
                melhor, melhor_rot, melhor_pt = cand, rot, pt

    return melhor, melhor_rot


# ------------------------------------------------------------------ validação


def montar_validacao(tipo: str, campos: list[Campo], qual: quality.Qualidade) -> dict:
    encontrados = {c.nome for c in campos}
    esperados = CAMPOS_ESPERADOS.get(tipo, [])
    faltando = [c for c in esperados if c not in encontrados]

    invalidos = [c.nome for c in campos if c.valido is False]
    baixa_confianca = [c.nome for c in campos if 0 < c.confianca < 0.75]

    completude = 100 if not esperados else int(round((len(esperados) - len(faltando)) / len(esperados) * 100))

    erros: list[str] = []
    avisos: list[str] = []

    if not qual.legivel:
        erros.append("A imagem não atingiu o nível mínimo de legibilidade para uma extração confiável.")
    erros.extend(qual.problemas if not qual.legivel else [])
    if qual.legivel:
        avisos.extend(qual.problemas)

    if tipo == "desconhecido":
        avisos.append("Não foi possível identificar o tipo do documento — os campos foram extraídos genericamente.")
    for nome in faltando:
        erros.append(f"Campo obrigatório não localizado para este tipo de documento: '{nome}'.")
    for nome in invalidos:
        erros.append(f"Campo '{nome}' foi lido, mas falhou na validação.")
    for nome in baixa_confianca:
        avisos.append(f"Campo '{nome}' foi lido com baixa confiança pelo OCR — confira manualmente.")

    if not campos:
        erros.append("Nenhum campo estruturado foi extraído da imagem.")

    # Os dados servem para uso automático: nada faltando e nada reprovado no DV.
    dados_utilizaveis = qual.legivel and not faltando and not invalidos and bool(campos)
    # A foto em si não tem nenhuma ressalva de qualidade nem campo duvidoso.
    sem_ressalvas = not qual.problemas and not baixa_confianca and tipo != "desconhecido"

    if not qual.legivel or not campos:
        veredito = "REPROVADO"
        resumo = "Não foi possível extrair os dados com segurança — solicite uma nova foto ao usuário."
    elif dados_utilizaveis and sem_ressalvas:
        veredito = "APROVADO"
        resumo = "Documento legível e com todos os campos esperados extraídos e validados."
    elif dados_utilizaveis:
        veredito = "APROVADO_COM_RESSALVAS"
        resumo = ("Todos os campos esperados foram extraídos e validados, mas a foto tem "
                  "problemas de qualidade — confira os valores antes de usar.")
    else:
        veredito = "APROVADO_COM_RESSALVAS"
        resumo = "Extração parcial: a imagem é legível, mas há campos faltando ou inconsistentes."

    return {
        "veredito": veredito,
        "resumo": resumo,
        "aprovado": veredito == "APROVADO",
        "dados_utilizaveis": dados_utilizaveis,
        "imagem_legivel": qual.legivel,
        "score_legibilidade": qual.score,
        "completude_percentual": completude,
        "campos_esperados": esperados,
        "campos_faltando": faltando,
        "campos_invalidos": invalidos,
        "campos_baixa_confianca": baixa_confianca,
        "erros": erros,
        "avisos": avisos,
        "sugestoes": qual.sugestoes,
    }


# ------------------------------------------------------------------- XML


def _para_xml(doc: dict) -> str:
    raiz = ET.Element("documento")
    ET.SubElement(raiz, "id").text = str(doc["id"])
    ET.SubElement(raiz, "arquivo").text = str(doc.get("arquivo", ""))
    ET.SubElement(raiz, "processado_em").text = str(doc["processado_em"])

    tipo = ET.SubElement(raiz, "tipo")
    ET.SubElement(tipo, "codigo").text = str(doc["tipo"]["codigo"])
    ET.SubElement(tipo, "descricao").text = str(doc["tipo"]["descricao"])
    ET.SubElement(tipo, "confianca_classificacao").text = str(doc["tipo"]["confianca_classificacao"])

    campos = ET.SubElement(raiz, "campos")
    for c in doc["campos"]:
        el = ET.SubElement(campos, "campo", {"nome": str(c["nome"])})
        ET.SubElement(el, "rotulo").text = str(c["rotulo"])
        ET.SubElement(el, "valor").text = str(c["valor"])
        ET.SubElement(el, "confianca_ocr").text = str(c["confianca"])
        ET.SubElement(el, "valido").text = ("" if c["valido"] is None else str(c["valido"]).lower())
        if c.get("observacao"):
            ET.SubElement(el, "observacao").text = str(c["observacao"])

    val = doc["validacao"]
    ev = ET.SubElement(raiz, "validacao")
    for chave in ("veredito", "resumo", "aprovado", "dados_utilizaveis", "imagem_legivel",
                  "score_legibilidade", "completude_percentual"):
        ET.SubElement(ev, chave).text = str(val[chave]).lower() if isinstance(val[chave], bool) else str(val[chave])
    for chave, item in (("campos_faltando", "campo"), ("campos_invalidos", "campo"),
                        ("erros", "erro"), ("avisos", "aviso"), ("sugestoes", "sugestao")):
        cont = ET.SubElement(ev, chave)
        for v in val[chave]:
            ET.SubElement(cont, item).text = str(v)

    q = doc["qualidade_imagem"]
    eq = ET.SubElement(raiz, "qualidade_imagem")
    ET.SubElement(eq, "score_legibilidade").text = str(q["score_legibilidade"])
    ET.SubElement(eq, "legivel").text = str(q["legivel"]).lower()
    ems = ET.SubElement(eq, "metricas")
    for m in q["metricas"]:
        em = ET.SubElement(ems, "metrica", {"nome": str(m["nome"])})
        ET.SubElement(em, "valor").text = str(m["valor"])
        ET.SubElement(em, "score").text = str(m["score"])
        ET.SubElement(em, "ok").text = str(m["ok"]).lower()
        ET.SubElement(em, "mensagem").text = str(m["mensagem"])

    et = ET.SubElement(raiz, "texto_bruto")
    for ln in doc["texto_linhas"]:
        ET.SubElement(et, "linha", {"confianca": str(ln["confianca"])}).text = str(ln["texto"])

    xml = ET.tostring(raiz, encoding="unicode")
    return minidom.parseString(xml).toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")


# ------------------------------------------------- arquivos temporários


def limpar_temporarios() -> int:
    """Remove arquivos temporários expirados. Devolve quantos foram apagados."""
    agora = time.time()
    removidos = 0
    for p in TMP_DIR.glob("*.*"):
        try:
            if agora - p.stat().st_mtime > TTL_SEGUNDOS:
                p.unlink()
                removidos += 1
        except OSError:
            pass
    return removidos


def salvar_temporarios(doc: dict) -> dict:
    import json

    limpar_temporarios()
    doc_id = doc["id"]

    caminho_json = TMP_DIR / f"{doc_id}.json"
    caminho_json.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    caminho_xml = TMP_DIR / f"{doc_id}.xml"
    caminho_xml.write_text(_para_xml(doc), encoding="utf-8")

    return {
        "json": f"/api/temp/{doc_id}.json",
        "xml": f"/api/temp/{doc_id}.xml",
        "expira_em_segundos": TTL_SEGUNDOS,
    }


# -------------------------------------------------------------- pipeline


def processar(conteudo: bytes, nome_arquivo: str, lang: str = "pt", tipo_forcado: str | None = None) -> dict:
    inicio = time.perf_counter()

    original = decodificar(conteudo)
    h, w = original.shape[:2]
    preparada = quality.preparar_para_ocr(original)

    linhas, rotacao = ocr_com_rotacao(preparada, lang)

    textos = [ln.texto for ln in linhas]
    confiancas = [ln.confianca for ln in linhas if ln.confianca > 0]
    conf_media = float(np.mean(confiancas)) if confiancas else None
    qtd_caracteres = sum(len(t) for t in textos)

    qual = quality.avaliar(original, conf_media, len(linhas), qtd_caracteres)

    texto_norm = "\n".join(normalizar(t) for t in textos)

    # A classificação roda SEMPRE, mesmo com tipo forçado. Forçar melhora a extração
    # (diz quais campos procurar), mas se substituísse o palpite do classificador não
    # sobraria como detectar que veio o arquivo errado — e é justamente disso que o
    # checklist depende para acusar troca de documento.
    tipo_detectado, pontos, todos = classificar(texto_norm)
    forcado = bool(tipo_forcado and tipo_forcado in ROTULOS_TIPO)
    tipo = tipo_forcado if forcado else tipo_detectado

    from .extractors import extrair_campos

    campos = extrair_campos(linhas, tipo)
    validacao = montar_validacao(tipo, campos, qual)

    doc = {
        "id": str(uuid.uuid4()),
        "arquivo": nome_arquivo,
        "processado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tempo_processamento_s": round(time.perf_counter() - inicio, 2),
        "imagem": {
            "largura": w,
            "altura": h,
            "rotacao_aplicada_graus": rotacao,
            "tamanho_bytes": len(conteudo),
        },
        "tipo": {
            # `codigo` é o tipo usado na extração; `detectado` é o que o classificador
            # leu sozinho. Iguais quando ninguém força o tipo.
            "codigo": tipo,
            "descricao": ROTULOS_TIPO.get(tipo, tipo),
            "detectado": tipo_detectado,
            "descricao_detectado": ROTULOS_TIPO.get(tipo_detectado, tipo_detectado),
            "confianca_classificacao": pontos,
            "pontuacoes": todos,
            "forcado_pelo_usuario": forcado,
        },
        "campos": [c.to_dict() for c in campos],
        "validacao": validacao,
        "qualidade_imagem": qual.to_dict(),
        "ocr": {
            "motor": "PaddleOCR",
            "idioma": lang,
            "confianca_media": round(conf_media, 4) if conf_media is not None else None,
            "blocos_detectados": len(linhas),
            "caracteres_detectados": qtd_caracteres,
        },
        "texto_linhas": [{"texto": ln.texto, "confianca": round(ln.confianca, 4)} for ln in linhas],
        "texto_completo": "\n".join(textos),
    }

    doc["arquivos_temporarios"] = salvar_temporarios(doc)
    return doc
