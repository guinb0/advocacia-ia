"""O tom de cada aviso: nota de rotina é "info" (quieta), problema é "atencao".

Foi o que separou a tela de "amarelo enchendo o saco" de uma tela em que só o
que precisa de ação chama atenção. Roda como script:

    PYTHONPATH=. .venv/Scripts/python.exe tests/test_avisos_tom.py
"""

from __future__ import annotations

from app import casos
from app.categorias import ItemChecklist


def checar(condicao: bool, descricao: str) -> int:
    print(f"  {'PASS' if condicao else '>> FALHA'} {descricao}")
    return 0 if condicao else 1


ITEM = ItemChecklist(
    codigo="DOC.10",
    numero=10,
    nome="Laudo médico",
    obrigatorio=True,
    tipo_ocr=None,
)


def _entrega(**extra) -> dict:
    base = {
        "status_proc": "pronto",
        "tipo_confere": None,
        "dados_utilizaveis": True,
        "texto_utilizavel": True,
        "itens_atendidos": [],
        "confirmado_manual": False,
    }
    base.update(extra)
    return base


def _tom(aviso_texto_contem: str, avisos: list[dict]) -> str | None:
    for a in avisos:
        if aviso_texto_contem.lower() in a["texto"].lower():
            return a["tom"]
    return None


def main_teste() -> int:
    falhas = 0

    # Classificação semântica é nota de rotina — não pode ser amarela.
    semantico = casos._avisos_da_entrega(
        _entrega(roteamento_origem="semantico", roteamento_motivo="parece um laudo"),
        ITEM,
    )
    falhas += checar(_tom("Classificado automaticamente", semantico) == "info",
                     "classificação semântica é nota 'info', não alerta amarelo")

    # Possível troca de arquivo é problema — precisa chamar atenção.
    troca = casos._avisos_da_entrega(_entrega(tipo_confere=False, tipo_detectado="cnh"), ITEM)
    falhas += checar(_tom("troca de arquivo", troca) == "atencao",
                     "possível troca de arquivo fica em 'atencao'")

    # Falha de leitura é dura — tom crítico.
    erro = casos._avisos_da_entrega(_entrega(status_proc="erro", erro_proc="pdf corrompido"), ITEM)
    falhas += checar(_tom("Não foi possível ler", erro) == "critico",
                     "erro de leitura fica em 'critico'")

    # Fila é status, não problema.
    fila = casos._avisos_da_entrega(_entrega(status_proc="na_fila"), ITEM)
    falhas += checar(_tom("aguardando", fila) == "info", "espera na fila é 'info'")

    # A lista de strings antiga continua existindo e batendo com os textos.
    entrada = _entrega(roteamento_origem="semantico", roteamento_motivo="parece um laudo")
    textos = casos._alertas_da_entrega(entrada, ITEM)
    esperado = [a["texto"] for a in casos._avisos_da_entrega(entrada, ITEM)]
    falhas += checar(
        textos == esperado,
        "a lista de strings legada bate com os textos dos avisos",
    )

    print("TODOS OS TESTES PASSARAM" if not falhas else f"{falhas} FALHA(S)")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
