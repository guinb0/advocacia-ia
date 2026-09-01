"""Consulta de CEP: o que preenche o endereço na entrevista.

Sem rede: as duas bases públicas são substituídas por um transporte falso. O que
se testa é o comportamento em volta delas, que é onde a atendente sente:
o troco entre provedores quando um cai, a diferença entre "CEP não existe" e
"base fora do ar", e o cache que evita bater na base a cada tecla.

Rodar: .venv\\Scripts\\python.exe -m tests.test_consultas
"""

from __future__ import annotations

import asyncio

import httpx

from app import consultas

BRASILAPI = {
    "cep": "66055240",
    "state": "PA",
    "city": "Belém",
    "neighborhood": "Nazaré",
    "street": "Avenida Governador José Malcher",
}

VIACEP = {
    "cep": "66055-240",
    "logradouro": "Avenida Governador José Malcher",
    "bairro": "Nazaré",
    "localidade": "Belém",
    "uf": "PA",
}


def checar(condicao: bool, descricao: str) -> bool:
    print(f"  {'PASS' if condicao else 'FALHA'} {descricao}")
    return condicao


def cliente(rotas: dict[str, httpx.Response], chamadas: list[str] | None = None):
    """Transporte falso: responde por host, e anota quem foi chamado."""

    def responder(pedido: httpx.Request) -> httpx.Response:
        if chamadas is not None:
            chamadas.append(pedido.url.host)
        for host, resposta in rotas.items():
            if host in pedido.url.host:
                if isinstance(resposta, Exception):
                    raise resposta
                return resposta
        return httpx.Response(500)

    return httpx.AsyncClient(transport=httpx.MockTransport(responder))


async def executar() -> int:
    falhas = 0

    # --- caminho feliz: a primeira base responde -----------------------
    consultas.limpar_cache()
    chamadas: list[str] = []
    async with cliente({"brasilapi": httpx.Response(200, json=BRASILAPI)}, chamadas) as http:
        r = await consultas.buscar_cep("66055-240", http)

    falhas += not checar(r["cidade"] == "Belém" and r["uf"] == "PA", "cidade e UF vêm da base")
    falhas += not checar(
        r["endereco_formatado"]
        == "Avenida Governador José Malcher, nº ___, Nazaré, Belém/PA, CEP 66055-240",
        f"o endereço já sai pronto para o campo ({r['endereco_formatado']!r})",
    )
    falhas += not checar(
        "nº ___" in r["endereco_formatado"],
        "o número fica em branco à vista — o CEP não o entrega, e sem ele não há citação",
    )
    falhas += not checar(r["fonte"] == "BrasilAPI", "a tela sabe de onde veio o dado")

    # --- cache: a segunda consulta não sai da máquina ------------------
    chamadas.clear()
    async with cliente({"brasilapi": httpx.Response(200, json=BRASILAPI)}, chamadas) as http:
        await consultas.buscar_cep("66055240", http)
    falhas += not checar(chamadas == [], "CEP repetido sai do cache, sem bater na base pública")

    # --- a primeira base cai, a segunda salva a entrevista -------------
    consultas.limpar_cache()
    chamadas = []
    rotas = {
        "brasilapi": httpx.ConnectError("sem rede"),
        "viacep": httpx.Response(200, json=VIACEP),
    }
    async with cliente(rotas, chamadas) as http:
        r = await consultas.buscar_cep("66055240", http)
    falhas += not checar(
        r["fonte"] == "ViaCEP" and r["cidade"] == "Belém",
        "caindo a primeira base, a segunda responde",
    )
    falhas += not checar(len(chamadas) == 2, "só tenta a segunda depois que a primeira falha")

    # --- CEP que não existe ≠ base fora do ar --------------------------
    consultas.limpar_cache()
    async with cliente(
        {"brasilapi": httpx.Response(404), "viacep": httpx.Response(200, json={"erro": "true"})}
    ) as http:
        try:
            await consultas.buscar_cep("99999999", http)
            msg = ""
        except consultas.ErroConsulta as exc:
            msg = str(exc)
    falhas += not checar("não encontrado" in msg, f"CEP inexistente diz isso ({msg!r})")

    consultas.limpar_cache()
    async with cliente({"brasilapi": httpx.ConnectError("x"), "viacep": httpx.ConnectError("x")}) as http:
        try:
            await consultas.buscar_cep("66055240", http)
            msg = ""
        except consultas.ErroConsulta as exc:
            msg = str(exc)
    falhas += not checar(
        "à mão" in msg,
        f"as duas fora do ar mandam preencher à mão, sem culpar o CEP ({msg!r})",
    )

    # --- entrada malformada não chega a sair da máquina ----------------
    chamadas = []
    async with cliente({"brasilapi": httpx.Response(200, json=BRASILAPI)}, chamadas) as http:
        try:
            await consultas.buscar_cep("123", http)
            recusou = False
        except consultas.ErroConsulta:
            recusou = True
    falhas += not checar(recusou and chamadas == [], "CEP incompleto nem chega a ser consultado")

    return falhas


def main_teste() -> int:
    falhas = asyncio.run(executar())
    consultas.limpar_cache()
    print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
