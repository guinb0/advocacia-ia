"""O que o atendente (e a cobrança automática) vê como pendente.

Issue "[Atendimento - Documentos] - Exibir somente documentos obrigatórios
pendentes ao atendente", cujos critérios são: o atendente vê SOMENTE os
obrigatórios faltantes, documento recebido deixa de aparecer, e a automação do
WhatsApp recebe as pendências corretas.

POR QUE ESTE TESTE EXISTE À PARTE

A regra vive em `casos.documentos_pendentes_da_situacao`, que é pura — recebe a
situação já montada e devolve a lista. A única cobertura que ela tinha estava em
`tests/test_casos.py`, que passou a exigir banco de teste (ver
`tests/banco_de_teste.py`) e por isso não roda na máquina de quem tem um `.env`
de produção. A regra que decide o que é cobrado do cliente não podia ficar sem
verificação executável.

Rodar: .venv\\Scripts\\python.exe -m tests.test_pendencias_atendente
"""

from __future__ import annotations

from typing import Any

from app import casos


def checar(condicao: bool, texto: str, detalhe: str = "") -> bool:
    print(("  PASS  " if condicao else "  FALHA ") + texto + (f"\n          {detalhe}" if not condicao and detalhe else ""))
    return condicao


def item(
    codigo: str,
    numero: int,
    nome: str,
    *,
    obrigatorio: bool,
    status: str,
    entregas: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "codigo": codigo,
        "numero": numero,
        "nome": nome,
        "obrigatorio": obrigatorio,
        "status": status,
        "observacao": "",
        "entregas": entregas or [],
    }


SITUACAO = {
    "itens": [
        item("DOC.01", 1, "RG", obrigatorio=True, status=casos.PENDENTE),
        item("DOC.02", 2, "CPF", obrigatorio=True, status=casos.ENTREGUE),
        # Chegou e está sendo lido: cobrar de novo faria o cliente reenviar o que
        # já mandou, antes de alguém ter olhado.
        item("DOC.03", 3, "CTPS", obrigatorio=True, status=casos.PROCESSANDO),
        # Chegou com ressalva: precisa de ação do cliente, obrigatório ou não.
        item("DOC.04", 4, "Contracheque", obrigatorio=True, status=casos.CONFERIR,
             entregas=[{"validacao": {"veredito": "REPROVADO"}}]),
        item("DOC.05", 5, "Foto do crachá", obrigatorio=False, status=casos.PENDENTE),
        item("DOC.06", 6, "Extrato antigo", obrigatorio=False, status=casos.CONFERIR,
             entregas=[{"validacao": {"veredito": "REPROVADO"}}]),
        item("DOC.07", 7, "Comprovante", obrigatorio=False, status=casos.ENTREGUE),
    ]
}


def nomes(lista: list[dict[str, Any]]) -> list[str]:
    return [i["nome"] for i in lista]


def testar_so_obrigatorios() -> int:
    falhas = 0
    pendentes = casos.documentos_pendentes_da_situacao(SITUACAO)
    obtidos = nomes(pendentes)

    falhas += not checar(
        "RG" in obtidos, "o obrigatório que ninguém mandou é cobrado", str(obtidos)
    )
    falhas += not checar(
        "Foto do crachá" not in obtidos,
        "opcional que ninguém mandou NÃO é cobrado do atendente",
        str(obtidos),
    )
    falhas += not checar(
        "CPF" not in obtidos, "documento recebido e aprovado sai da lista", str(obtidos)
    )
    falhas += not checar(
        "CTPS" not in obtidos,
        "documento em leitura não é cobrado de novo — o cliente já enviou",
        str(obtidos),
    )
    falhas += not checar(
        "Contracheque" in obtidos,
        "obrigatório que voltou com ressalva continua pendente",
        str(obtidos),
    )
    falhas += not checar(
        "Extrato antigo" in obtidos,
        "opcional COM ressalva entra: o cliente já agiu e precisa reenviar",
        str(obtidos),
    )
    falhas += not checar(
        "Comprovante" not in obtidos, "opcional aprovado não aparece", str(obtidos)
    )
    return falhas


