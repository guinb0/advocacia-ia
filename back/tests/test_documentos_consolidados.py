"""Documentos mínimos consolidados entre as ações do atendimento (cenário 15)."""

from __future__ import annotations

from app import pos_entrevista
from app.casos import ENTREGUE, PENDENTE


def _item(nome: str, obrigatorio: bool = True, tipo: str | None = None, status: str = PENDENTE) -> dict:
    return {"codigo": nome.lower()[:8], "nome": nome, "obrigatorio": obrigatorio, "tipo": tipo, "status": status}


def _nomes(lista: list[dict]) -> list[str]:
    return sorted(d["nome"] for d in lista)


def test_cenario_15_duas_acoes_pedem_um_documento_uma_vez_so():
    casos = [
        {"id": "c1", "acao": "Doença Ocupacional", "itens": [
            _item("RG", tipo="rg"), _item("CAT", tipo="cat"), _item("Laudo médico"), _item("Fotos", obrigatorio=False),
        ]},
        {"id": "c2", "acao": "Auxílio-Acidente", "itens": [
            _item("Documento de identidade", tipo="rg"), _item("Carta do INSS"), _item("laudo  MÉDICO"),
        ]},
    ]

    resumo = pos_entrevista.consolidar(casos)

    assert _nomes(resumo["faltantes"]) == ["CAT", "Carta do INSS", "Laudo médico", "RG"]
    rg = next(d for d in resumo["faltantes"] if d["tipo"] == "rg")
    assert rg["casos"] == ["Doença Ocupacional", "Auxílio-Acidente"]
    assert resumo["disponiveis"] == []


def test_o_que_ja_chegou_foi_declarado_ou_validado_em_outro_caso_nao_falta():
    casos = [
        {"id": "c1", "acao": "Doença Ocupacional", "itens": [
            _item("RG", tipo="rg", status=ENTREGUE), _item("CAT", tipo="cat"), _item("Laudo médico"),
            _item("CTPS", tipo="ctps"),
        ]},
        {"id": "c2", "acao": "Auxílio-Acidente", "itens": [_item("RG", tipo="rg"), _item("Carta do INSS")]},
    ]

    resumo = pos_entrevista.consolidar(
        casos, declarados=["laudo medico", "Comprovante de residência"],
        validados_em_outros={pos_entrevista.chave_documento({"tipo": "ctps"})},
    )

    origens = {d["nome"]: d["origem"] for d in resumo["disponiveis"]}
    assert origens == {"RG": "caso", "Laudo médico": "entrevista", "CTPS": "outro_caso",
                       "Comprovante de residência": "entrevista"}
    # O RG entregue no caso 1 cobre o RG pendente do caso 2.
    assert _nomes(resumo["faltantes"]) == ["CAT", "Carta do INSS"]


def test_documento_opcional_nunca_aparece_como_faltante():
    resumo = pos_entrevista.consolidar([{"id": "c1", "itens": [_item("Fotos do local", obrigatorio=False)]}])
    assert resumo == {"disponiveis": [], "faltantes": []}


def test_resumo_do_atendimento_usa_os_casos_criados(monkeypatch):
    itens = {"c1": [_item("RG", tipo="rg")], "c2": [_item("RG", tipo="rg"), _item("CAT", tipo="cat")]}
    monkeypatch.setattr(pos_entrevista, "_itens_do_caso", lambda caso_id: (itens[caso_id], None))
    monkeypatch.setattr(pos_entrevista, "_cpf_dos_casos", lambda ids: "")

    resumo = pos_entrevista.documentos_consolidados({
        "id": "a1", "casos": [{"id": "c1", "acao": "A"}, {"id": "c2", "acao": "B"}],
        "documentos": {"declarados": ["CAT"]},
    })

    assert _nomes(resumo["faltantes"]) == ["RG"]
    assert _nomes(resumo["disponiveis"]) == ["CAT"]
    assert resumo["declarados"] == ["CAT"]
