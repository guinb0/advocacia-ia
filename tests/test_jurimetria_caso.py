"""O cruzamento do caso com a jurimetria: usa os achados do OCR e degrada bem.

Não toca o pgvector: `rag.buscar_similares` e os sinais do caso são trocados por
versões de teste. O que se prova:
  - os achados extraídos (CID etc.) ENTRAM na consulta vetorial, não só a entrevista;
  - com precedentes, devolve estatísticas e a lista auditável;
  - base fora do ar ou sem sinais devolve `disponivel: False`, nunca levanta.

    PYTHONPATH=. .venv/Scripts/python.exe tests/test_jurimetria_caso.py
"""

from __future__ import annotations

from app import jurimetria_caso, rag


def checar(cond: bool, desc: str) -> int:
    print(f"  {'PASS' if cond else '>> FALHA'} {desc}")
    return 0 if cond else 1


def _trecho(resultado: str, vara: str, processo: str) -> rag.TrechoSimilar:
    return rag.TrechoSimilar(
        texto="fundamentação da decisão sobre acidente de trabalho e nexo",
        similaridade=0.82,
        titulo="acórdão",
        identificador=processo,
        url=None,
        metadados={"numero_processo": processo, "rotulo": resultado, "orgao_julgador": vara},
    )


def main_teste() -> int:
    falhas = 0
    guardado_sinais = jurimetria_caso._sinais_do_caso
    guardado_busca = rag.buscar_similares

    jurimetria_caso._sinais_do_caso = lambda _id: {  # type: ignore[assignment]
        "categoria": "Acidente do Trabalho",
        "entrevista": "cliente caiu de andaime e fraturou a tíbia",
        "achados": ["CID S82.2 fratura da tíbia", "Benefício INSS espécie 91"],
    }

    # 1) A consulta carrega os achados do OCR, não só a entrevista.
    capturada = {}
    def busca_ok(consulta, **_):
        capturada["consulta"] = consulta
        return [_trecho("PROCEDENTE", "1a Vara", "001"), _trecho("IMPROCEDENTE", "2a Vara", "002"),
                _trecho("PROCEDENTE", "1a Vara", "003")]
    rag.buscar_similares = busca_ok  # type: ignore[assignment]
    r = jurimetria_caso.cruzar("caso-1")
    falhas += checar(r["disponivel"] is True, "com precedentes, disponivel=True")
    falhas += checar("CID S82.2" in capturada.get("consulta", ""), "o CID extraído entra na busca vetorial")
    falhas += checar("Benefício INSS" in capturada.get("consulta", ""), "o benefício do INSS também entra")
    falhas += checar(len(r["precedentes"]) == 3, "lista os precedentes recuperados")
    falhas += checar(
        r["estatisticas"] and r["estatisticas"]["processos_analisados"] == 3,
        "traz as estatísticas da amostra (desfechos, varas)",
    )
    falhas += checar(
        any(v["nome"] == "1a Vara" for v in r["estatisticas"]["varas"]),
        "a distribuição POR VARA aparece",
    )

    # 2) Base fora do ar não derruba — vira disponivel=False.
    def busca_falha(*_a, **_k):
        raise rag.ErroRAG("pgvector fora do ar")
    rag.buscar_similares = busca_falha  # type: ignore[assignment]
    r = jurimetria_caso.cruzar("caso-1")
    falhas += checar(r["disponivel"] is False and "não respondeu" in r["aviso"], "base fora do ar vira aviso, não erro")

    # 3) Sem sinais nenhum, não tenta buscar.
    jurimetria_caso._sinais_do_caso = lambda _id: {"categoria": "", "entrevista": "", "achados": []}  # type: ignore[assignment]
    r = jurimetria_caso.cruzar("caso-1")
    falhas += checar(r["disponivel"] is False, "sem entrevista nem achados, disponivel=False")

    jurimetria_caso._sinais_do_caso = guardado_sinais  # type: ignore[assignment]
    rag.buscar_similares = guardado_busca  # type: ignore[assignment]
    print("TODOS OS TESTES PASSARAM" if not falhas else f"{falhas} FALHA(S)")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
