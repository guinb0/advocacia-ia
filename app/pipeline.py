"""Pipeline completo: imagem -> OCR -> campos -> validação -> JSON/XML temporário."""

from __future__ import annotations

import logging
import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from xml.dom import minidom
from xml.etree import ElementTree as ET

import cv2
import numpy as np

from . import quality
from .extractors import CAMPOS_ESPERADOS, ROTULOS_TIPO, Campo, Linha, classificar, normalizar
from .ocr_engine import motor_ativo, rodar_ocr_com_tempo

log = logging.getLogger("pipeline")


class Cronometro:
    """Acumula o tempo de cada etapa do pipeline num dicionário.

    Existe porque "o OCR levou 200s" não é diagnóstico: sem separar decodificação,
    preparo, inferência e extração não dá para saber se o custo está no modelo ou
    numa passada extra de rotação. Ver `tempo_etapas_s` na saída de `processar`.
    """

    def __init__(self) -> None:
        self.etapas: dict[str, float] = {}

    @contextmanager
    def medir(self, nome: str):
        inicio = time.perf_counter()
        try:
            yield
        finally:
            self.etapas[nome] = round(self.etapas.get(nome, 0.0) + time.perf_counter() - inicio, 3)

    def resumo(self) -> str:
        return " ".join(f"{nome}={valor:.2f}s" for nome, valor in self.etapas.items())


TMP_DIR = Path(__file__).resolve().parent.parent / "tmp"
TMP_DIR.mkdir(exist_ok=True)
TTL_SEGUNDOS = 30 * 60  # arquivos temporários expiram em 30 min


# --------------------------------------------------------------- decodificação


