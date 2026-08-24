"""O roteiro de entrevista visto de fora — como a tela o recebe.

O que este teste protege é a costura entre os dois lados: quem sabe que o campo
"CPF" é um CPF é o roteiro, e a tela só obedece ao que vem em `validacao`. Se
essa marca sumir num refactor, o campo continua funcionando, o número errado
continua sendo aceito, e ninguém percebe até a papelada voltar da Receita.

Rodar: .venv\\Scripts\\python.exe -m tests.test_roteiros
"""

from __future__ import annotations

import os

# A rota do roteiro é protegida, e este teste não tem sessão. Sem desligar a
# autenticação AQUI — antes de importar `app.main`, que lê a variável na
# importação — a suíte parava no primeiro 401 e nenhuma das conferências de
# estrutura chegava a rodar. O `carregar_env` só preenche variável AUSENTE, então
# defini-la vazia aqui vence o que está no `.env`.
os.environ["JWT_SECRET"] = ""

from fastapi.testclient import TestClient  # noqa: E402

from app import main, roteiros, validators  # noqa: E402

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

        abertura = next(bloco for bloco in resposta.json()["blocos"] if bloco["id"] == "abertura")
        ids_abertura = [pergunta["id"] for pergunta in abertura["perguntas"]]
        falhas += not checar(
            ids_abertura == ["nome", "cpf", "uf", "municipio"],
            "a abertura pede nome, CPF, UF e município nesta ordem",
        )
        uf_residencia = next((p for p in perguntas if p["id"] == "uf"), None)
        municipio = next((p for p in perguntas if p["id"] == "municipio"), None)
        falhas += not checar(
            uf_residencia is not None
            and uf_residencia["tipo"] == "lista"
            and len(uf_residencia["opcoes"]) == 27
            and uf_residencia["obrigatoria"],
            "a UF de residência é obrigatória e oferece as 27 unidades",
        )
        falhas += not checar(
            municipio is not None and municipio["obrigatoria"],
            "o município de residência é obrigatório",
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

    # --- o roteiro é o do escritório, não uma paráfrase --------------------
    # O escritório pediu que o documento fosse seguido estritamente. Estas
    # asserções travam o que uma reescrita bem-intencionada apagaria primeiro.
    corpo = resposta.json()
    saudacao, encerramento = corpo["saudacao"], corpo["encerramento"]

    falhas += not checar(
        len(saudacao) == 10 and saudacao[-1] == "Podemos começar?",
        f"a saudação tem os 10 parágrafos e termina no convite ({len(saudacao)})",
    )
    falhas += not checar(
        "totalmente sigilosa" in " ".join(saudacao),
        "a promessa de sigilo continua na abertura, palavra por palavra",
    )
    falhas += not checar(
        any("Departamento de Documentação" in p for p in encerramento),
        "o encerramento passa o atendimento para a Documentação",
    )

    # --- a ordem que o escritório pediu ------------------------------------
    ordem = [b["id"] for b in corpo["blocos"]]
    falhas += not checar(
        ordem[0] == "abertura",
        f"a entrevista abre pela identificação mínima ({ordem[0]})",
    )
    abertura = next(b for b in corpo["blocos"] if b["id"] == "abertura")
    falhas += not checar(
        [p["id"] for p in abertura["perguntas"]] == ["nome", "cpf", "uf", "municipio"],
        "e ela pede nome, CPF, UF e município",
    )
    falhas += not checar(
        ordem[-1] == "identificacao" and ordem.index("rastreio") < ordem.index("identificacao"),
        "a qualificação completa foi para o fim, depois do rastreio",
    )
    qualificacao = next(b for b in corpo["blocos"] if b["id"] == "identificacao")
    falhas += not checar(
        qualificacao["delegado_a"] == "Departamento de Documentação",
        "e está marcada como de outra equipe",
    )
    falhas += not checar(
        not any(
            p["id"] in ("nome", "cpf", "uf", "municipio")
            for p in qualificacao["perguntas"]
        ),
        "os quatro dados de abertura não ficaram duplicados nos dois blocos",
    )

    # --- as retomadas ------------------------------------------------------
    # Elas são LIDAS emendando no enunciado da pergunta, que a tela mostra logo
    # abaixo. Uma frase que não termine em dois-pontos quebra a leitura em voz
    # alta com o cliente na linha — e nada no código acusaria isso.
    retomadas = corpo["retomadas"]
    falhas += not checar(
        len(retomadas) >= 2,
        f"o roteiro traz frases de retomada ({len(retomadas)})",
    )
    sem_emenda = [r for r in retomadas if not r.rstrip().endswith(":")]
    falhas += not checar(
        not sem_emenda,
        f"toda retomada emenda no enunciado, terminando em dois-pontos ({len(sem_emenda)} fora)",
    )

    # Fecho para tipo que não existe é frase que nunca aparece; e `relato` fica
    # de fora de propósito — ali o que se quer é que o cliente conte.
    fechos = corpo["fechos_por_tipo"]
    tipos_no_roteiro = {p["tipo"] for b in corpo["blocos"] for p in b["perguntas"]}
    falhas += not checar(
        set(fechos) <= tipos_no_roteiro,
        f"todo fecho é de um tipo que o roteiro usa (sobrando: {set(fechos) - tipos_no_roteiro})",
    )
    falhas += not checar(
        "relato" not in fechos,
        "relato não tem fecho — ali a resposta longa é o objetivo",
    )

    # --- ids únicos --------------------------------------------------------
    # Mover pergunta entre blocos é onde se duplica id sem perceber, e id
    # duplicado faz uma resposta sobrescrever a outra em silêncio.
    todos = [p["id"] for b in corpo["blocos"] for p in b["perguntas"]]
    duplicados = {i for i in todos if todos.count(i) > 1}
    falhas += not checar(not duplicados, f"nenhum id de pergunta duplicado ({duplicados})")

    # --- o impedimento do §62 ---------------------------------------------
    falhas += not checar(
        roteiros.impedimentos("empregado_publico", {}) == [],
        "sem resposta, nada impede o prosseguimento",
    )
    falhas += not checar(
        len(roteiros.impedimentos("empregado_publico", {"as_recebeu": "sim"})) == 0,
        "quem já recebeu a ação anterior pode seguir",
    )
    for grafia in ("não", "nao", "NÃO"):
        barrado = roteiros.impedimentos("empregado_publico", {"as_recebeu": grafia})
        falhas += not checar(
            len(barrado) == 1 and barrado[0]["motivo"],
            f"quem NÃO recebeu é barrado, com motivo — grafia {grafia!r}",
        )

    print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
