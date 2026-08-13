"""O roteiro de entrevista visto de fora — como a tela o recebe.

O que este teste protege é a costura entre os dois lados: quem sabe que o campo
"CPF" é um CPF é o roteiro, e a tela só obedece ao que vem em `validacao`. Se
essa marca sumir num refactor, o campo continua funcionando, o número errado
continua sendo aceito, e ninguém percebe até a papelada voltar da Receita.

Rodar: .venv\\Scripts\\python.exe -m tests.test_roteiros
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import main, roteiros, validators

#: Tudo o que a tela sabe conferir hoje (ver frontend/lib/documentos.ts).
VALIDACOES_CONHECIDAS = {"", "cpf"}
#: Tudo o que a tela sabe consultar hoje (ver app/consultas.py).
BUSCAS_CONHECIDAS = {"", "cep"}


def checar(condicao: bool, descricao: str) -> bool:
    print(f"  {'PASS' if condicao else 'FALHA'} {descricao}")
    return condicao


def main_teste() -> int:
    falhas = 0

    with TestClient(main.app) as cliente:
        resposta = cliente.get("/api/roteiros/empregado_publico")
        falhas += not checar(resposta.status_code == 200, "o roteiro responde")
        perguntas = [p for bloco in resposta.json()["blocos"] for p in bloco["perguntas"]]

        cpf = next((p for p in perguntas if p["id"] == "cpf"), None)
        falhas += not checar(cpf is not None, "o roteiro tem o campo de CPF")
        if cpf is not None:
            falhas += not checar(
                cpf["validacao"] == "cpf",
                "o campo de CPF chega à tela marcado para conferência do dígito",
            )
            falhas += not checar(
                cpf["tipo"] == "dado" and not cpf["transcrever"],
                "o CPF é digitado, não ditado — dígito transcrito ninguém confere",
            )

        desconhecidas = {
            p["validacao"] for p in perguntas if p["validacao"] not in VALIDACOES_CONHECIDAS
        }
        falhas += not checar(
            not desconhecidas,
            f"nenhuma validação que a tela não saiba aplicar (achadas: {desconhecidas or '—'})",
        )

        # --- campos que uma base pública preenche ------------------------
        cep = next((p for p in perguntas if p["id"] == "cep"), None)
        falhas += not checar(
            cep is not None and cep["busca"] == "cep" and cep["preenche"] == "endereco",
            "o CEP está marcado para consulta e sabe qual campo preenche",
        )

        civil = next((p for p in perguntas if p["id"] == "estado_civil"), None)
        falhas += not checar(
            civil is not None and civil["tipo"] == "escolha" and len(civil["opcoes"]) >= 4,
            "estado civil é escolhido de uma lista, não digitado",
        )

        # Escolha ou lista sem opção é um campo que não dá para responder: a
        # tela desenha zero botões e a pergunta fica morta.
        sem_opcoes = [
            p["id"] for p in perguntas if p["tipo"] in ("escolha", "lista") and not p["opcoes"]
        ]
        falhas += not checar(
            not sem_opcoes, f"toda escolha e lista tem opções (vazias: {sem_opcoes or '—'})"
        )

        # --- RG em três campos, como o contrato pede ---------------------
        ids = {p["id"] for p in perguntas}
        falhas += not checar(
            {"rg", "rg_orgao", "rg_uf"} <= ids,
            "o RG está separado em número, órgão expedidor e UF",
        )
        uf = next((p for p in perguntas if p["id"] == "rg_uf"), None)
        falhas += not checar(
            uf is not None and uf["tipo"] == "lista" and len(uf["opcoes"]) == 27,
            "a UF é escolhida numa lista com as 27 unidades da federação",
        )

        buscas_estranhas = {p["busca"] for p in perguntas if p["busca"] not in BUSCAS_CONHECIDAS}
        falhas += not checar(
            not buscas_estranhas,
            f"nenhuma busca que o backend não saiba fazer (achadas: {buscas_estranhas or '—'})",
        )

        # Um `preenche` apontando para pergunta que não existe é falha muda: a
        # consulta funciona, o resultado é gravado, e nada aparece na tela.
        orfaos = {p["preenche"] for p in perguntas if p["preenche"] and p["preenche"] not in ids}
        falhas += not checar(
            not orfaos, f"toda busca preenche um campo existente (órfãos: {orfaos or '—'})"
        )

    # O validador do navegador é uma cópia deste; os dois têm de concordar nos
    # casos de sempre. Divergiu, a regra certa é a do Python.
    for valor, esperado in (("111.444.777-35", True), ("11144477736", False), ("111.111.111-11", False)):
        falhas += not checar(
            validators.validar_cpf(valor) is esperado,
            f"validar_cpf({valor!r}) = {esperado}",
        )

    falhas += not checar(
        roteiros.obter("nao_existe") is None,
        "roteiro inexistente devolve None em vez de estourar",
    )

    print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
