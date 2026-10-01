"""A jurimetria da petição gerada foca no TRT do estado, igual ao painel.

Antes, o apêndice jurimétrico da peça buscava no acervo NACIONAL enquanto o
painel do caso já focava no TRT do estado — o mesmo caso citava jurisdições
diferentes. Aqui provamos que a busca focada (estado→região→país) é a mesma nos
dois caminhos, sem tocar o pgvector nem a DeepSeek.

    PYTHONPATH=. .venv/Scripts/python.exe tests/test_peticao_jurimetria_uf.py
"""

from __future__ import annotations

from app import jurimetria_caso, peticao_local, rag


def checar(cond: bool, desc: str, detalhe: str = "") -> int:
    print(f"  {'PASS' if cond else '>> FALHA'} {desc}" + (f" ({detalhe})" if detalhe and not cond else ""))
    return 0 if cond else 1


def _trecho(processo: str) -> rag.TrechoSimilar:
    return rag.TrechoSimilar(
        texto="fundamentação sobre horas extras e adicional noturno",
        similaridade=0.8,
        titulo="sentença",
        identificador=processo,
        url=None,
        metadados={"numero_processo": processo, "rotulo": "PROCEDENTE", "orgao_julgador": "1a Vara"},
    )


def main_teste() -> int:
    falhas = 0
    guardado_busca = rag.buscar_similares
    guardado_llm = peticao_local._llm_json

    tribunais_vistos: list[list[str] | None] = []

    def busca(consulta, **kwargs):  # noqa: ANN001
        tribunais_vistos.append(kwargs.get("tribunais"))
        # Amostra >= MINIMO_AMOSTRA para a camada do estado "colar" (senão o
        # design manda cair para região/nacional, o que é correto).
        return [_trecho(f"{n:04d}") for n in range(1, jurimetria_caso.MINIMO_AMOSTRA + 1)]

    # Sem rede: a leitura jurimétrica é opcional e o código tolera falha dela.
    def llm(*_a, **_k):  # noqa: ANN002, ANN003
        raise peticao_local.ErroPeticao("sem DeepSeek no teste")

    rag.buscar_similares = busca  # type: ignore[assignment]
    peticao_local._llm_json = llm  # type: ignore[assignment]

    secoes = [
        {"code": "FACTS", "content": "O reclamante reside em Nova Iguaçu - RJ e trabalhou na ré."},
        {"code": "LEGAL_GROUNDS", "content": "Horas extras habituais."},
        {"code": "CLAIMS", "content": "Pagamento das horas extras."},
        {"code": "EVIDENCE", "content": "Cartões de ponto."},
    ]
    resultado, _apendice = peticao_local._analisar_jurimetria_da_minuta(
        secoes, texto_para_uf="Reclamante domiciliado em Nova Iguaçu - RJ"
    )

    falhas += checar(resultado["disponivel"] is True, "com amostra, jurimetria disponível")
    falhas += checar(
        tribunais_vistos and tribunais_vistos[0] == ["TRT1"],
        "a busca da peticao foi FOCADA no TRT do estado (RJ->TRT1)",
        str(tribunais_vistos[:1]),
    )
    falhas += checar(
        resultado.get("jurisdicao") == "TRT1",
        "a jurisdição usada volta para a tela",
        str(resultado.get("jurisdicao")),
    )

    # Coerência: o mesmo texto no painel do caso escolhe a mesma jurisdição.
    _sim, jurisdicao_painel, uf = jurimetria_caso.buscar_focada(
        "horas extras", texto_para_uf="Nova Iguaçu - RJ"
    )
    falhas += checar(uf == "RJ" and jurisdicao_painel == "TRT1", "painel e petição concordam na jurisdição")

    rag.buscar_similares = guardado_busca  # type: ignore[assignment]
    peticao_local._llm_json = guardado_llm  # type: ignore[assignment]
    print("TODOS OS TESTES PASSARAM" if not falhas else f"{falhas} FALHA(S)")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