def testar_com_opcionais() -> int:
    falhas = 0
    pendentes = casos.documentos_pendentes_da_situacao(SITUACAO, incluir_opcionais=True)
    obtidos = nomes(pendentes)
    falhas += not checar(
        "Foto do crachá" in obtidos,
        "pedindo os opcionais, o opcional pendente aparece",
        str(obtidos),
    )
    falhas += not checar(
        "CTPS" not in obtidos and "CPF" not in obtidos,
        "mas recebido continua fora, opcionais ou não",
        str(obtidos),
    )
    return falhas


def testar_motivo_para_o_cliente() -> int:
    """A pendência tem de dizer POR QUE, senão o cliente não sabe o que refazer."""
    falhas = 0
    pendentes = {i["nome"]: i for i in casos.documentos_pendentes_da_situacao(SITUACAO)}
    falhas += not checar(
        pendentes["RG"]["motivo"] == "ainda não recebemos este documento",
        f"o que não chegou diz que não chegou ({pendentes['RG']['motivo']!r})",
    )
    falhas += not checar(
        bool(pendentes["Contracheque"]["motivo"])
        and pendentes["Contracheque"]["motivo"] != "ainda não recebemos este documento",
        f"o que chegou com ressalva diz o motivo da ressalva ({pendentes['Contracheque']['motivo']!r})",
    )
    return falhas


def testar_situacao_vazia() -> int:
    falhas = 0
    falhas += not checar(
        casos.documentos_pendentes_da_situacao({}) == [],
        "situação sem itens não inventa pendência",
    )
    falhas += not checar(
        casos.documentos_pendentes_da_situacao({"itens": []}) == [],
        "checklist vazio também não",
    )
    return falhas


def testar_ordem() -> int:
    """A ordem é OPERACIONAL, não a numérica do checklist.

    `ordenar_itens_para_listagem` põe primeiro o que nunca chegou (pendente),
    depois o que voltou com ressalva (conferir); dentro de cada grupo, obrigatório
    antes de opcional e então o número. A lista vai para o WhatsApp do cliente: o
    que ele ainda não mandou vem antes do que ele precisa refazer.
    """
    falhas = 0
    pendentes = casos.documentos_pendentes_da_situacao(SITUACAO, incluir_opcionais=True)
    chaves = [(i["status"], i["obrigatorio"], i["numero"]) for i in pendentes]

    falhas += not checar(
        [c[0] for c in chaves] == [casos.PENDENTE, casos.PENDENTE, casos.CONFERIR, casos.CONFERIR],
        f"o que nunca chegou vem antes do que precisa ser refeito ({chaves})",
    )
    falhas += not checar(
        [c[1] for c in chaves] == [True, False, True, False],
        f"e dentro de cada grupo o obrigatório vem primeiro ({chaves})",
    )
    # Dentro do mesmo grupo a numeração do checklist é preservada — é como o
    # cliente vê os documentos na lista que recebeu.
    so_obrigatorios = casos.documentos_pendentes_da_situacao(SITUACAO)
    numeros = [i["numero"] for i in so_obrigatorios if i["status"] == casos.PENDENTE]
    falhas += not checar(numeros == sorted(numeros), f"a numeração do checklist é respeitada ({numeros})")
    return falhas


def main_teste() -> int:
    falhas = 0
    for titulo, teste in (
        ("1. Só os obrigatórios faltantes", testar_so_obrigatorios),
        ("2. Com os opcionais, a pedido", testar_com_opcionais),
        ("3. Cada pendência diz o porquê", testar_motivo_para_o_cliente),
        ("4. Caso sem checklist", testar_situacao_vazia),
        ("5. Ordem do checklist", testar_ordem),
    ):
        print(f"\n{titulo}")
        falhas += teste()
    print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
