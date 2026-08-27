"""A análise dos documentos não deixa passar achado sem citação conferida.

O achado vai virar peça processual. Quem revisa depois não estava na conversa
nem leu o documento — para essa pessoa, "CID F43.1" inventado e "CID F43.1"
verdadeiro são indistinguíveis. Por isso a citação é conferida contra o texto do
documento APONTADO, e não contra o conjunto: citação que existe em outro anexo é
atribuição errada de prova, que é tão grave quanto invenção.

Nada aqui chama modelo: o `_chamar_modelo` é trocado por um que devolve o JSON
que se quer testar.

Rodar: .venv\Scripts\python.exe -m tests.test_analise_documentos
"""

from __future__ import annotations

from app import analise_documentos as ad


def checar(condicao: bool, descricao: str) -> bool:
    print(f"  {'PASS' if condicao else 'FALHA'} {descricao}")
    return condicao


LAUDO = "Paciente em acompanhamento. Diagnóstico: CID F43.1 — estresse pós-traumático."
CNIS = "Vinculo EMPRESA X. Afastamento de 12/03/2026 a 27/03/2026 por auxilio-doenca."

DOCUMENTOS = [
    {"id": "e1", "arquivo": "laudo.pdf", "texto": LAUDO},
    {"id": "e2", "arquivo": "cnis.png", "texto": CNIS},
]


def instalar(resposta: dict) -> list[str]:
    """Troca o modelo e devolve a lista onde as mensagens enviadas ficam."""
    enviadas: list[str] = []

    def falso(mensagem: str) -> dict:
        enviadas.append(mensagem)
        return resposta

    ad._chamar_modelo = falso  # type: ignore[assignment]
    ad._documentos_do_caso = lambda _id: list(DOCUMENTOS)  # type: ignore[assignment]
    ad._fatos_conhecidos = lambda _id: ["Ficou afastado pelo INSS?: não"]  # type: ignore[assignment]
    return enviadas


def cenario_citacao_conferida() -> int:
    falhas = 0
    instalar(
        {
            "achados": [
                # Verdadeiro: a citação está no laudo.
                {"informacao": "Diagnóstico de estresse pós-traumático",
                 "documento": "laudo.pdf", "citacao": "CID F43.1",
                 "relevancia": "sustenta o nexo", "contradiz": False},
                # Inventado: ninguém escreveu isso em documento nenhum.
                {"informacao": "Incapacidade permanente",
                 "documento": "laudo.pdf", "citacao": "incapacidade total e permanente",
                 "relevancia": "aumentaria o pedido", "contradiz": False},
                # Trocado de arquivo: a citação existe, mas no OUTRO documento.
                {"informacao": "Afastamento previdenciário",
                 "documento": "laudo.pdf", "citacao": "Afastamento de 12/03/2026",
                 "relevancia": "prova o afastamento", "contradiz": True},
            ]
        }
    )
    r = ad.analisar("caso-1")
    informacoes = [a["informacao"] for a in r["achados"]]

    falhas += not checar(
        "Diagnóstico de estresse pós-traumático" in informacoes,
        "o achado com citação real passa",
    )
    falhas += not checar(
        "Incapacidade permanente" not in informacoes,
        "o achado inventado NÃO passa",
    )
    falhas += not checar(
        "Afastamento previdenciário" not in informacoes,
        "e o atribuído ao documento errado também não",
    )
    falhas += not checar(
        r["recusados"] == 2, f"as duas recusas são contadas e mostradas ({r['recusados']})"
    )
    return falhas


def cenario_ocr_imperfeito() -> int:
    """Acento e pontuação trocados pelo OCR não podem recusar citação honesta."""
    falhas = 0
    instalar(
        {
            "achados": [
                {"informacao": "Diagnóstico registrado",
                 "documento": "laudo.pdf", "citacao": "CID F43.1 - estresse pos traumatico",
                 "relevancia": "nexo", "contradiz": False},
            ]
        }
    )
    r = ad.analisar("caso-1")
    falhas += not checar(
        len(r["achados"]) == 1,
        "citação sem acento e com hífen diferente ainda confere",
    )
    return falhas


def cenario_o_que_o_modelo_recebe() -> int:
    falhas = 0
    enviadas = instalar({"achados": []})
    ad.analisar("caso-1")
    msg = enviadas[0] if enviadas else ""
    falhas += not checar("laudo.pdf" in msg and "cnis.png" in msg, "os dois documentos vão no prompt")
    falhas += not checar("CID F43.1" in msg, "com o texto lido, não só o nome do arquivo")
    falhas += not checar(
        "Ficou afastado pelo INSS?: não" in msg,
        "e o que a entrevista já registrou, para o modelo não repetir",
    )
    return falhas


def main_teste() -> int:
    falhas = 0
    for titulo, teste in (
        ("citação é conferida contra o documento apontado", cenario_citacao_conferida),
        ("OCR imperfeito não recusa citação honesta", cenario_ocr_imperfeito),
        ("o que o modelo recebe", cenario_o_que_o_modelo_recebe),
    ):
        print(f"\n{titulo}")
        falhas += teste()
    print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
