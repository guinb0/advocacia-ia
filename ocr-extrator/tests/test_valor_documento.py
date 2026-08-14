"""Leitura do texto do OCR: para que o documento serve no caso.

O modelo é dublado. O que se protege aqui é o que faria um advogado confiar em
coisa errada: item de checklist inventado, achado sem valor, e a fronteira entre
descrever um documento e opinar sobre o mérito do pedido.

Rodar: .venv\\Scripts\\python.exe -m tests.test_valor_documento
"""

from __future__ import annotations

import json
import os

import httpx

from app import valor_documento


def checar(condicao: bool, descricao: str) -> bool:
    print(f"  {'PASS' if condicao else 'FALHA'} {descricao}")
    return condicao


#: Um laudo como o OCR o entrega: linhas soltas, ordem imperfeita, ruído.
LAUDO = {
    "texto_linhas": [
        {"texto": "CLINICA ORTOPEDICA SAO LUCAS", "confianca": 0.94},
        {"texto": "LAUDO MEDICO", "confianca": 0.97},
        {"texto": "Paciente: MARIA APARECIDA DA SILVA", "confianca": 0.91},
        {"texto": "Data: 14/03/2025", "confianca": 0.88},
        {"texto": "CID-10: M54.5 - Dor lombar baixa", "confianca": 0.93},
        {"texto": "Paciente relata dores apos esforco repetitivo no trabalho", "confianca": 0.85},
        {"texto": "Afastamento recomendado por 30 dias", "confianca": 0.90},
        {"texto": "Dr. Joao Pereira - CRM 12345", "confianca": 0.89},
    ]
}

PENDENCIAS = [
    {"codigo": "DOC.10", "nome": "CAT (Comunicação de Acidente de Trabalho)"},
    {"codigo": "DOC.13", "nome": "Laudos e exames médicos"},
    {"codigo": "DOC.11", "nome": "Boletim de ocorrência"},
]

visto: dict[str, object] = {}


def instalar_modelo(retorno: dict):
    def falso(url, **kwargs):
        visto["corpo"] = kwargs.get("json")
        visto["prompt"] = kwargs["json"]["messages"][1]["content"]
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(retorno)}}]},
            request=httpx.Request("POST", url),
        )

    valor_documento.httpx.post = falso  # type: ignore[assignment]


# ------------------------------------------------------------------- testes


def testar_leitura() -> int:
    falhas = 0
    instalar_modelo(
        {
            "documento": "Laudo médico — ortopedia",
            "serve_para": [
                {"item": "DOC.13", "porque": "É laudo com CID e recomendação de afastamento."},
            ],
            "achados": [
                {"campo": "CID", "valor": "M54.5"},
                {"campo": "Data", "valor": "14/03/2025"},
                {"campo": "CRM", "valor": "12345"},
            ],
            "atencao": ["Não menciona nexo com o trabalho de forma explícita."],
            "sugere_pedir": ["CAT correspondente ao afastamento"],
        }
    )

    r = valor_documento.ler(LAUDO, PENDENCIAS, "Acidente do Trabalho (Correios)")
    falhas += not checar(r["documento"].startswith("Laudo"), f"identificou o documento ({r['documento']})")
    falhas += not checar(
        [s["item"] for s in r["serve_para"]] == ["DOC.13"],
        "ligou ao item certo do checklist",
    )
    falhas += not checar(
        {a["campo"] for a in r["achados"]} == {"CID", "Data", "CRM"},
        "extraiu os achados que um advogado procuraria",
    )
    falhas += not checar(len(r["atencao"]) == 1, "apontou o problema do documento")
    falhas += not checar(len(r["sugere_pedir"]) == 1, "sugeriu o complementar")
    falhas += not checar(
        "não decide item do checklist" in r["aviso"],
        "e o aviso diz o que ele NÃO é",
    )

    # O prompt só leva o que está pendente — mandar os doze faria o modelo
    # "resolver" item já entregue.
    prompt = str(visto["prompt"])
    falhas += not checar("DOC.10" in prompt and "DOC.13" in prompt, "as pendências vão ao modelo")
    falhas += not checar("M54.5" in prompt, "e o texto do OCR também")
    return falhas