def decodificar(conteudo: bytes) -> np.ndarray:
    if conteudo.lstrip().startswith(b"%PDF-"):
        from .pdf import pdf_para_imagem

        return pdf_para_imagem(conteudo)

    arr = np.frombuffer(conteudo, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Arquivo não é uma imagem válida ou está corrompido.")
    return img


def _pontuar_linhas(linhas: list[Linha]) -> float:
    """Heurística para escolher a melhor rotação: caracteres ponderados pela confiança."""
    return sum(len(ln.texto) * ln.confianca for ln in linhas)


def ocr_com_rotacao(img: np.ndarray, lang: str) -> tuple[list[Linha], int, int]:
    linhas, rotacao, _, passadas = ocr_com_rotacao_medido(img, lang)
    return linhas, rotacao, passadas


def ocr_com_rotacao_medido(
    img: np.ndarray,
    lang: str,
) -> tuple[list[Linha], int, list[dict[str, float | int]], int]:
    """Roda o OCR na orientação original; se render pouco texto, testa 90/180/270.

    A Mistral reconhece orientação; esta é a rede de segurança para casos em
    que o serviço não encontra a posição correta.

    Devolve também quantas passadas de OCR foram gastas. O número importa: uma
    foto que pontua mal custa **quatro** inferências, não uma, e é essa a
    diferença entre o caso bom e o caso ruim de tempo — não o tamanho da imagem.
    """
    inicio_rotacoes = time.perf_counter()
    linhas, tempos = rodar_ocr_com_tempo(img, lang)
    tentativas: list[dict[str, float | int]] = [{**tempos, "rotacao_graus": 0}]
    melhor, melhor_rot, melhor_pt = linhas, 0, _pontuar_linhas(linhas)
    passadas = 1

    if melhor_pt < 60:  # provavelmente a foto está deitada
        for rot, code in ((90, cv2.ROTATE_90_CLOCKWISE),
                          (180, cv2.ROTATE_180),
                          (270, cv2.ROTATE_90_COUNTERCLOCKWISE)):
            # A Mistral já classifica a orientação. Esta segunda defesa não pode
            # transformar uma foto ruim em quatro inferências de ~50 segundos.
            # Zero desliga o teto para benchmarks específicos.
            limite_s = float(os.getenv("OCR_ORIENTATION_FALLBACK_BUDGET_S", "45"))
            decorrido_s = time.perf_counter() - inicio_rotacoes
            if limite_s > 0 and decorrido_s >= limite_s:
                log.warning(
                    "Interrompendo rotações extras após %.1fs (limite %.1fs).",
                    decorrido_s,
                    limite_s,
                )
                break
            try:
                cand, tempos = rodar_ocr_com_tempo(cv2.rotate(img, code), lang)
                tentativas.append({**tempos, "rotacao_graus": rot})
                passadas += 1
            except Exception as exc:
                log.warning("Falha no OCR com rotação %s: %s", rot, exc)
                continue
            pt = _pontuar_linhas(cand)
            if pt > melhor_pt:
                melhor, melhor_rot, melhor_pt = cand, rot, pt

    return melhor, melhor_rot, tentativas, passadas


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


# ------------------------------------------------------- resgate de foto ruim


#: Realces extras tentados quando a primeira leitura sai fraca, do mais suave ao
#: mais agressivo. `(sigma, amount, escala)`.
#:
#: Os números saíram de varredura nas amostras reais, não de palpite. Na CNH
#: borrada (nitidez 1.9 contra 3265 da mesma CNH limpa) a passada única extraía
#: UM campo; a união destas três extrai TRÊS. Nas amostras boas nenhuma delas muda
#: nada — 22 blocos e 342 caracteres antes e depois —, e é por isso que dá para
#: tentá-las sem risco de estragar o que já funcionava.
#:
#: Ampliar (escala 2.0) fragmenta o texto em mais caixas e derruba a confiança
#: média, mas encontra campo que os outros não encontram: na medição foi ela quem
#: trouxe o CPF. Por isso está na lista e por isso é a última.
REALCES_DE_RESGATE: tuple[tuple[float, float, float], ...] = (
    (1.5, 1.5, 1.0),
    (2.5, 2.0, 1.0),
    (2.0, 1.5, 2.0),
)

#: Teto de tempo do resgate inteiro. Documento ruim não pode prender a fila: o
#: cliente está esperando o retorno do envio, e três passadas de OCR numa foto de
#: 12 MP passam de um minuto em CPU.
#: Desligável por ambiente: se um acervo específico regredir, dá para voltar ao
#: comportamento antigo sem reverter código.
RESGATE_LIGADO = os.getenv("OCR_RESGATE", "1").strip().lower() not in {"0", "false", "nao"}

RESGATE_SEGUNDOS = float(os.getenv("OCR_RESGATE_SEGUNDOS", "45"))

#: O quanto a releitura precisa ser melhor para SUBSTITUIR um campo já extraído.
#: Ver a justificativa no ponto da troca, em `_resgatar`.
MARGEM_TROCA = 0.10
#: E o piso abaixo do qual nem com margem se troca: duas leituras ruins não se
#: corrigem uma à outra.
CONFIANCA_MINIMA_TROCA = 0.60


def _realcar(
    original: np.ndarray, sigma: float, amount: float, escala: float
) -> np.ndarray:
    """Uma variante de realce, refeita a partir da imagem ORIGINAL.

    Quando amplia, amplia ANTES de preparar: gamma e CLAHE trabalham melhor na
    resolução maior, e foi assim — e só assim — que a medição encontrou o CPF que
    a variante aplicada sobre a imagem já preparada perdia.
    """
    if escala != 1.0:
        base = cv2.resize(original, None, fx=escala, fy=escala, interpolation=cv2.INTER_CUBIC)
        base = quality.preparar_para_ocr(base, lado_maximo=int(2000 * escala))
    else:
        base = quality.preparar_para_ocr(original)
    suave = cv2.GaussianBlur(base, (0, 0), sigma)
    return cv2.addWeighted(base, 1 + amount, suave, -amount, 0)


def _merecer_resgate(campos: list, validacao: dict, tipo: str) -> bool:
    """Vale gastar mais OCR nesta imagem?

    Só quando a leitura saiu de fato incompleta. Duas condições, e nenhuma delas
    é "a foto está feia": o que importa é o resultado. Documento sem tipo
    conhecido não tem campo esperado para comparar e fica de fora — repetir OCR
    numa foto de nota fiscal não faria surgir campo de CNH.
    """
    if tipo == "desconhecido":
        return False
    esperados = validacao.get("campos_esperados") or []
    if not esperados:
        return False
    achados = sum(1 for c in campos if str(getattr(c, "valor", "") or "").strip())
    # Metade é o corte: acima disso a leitura funcionou e as variantes só
    # acrescentariam ruído de baixa confiança sobre campo que já saiu bom.
    return achados < len(esperados) * 0.5


def _resgatar(original: np.ndarray, lang: str, tipo: str, campos: list) -> tuple[list, int]:
    """Relê a imagem com outros realces e devolve a MELHOR versão de cada campo.

    NUNCA piora: um campo só é substituído por outro de confiança estritamente
    maior, e campo que já saiu continua saindo. O ganho vem do que a primeira
    passada não viu — cada realce revela caixa de texto que os outros perdem.
    """
    from .extractors import extrair_campos

    melhores = {
        c.nome: c for c in campos if str(getattr(c, "valor", "") or "").strip()
    }
    inicio = time.perf_counter()
    tentadas = 0

    for sigma, amount, escala in REALCES_DE_RESGATE:
        if time.perf_counter() - inicio > RESGATE_SEGUNDOS:
            log.info("resgate interrompido pelo teto de %.0fs", RESGATE_SEGUNDOS)
            break
        try:
            variante = _realcar(original, sigma, amount, escala)
            linhas_v, _ = rodar_ocr_com_tempo(variante, lang)
            tentadas += 1
            for campo in extrair_campos(linhas_v, tipo):
                valor = str(getattr(campo, "valor", "") or "").strip()
                if not valor:
                    continue
                atual = melhores.get(campo.nome)
                if atual is None:
                    melhores[campo.nome] = campo
                    continue
                # SUBSTITUIR exige margem, e não só ser maior.
                #
                # Confiança não é correção: na CNH borrada, uma variante trocou
                # "ARIA APARECIDA" por "BARIA APARECIDA" com confiança um pouco
                # maior — dois erros, e a troca não melhorou nada. Pior: num
                # documento que vira peça, alternar entre duas leituras erradas a
                # cada reprocessamento é ruído que ninguém consegue auditar.
                #
                # Com margem, só troca quando a nova leitura é claramente melhor.
                # O ganho de campo NOVO (o ramo acima) não tem trava nenhuma: ali
                # a alternativa é não ter o campo.
                nova, velha = float(campo.confianca or 0), float(atual.confianca or 0)
                if nova >= velha + MARGEM_TROCA and nova >= CONFIANCA_MINIMA_TROCA:
                    melhores[campo.nome] = campo
        except Exception:  # noqa: BLE001 — resgate é bônus; falhar nele não perde o que já há
            log.warning("realce de resgate falhou (sigma=%s)", sigma, exc_info=True)

    return list(melhores.values()), tentadas


def processar(
    conteudo: bytes,
    nome_arquivo: str,
    lang: str = "pt",
    tipo_forcado: str | None = None,
    *,
    gerar_arquivos_temporarios: bool = True,
) -> dict:
    inicio = time.perf_counter()
    crono = Cronometro()

    with crono.medir("decodificar"):
        original = decodificar(conteudo)
    h, w = original.shape[:2]

    with crono.medir("preparar"):
        para_ocr = original
        # Nome, endereço, CEP e datas ficam no cabeçalho das contas. A parte
        # inferior traz tabelas e QR code que não alimentam o checklist, mas
        # custam reconhecimento. Mantém a imagem original para avaliar qualidade.
        if tipo_forcado == "comprovante_residencia":
            try:
                proporcao = float(os.getenv("OCR_COMPROVANTE_ALTURA", "0.55"))
            except ValueError:
                proporcao = 1.0
            if 0.4 <= proporcao < 1.0:
                para_ocr = original[: max(1, int(original.shape[0] * proporcao)), :]
        preparada = quality.preparar_para_ocr(para_ocr)

    with crono.medir("ocr"):
        linhas, rotacao, tentativas_ocr, passadas = ocr_com_rotacao_medido(preparada, lang)

    textos = [ln.texto for ln in linhas]
    confiancas = [ln.confianca for ln in linhas if ln.confianca > 0]
    conf_media = float(np.mean(confiancas)) if confiancas else None
    qtd_caracteres = sum(len(t) for t in textos)

    with crono.medir("qualidade"):
        qual = quality.avaliar(original, conf_media, len(linhas), qtd_caracteres)

    texto_norm = "\n".join(normalizar(t) for t in textos)

    # A classificação roda SEMPRE, mesmo com tipo forçado. Forçar melhora a extração
    # (diz quais campos procurar), mas se substituísse o palpite do classificador não
    # sobraria como detectar que veio o arquivo errado — e é justamente disso que o
    # checklist depende para acusar troca de documento.
    with crono.medir("classificar"):
        tipo_detectado, pontos, todos = classificar(texto_norm)
    forcado = bool(tipo_forcado and tipo_forcado in ROTULOS_TIPO)
    tipo = tipo_forcado if forcado else tipo_detectado

    from .extractors import extrair_campos

    with crono.medir("extrair"):
        campos = extrair_campos(linhas, tipo)
        validacao = montar_validacao(tipo, campos, qual)

    # SEGUNDA CHANCE PARA FOTO RUIM
    #
    # Uma passada de OCR lê a imagem de um jeito só. Numa foto borrada isso custa
    # caro: medido na CNH borrada do acervo, a passada única extraía 1 dos 11
    # campos que a mesma CNH limpa entrega. Reler com outros realces e ficar com a
    # melhor versão de cada campo levou esse número a 3 — cada realce revela caixa
    # de texto que os outros perdem, e nenhum deles muda o resultado de documento
    # que já saiu bom.
    #
    # Só roda quando a leitura saiu de fato incompleta (ver `_merecer_resgate`), e
    # o `montar_validacao` é refeito depois porque completude e veredito mudam com
    # os campos novos.
    resgate = {"tentado": False, "realces": 0, "campos_antes": len(campos)}
    if RESGATE_LIGADO and _merecer_resgate(campos, validacao, tipo):
        with crono.medir("resgate"):
            campos, realces = _resgatar(para_ocr, lang, tipo, campos)
            validacao = montar_validacao(tipo, campos, qual)
        resgate.update({"tentado": True, "realces": realces, "campos_depois": len(campos)})
        log.info(
            "resgate em %s: %d -> %d campo(s) em %d realce(s)",
            nome_arquivo, resgate["campos_antes"], len(campos), realces,
        )

    # Um documento jurídico pode não ter campos cadastrais conhecidos e ainda
    # conter fatos, fundamentos, pedidos, datas e provas essenciais. Este sinal
    # é calculado SEMPRE (antes ficava acidentalmente dentro do bloco de resgate).
    texto_utilizavel = bool(
        qual.legivel
        and qtd_caracteres >= 80
        and (conf_media is None or conf_media >= 0.55)
    )
    validacao["texto_utilizavel"] = texto_utilizavel
    validacao["caracteres_aproveitaveis"] = qtd_caracteres
    if texto_utilizavel and not campos:
        validacao["veredito"] = "APROVADO_COM_RESSALVAS"
        validacao["resumo"] = (
            "Texto integral extraído e preservado para análise jurídica. "
            "Este documento não possui campos cadastrais estruturados conhecidos."
        )
        validacao["erros"] = [
            erro for erro in validacao.get("erros", [])
            if not erro.startswith("Nenhum campo estruturado")
        ]

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
            "motor": motor_ativo(),
            "idioma": lang,
            "confianca_media": round(conf_media, 4) if conf_media is not None else None,
            "blocos_detectados": len(linhas),
            "caracteres_detectados": qtd_caracteres,
            "passadas": passadas,
            # Diz se a foto precisou de segunda chance e o que ela rendeu. Sem
            # isto, "por que este documento demorou 40s" não tem resposta no log.
            "resgate": resgate,
            "tentativas": [
                {k: round(v, 3) if isinstance(v, float) else v for k, v in tentativa.items()}
                for tentativa in tentativas_ocr
            ],
        },
        "texto_linhas": [{"texto": ln.texto, "confianca": round(ln.confianca, 4)} for ln in linhas],
        "texto_completo": "\n".join(textos),
    }

    if gerar_arquivos_temporarios:
        with crono.medir("salvar"):
            doc["arquivos_temporarios"] = salvar_temporarios(doc)

    doc["tempo_etapas_s"] = crono.etapas
    log.info(
        "processado %s: total=%.2fs passadas_ocr=%d entrada=%dx%d %s",
        nome_arquivo, time.perf_counter() - inicio, passadas, w, h, crono.resumo(),
    )
    return doc
