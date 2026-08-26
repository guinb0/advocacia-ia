"""Teste end-to-end: gera documentos sintéticos, roda o pipeline e confere a extração.

Rodar: .venv\\Scripts\\python.exe -m tests.test_pipeline
"""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

SAIDA = Path(__file__).resolve().parent / "amostras"
SAIDA.mkdir(exist_ok=True)


def _fonte(tamanho: int):
    for nome in ("arialbd.ttf", "arial.ttf", "segoeui.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(nome, tamanho)
        except OSError:
            continue
    return ImageFont.load_default()


def desenhar(linhas: list[tuple[str, int, int, int]], w=1000, h=640) -> bytes:
    """linhas = [(texto, x, y, tamanho_fonte)]"""
    img = Image.new("RGB", (w, h), (248, 248, 244))
    dr = ImageDraw.Draw(img)
    dr.rectangle([8, 8, w - 8, h - 8], outline=(120, 130, 150), width=3)
    for texto, x, y, tam in linhas:
        dr.text((x, y), texto, fill=(15, 20, 35), font=_fonte(tam))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ------------------------------------------------------------- amostras

CNH = desenhar([
    ("REPUBLICA FEDERATIVA DO BRASIL", 40, 30, 26),
    ("CARTEIRA NACIONAL DE HABILITACAO", 40, 66, 30),
    ("NOME", 40, 130, 20),
    ("MARIA APARECIDA DA SILVA SANTOS", 40, 156, 32),
    ("DOC. IDENTIDADE / ORG. EMISSOR / UF", 40, 214, 18),
    ("MG-12.345.678  SSP/MG", 40, 238, 26),
    ("CPF", 560, 214, 18),
    ("111.444.777-35", 560, 238, 26),
    ("DATA NASCIMENTO", 40, 296, 18),
    ("15/03/1990", 40, 320, 26),
    ("N REGISTRO", 340, 296, 18),
    ("12345678900", 340, 320, 26),
    ("VALIDADE", 640, 296, 18),
    ("10/01/2030", 640, 320, 26),
    ("FILIACAO", 40, 380, 18),
    ("JOANA PEREIRA DA SILVA", 40, 406, 26),
    ("ANTONIO CARLOS SANTOS", 40, 440, 26),
    ("CAT. HAB.", 640, 380, 18),
    ("AB", 640, 406, 30),
    ("1 HABILITACAO", 640, 460, 18),
    ("20/06/2010", 640, 484, 24),
    ("LOCAL  BELO HORIZONTE, MG", 40, 540, 22),
])

CTPS = desenhar([
    ("MINISTERIO DO TRABALHO E PREVIDENCIA SOCIAL", 40, 34, 26),
    ("CARTEIRA DE TRABALHO E PREVIDENCIA SOCIAL", 40, 74, 30),
    ("QUALIFICACAO CIVIL", 40, 130, 22),
    ("NOME", 40, 180, 20),
    ("JOSE ROBERTO DE OLIVEIRA LIMA", 40, 206, 32),
    ("N DA CARTEIRA", 40, 268, 18),
    ("1234567", 40, 292, 26),
    ("SERIE", 300, 268, 18),
    ("00123/MG", 300, 292, 26),
    ("PIS/PASEP", 560, 268, 18),
    ("120.12345.67-2", 560, 292, 26),
    ("DATA NASCIMENTO", 40, 350, 18),
    ("22/11/1985", 40, 374, 26),
    ("CPF", 340, 350, 18),
    ("111.444.777-35", 340, 374, 26),
    ("NATURALIDADE", 40, 432, 18),
    ("CONTAGEM - MG", 40, 456, 26),
    ("FILIACAO", 40, 510, 18),
    ("TEREZA DE OLIVEIRA LIMA", 40, 536, 24),
    ("SEBASTIAO LIMA FILHO", 40, 570, 24),
])

CPF_CARTAO = desenhar([
    ("MINISTERIO DA FAZENDA", 40, 40, 28),
    ("SECRETARIA DA RECEITA FEDERAL", 40, 78, 26),
    ("CADASTRO DE PESSOAS FISICAS", 40, 118, 30),
    ("NOME", 40, 200, 22),
    ("CARLOS EDUARDO FERREIRA MARTINS", 40, 230, 34),
    ("CPF", 40, 300, 22),
    ("111.444.777-35", 40, 332, 40),
    ("DATA NASCIMENTO", 40, 400, 22),
    ("07/09/1978", 40, 430, 30),
])  # altura padrão 640px: abaixo de 600 o próprio extrator reprova por resolução

TITULO = desenhar([
    ("JUSTICA ELEITORAL", 40, 40, 28),
    ("TRIBUNAL SUPERIOR ELEITORAL", 40, 76, 26),
    ("TITULO DE ELEITOR", 40, 116, 32),
    ("INSCRICAO", 40, 190, 20),
    ("1234 5678 0191", 40, 218, 34),
    ("NOME", 40, 286, 20),
    ("ANA BEATRIZ RODRIGUES COSTA", 40, 314, 30),
    ("ZONA", 40, 380, 20),
    ("0123", 40, 406, 28),
    ("SECAO", 300, 380, 20),
    ("0456", 300, 406, 28),
    ("DATA DE NASCIMENTO", 560, 380, 20),
    ("03/05/1995", 560, 406, 28),
])

DEITADA = cv2.imencode(
    ".png",
    cv2.rotate(cv2.imdecode(np.frombuffer(CNH, np.uint8), cv2.IMREAD_COLOR), cv2.ROTATE_90_COUNTERCLOCKWISE),
)[1].tobytes()

BORRADA = cv2.imencode(
    ".png",
    cv2.GaussianBlur(cv2.imdecode(np.frombuffer(CNH, np.uint8), cv2.IMREAD_COLOR), (25, 25), 0),
)[1].tobytes()

ESCURA = cv2.imencode(
    ".png",
    (cv2.imdecode(np.frombuffer(CPF_CARTAO, np.uint8), cv2.IMREAD_COLOR) * 0.18).astype(np.uint8),
)[1].tobytes()

RUIDO = cv2.imencode(".png", np.random.randint(0, 255, (700, 900, 3), dtype=np.uint8))[1].tobytes()


AMOSTRAS = [
    # (arquivo, bytes, tipo_esperado, campos_esperados, valores_exatos, campos_proibidos)
    ("cnh.png", CNH, "cnh",
     ["nome", "cpf", "cnh", "data_nascimento", "data_validade"],
     {"nome": "MARIA APARECIDA DA SILVA SANTOS",
      "cpf": "111.444.777-35",
      "cnh": "12345678900",
      "data_nascimento": "15/03/1990",
      "data_validade": "10/01/2030",
      "filiacao_1": "JOANA PEREIRA DA SILVA",    # não pode vir com o "AB" da coluna vizinha
      "filiacao_2": "ANTONIO CARLOS SANTOS",
      "orgao_emissor": "SSP/MG",
      "categoria_cnh": "AB",
      "data_primeira_habilitacao": "20/06/2010"},
     ["pis"]),                                    # o nº da CNH passa no DV do PIS: não pode virar PIS

    ("ctps.png", CTPS, "ctps",
     ["nome", "pis", "data_nascimento"],
     {"nome": "JOSE ROBERTO DE OLIVEIRA LIMA",
      "pis": "120.12345.67-2",
      "cpf": "111.444.777-35",
      "data_nascimento": "22/11/1985",
      "naturalidade": "CONTAGEM - MG",
      "numero_ctps": "1234567",
      "serie_ctps": "00123/MG"},
     []),

    ("cpf.png", CPF_CARTAO, "cpf",
     ["nome", "cpf"],
     {"nome": "CARLOS EDUARDO FERREIRA MARTINS",
      "cpf": "111.444.777-35",
      "data_nascimento": "07/09/1978"},
     []),

    ("titulo.png", TITULO, "titulo_eleitor",
     ["titulo_eleitor", "nome"],
     {"titulo_eleitor": "123456780191",
      "nome": "ANA BEATRIZ RODRIGUES COSTA",
      "zona": "0123",
      "secao": "0456"},
     []),

    # Foto deitada (celular na horizontal): o texto é lido de qualquer jeito, mas
    # sem endireitar a página as caixas saem transpostas e os rótulos trocam de valor.
    ("cnh_deitada.png", DEITADA, "cnh",
     ["nome", "cpf", "cnh", "data_nascimento", "data_validade"],
     {"nome": "MARIA APARECIDA DA SILVA SANTOS",
      "cpf": "111.444.777-35",
      "cnh": "12345678900",
      "data_nascimento": "15/03/1990",
      "data_validade": "10/01/2030"},
     ["pis"]),

    ("cnh_borrada.png", BORRADA, None, [], {}, []),
    ("cpf_escuro.png", ESCURA, None, [], {}, []),
    ("ruido.png", RUIDO, None, [], {}, []),
]


def main() -> int:
    from app.pipeline import processar

    falhas = 0
    for nome, blob, tipo_esperado, campos_esperados, valores_exatos, proibidos in AMOSTRAS:
        (SAIDA / nome).write_bytes(blob)
        print("=" * 78)
        print(f"AMOSTRA: {nome}")
        try:
            r = processar(blob, nome)
        except Exception as exc:
            print(f"  ERRO: {exc}")
            falhas += 1
            continue

        v, q = r["validacao"], r["qualidade_imagem"]
        print(f"  tipo detectado ....... {r['tipo']['codigo']} (pontos: {r['tipo']['confianca_classificacao']})")
        print(f"  veredito ............. {v['veredito']}  (dados_utilizaveis={v['dados_utilizaveis']})")
        print(f"  legibilidade ......... {q['score_legibilidade']}%  legivel={q['legivel']}")
        print(f"  confianca OCR ........ {r['ocr']['confianca_media']}  blocos={r['ocr']['blocos_detectados']}")
        print(f"  tempo ................ {r['tempo_processamento_s']}s")
        print("  campos:")
        for c in r["campos"]:
            print(f"    - {c['nome']:26} = {c['valor']!r:38} valido={c['valido']} conf={c['confianca']}")
        if v["erros"]:
            print("  erros:")
            for e in v["erros"]:
                print(f"    ! {e}")

        obtidos = {c["nome"] for c in r["campos"]}

        if tipo_esperado:
            if r["tipo"]["codigo"] != tipo_esperado:
                print(f"  >> FALHA: esperava tipo '{tipo_esperado}'")
                falhas += 1
            faltando = [c for c in campos_esperados if c not in obtidos]
            if faltando:
                print(f"  >> FALHA: campos não extraídos: {faltando}")
                falhas += 1
            if not q["legivel"]:
                print("  >> FALHA: imagem sintética limpa deveria ser legível")
                falhas += 1
            if not v["dados_utilizaveis"]:
                print("  >> FALHA: os dados de uma amostra limpa deveriam ser utilizáveis")
                falhas += 1
            if v["veredito"] != "APROVADO":
                print(f"  >> FALHA: amostra limpa deveria ser APROVADA, veio {v['veredito']}"
                      f" (avisos: {v['avisos']})")
                falhas += 1
            for c in r["campos"]:
                if c["valido"] is False:
                    print(f"  >> FALHA: campo '{c['nome']}' saiu inválido")
                    falhas += 1

            valores = {c["nome"]: c["valor"] for c in r["campos"]}
            for campo, esperado in valores_exatos.items():
                if campo not in valores:
                    print(f"  >> FALHA: campo '{campo}' não foi extraído (esperava {esperado!r})")
                    falhas += 1
                elif valores[campo] != esperado:
                    print(f"  >> FALHA: campo '{campo}' = {valores[campo]!r}, esperava {esperado!r}")
                    falhas += 1
            for campo in proibidos:
                if campo in valores:
                    print(f"  >> FALHA: campo '{campo}' não deveria existir (veio {valores[campo]!r})")
                    falhas += 1
        else:
            # Amostras degradadas nunca podem passar limpas: ou reprovam, ou saem
            # com ressalvas explícitas para o usuário.
            if v["veredito"] == "APROVADO":
                print("  >> FALHA: amostra degradada não deveria ser APROVADA")
                falhas += 1

    print("=" * 78)
    print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    print(f"Amostras salvas em: {SAIDA}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