def testar_item_inventado() -> int:
    """Código que não estava pendente não pode aparecer como novidade."""
    falhas = 0
    instalar_modelo(
        {
            "documento": "Laudo",
            "serve_para": [
                {"item": "DOC.99", "porque": "item que não existe"},
                {"item": "DOC.03", "porque": "item que existe mas já foi entregue"},
                {"item": "DOC.13", "porque": "este estava pendente"},
            ],
            "achados": [{"campo": "", "valor": "sem campo"}, {"campo": "CID", "valor": ""}],
            "atencao": [],
            "sugere_pedir": [],
        }
    )
    r = valor_documento.ler(LAUDO, PENDENCIAS)
    falhas += not checar(
        [s["item"] for s in r["serve_para"]] == ["DOC.13"],
        f"só o item que estava pendente sobrevive ({[s['item'] for s in r['serve_para']]})",
    )
    falhas += not checar(
        r["achados"] == [], f"achado sem campo ou sem valor é descartado ({r['achados']})"
    )
    return falhas


def testar_texto_curto() -> int:
    falhas = 0
    chamou = {"n": 0}

    def contando(url, **kwargs):
        chamou["n"] += 1
        return httpx.Response(200, json={}, request=httpx.Request("POST", url))

    valor_documento.httpx.post = contando  # type: ignore[assignment]

    try:
        valor_documento.ler({"texto_linhas": [{"texto": "borrado"}]}, PENDENCIAS)
        falhas += not checar(False, "foto ilegível é recusada")
    except valor_documento.ErroValor as exc:
        falhas += not checar("ilegível" in str(exc), f"e diz por quê ({exc})")
    falhas += not checar(chamou["n"] == 0, "sem gastar chamada ao modelo")

    # Documento sem OCR nenhum.
    try:
        valor_documento.ler({}, PENDENCIAS)
        falhas += not checar(False, "extração vazia é recusada")
    except valor_documento.ErroValor:
        falhas += not checar(True, "extração vazia é recusada")
    return falhas


def testar_sem_chave() -> int:
    falhas = 0
    guardada = os.environ.get("DEEPSEEK_API_KEY")
    os.environ["DEEPSEEK_API_KEY"] = ""
    try:
        valor_documento.ler(LAUDO, PENDENCIAS)
        falhas += not checar(False, "sem chave, recusa explicando")
    except valor_documento.ErroValor as exc:
        falhas += not checar(
            "DEEPSEEK_API_KEY" in str(exc) and "checklist funciona" in str(exc),
            f"o erro diz o que falta E que o envio não foi perdido ({exc})",
        )
    finally:
        if guardada is None:
            os.environ.pop("DEEPSEEK_API_KEY", None)
        else:
            os.environ["DEEPSEEK_API_KEY"] = guardada
    return falhas


def testar_texto_do_ocr() -> int:
    falhas = 0
    t = valor_documento.texto_do_ocr(LAUDO)
    falhas += not checar("CID-10: M54.5" in t, "junta as linhas do OCR")
    falhas += not checar(
        t.index("CLINICA") < t.index("Dr. Joao"),
        "na ordem em que saíram — a ordem carrega sentido no laudo",
    )
    grande = {"texto_linhas": [{"texto": "x" * 200} for _ in range(100)]}
    falhas += not checar(
        len(valor_documento.texto_do_ocr(grande)) <= valor_documento.MAXIMO_CARACTERES,
        "e corta o prontuário de internação no teto",
    )
    return falhas


def main_teste() -> int:
    guardada = os.environ.get("DEEPSEEK_API_KEY")
    if not guardada:
        os.environ["DEEPSEEK_API_KEY"] = "chave-de-teste"
    original = valor_documento.httpx.post

    falhas = 0
    for titulo, teste in (
        ("o texto que vai para o modelo", testar_texto_do_ocr),
        ("leitura de um laudo", testar_leitura),
        ("item de checklist inventado", testar_item_inventado),
        ("foto ilegível", testar_texto_curto),
        ("sem chave", testar_sem_chave),
    ):
        print(f"\n{titulo}")
        falhas += teste()

    valor_documento.httpx.post = original
    if guardada is None:
        os.environ.pop("DEEPSEEK_API_KEY", None)
    else:
        os.environ["DEEPSEEK_API_KEY"] = guardada

    print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
