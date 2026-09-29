"""O recorte da base de uma vara — issue "Preparar base com 500 processos da última vara".

Sem rede e sem banco: as três funções que decidem o recorte são puras, e é nelas
que moram os critérios de aceite da issue.

O que cada verificação protege:

- **"não existem duplicidades indevidas"**: o DJEN publica várias vezes no mesmo
  processo (intimação, sentença, embargos). Contar as três contaria o mesmo
  processo três vezes na estatística de desfechos da jurimetria — a base ficaria
  dizendo que houve mais julgados do que houve.
- **a vara vem do número CNJ, não do texto**: a publicação cita outras varas ao
  narrar o histórico do processo, então ler do texto escolheria juízo errado.
- **"procedimento corresponde à estratégia de limpeza definida"**: é a mesma de
  `scripts/coletar_djen_trts.py` — fora lista de distribuição e texto curto.

Rodar: .venv\\Scripts\\python.exe -m tests.test_base_vara
"""

from __future__ import annotations

from scripts.preparar_base_vara import (
    MIN_CARACTERES,
    escolher_vara,
    montar,
    vara_do_processo,
)


def checar(condicao: bool, texto: str, detalhe: str = "") -> bool:
    print(("  PASS  " if condicao else "  FALHA ") + texto + (f"\n          {detalhe}" if not condicao and detalhe else ""))
    return condicao


def publicacao(
    processo: str, data: str, *, texto: str | None = None, tipo: str = "Intimação"
) -> dict:
    return {
        "numeroProcesso": processo,
        "tribunal": "TRT8",
        "dataDisponibilizacao": data,
        "tipoComunicacao": tipo,
        "tipo_conteudo": "publicacao_djen",
        "texto": texto if texto is not None else ("D" * MIN_CARACTERES),
    }


# Números CNJ de 20 dígitos: os 4 últimos são a unidade de origem.
P_VARA19_A = "00010000020265080019"
P_VARA19_B = "00020000020265080019"
P_VARA19_C = "00030000020265080019"
P_VARA18 = "00040000020265080018"
P_TRIBUNAL = "00050000020265080000"


def testar_leitura_da_vara() -> int:
    falhas = 0
    falhas += not checar(vara_do_processo(P_VARA19_A) == "0019", "lê a unidade de origem do número CNJ")
    falhas += not checar(
        vara_do_processo("0001000-00.2026.5.08.0019") == "0019",
        "lê igual com a pontuação do CNJ",
    )
    falhas += not checar(vara_do_processo(P_TRIBUNAL) == "0000", "o 2º grau é reconhecido como 0000")
    # Número truncado não pode virar vara chutada: quatro dígitos quaisquer
    # colocariam o processo no juízo errado da base.
    falhas += not checar(vara_do_processo("123") == "", "número curto não vira vara")
    falhas += not checar(vara_do_processo(None) == "", "número ausente não vira vara")
    return falhas


def testar_escolha_da_ultima_vara() -> int:
    falhas = 0
    publicacoes = [
        publicacao(P_VARA18, "2026-08-01"),
        publicacao(P_VARA19_A, "2026-09-02"),
        # O 2º grau publicou DEPOIS de todas. Não é vara, e não pode ser escolhido.
        publicacao(P_TRIBUNAL, "2026-09-30"),
    ]
    vara, data = escolher_vara(publicacoes)
    falhas += not checar(vara == "0019", f"a última vara a publicar é a escolhida ({vara})")
    falhas += not checar(data == "2026-09-02", f"e vem com a data da publicação ({data})")
    falhas += not checar(
        escolher_vara([publicacao(P_TRIBUNAL, "2026-09-30")]) == ("", ""),
        "só com 2º grau não há vara a escolher",
    )
    return falhas


def testar_um_processo_uma_linha() -> int:
    """O critério "não existem duplicidades indevidas", medido."""
    falhas = 0
    publicacoes = [
        publicacao(P_VARA19_A, "2026-05-10", texto="A" * MIN_CARACTERES),
        # Mesmo processo, publicação mais nova: é ela que fica.
        publicacao(P_VARA19_A, "2026-08-20", texto="B" * (MIN_CARACTERES + 50)),
        publicacao(P_VARA19_B, "2026-06-01"),
        publicacao(P_VARA18, "2026-07-01"),
    ]
    escolhidas, contagem = montar(publicacoes, "0019", 500)
    numeros = [p["numeroProcesso"] for p in escolhidas]

    falhas += not checar(len(escolhidas) == 2, f"dois processos distintos da vara (veio {len(escolhidas)})")
    falhas += not checar(
        numeros.count(P_VARA19_A) == 1, "o processo repetido entra UMA vez", str(numeros)
    )
    falhas += not checar(
        next(p for p in escolhidas if p["numeroProcesso"] == P_VARA19_A)["dataDisponibilizacao"]
        == "2026-08-20",
        "das duas publicações fica a mais recente",
    )
    falhas += not checar(
        P_VARA18 not in numeros, "processo de outra vara não entra no recorte"
    )
    falhas += not checar(
        contagem["duplicidades_do_mesmo_processo"] == 1,
        f"a duplicidade é contada no relatório ({contagem})",
    )
    falhas += not checar(
        escolhidas[0]["dataDisponibilizacao"] >= escolhidas[-1]["dataDisponibilizacao"],
        "a saída vem da mais recente para a mais antiga",
    )
    return falhas


def testar_limpeza() -> int:
    falhas = 0
    publicacoes = [
        publicacao(P_VARA19_A, "2026-08-01"),
        # Lista de distribuição é roteamento, não decisão.
        publicacao(P_VARA19_B, "2026-08-02", tipo="Lista de Distribuição"),
        # Texto curto: aviso sem teor.
        publicacao(P_VARA19_C, "2026-08-03", texto="ciência"),
    ]
    escolhidas, contagem = montar(publicacoes, "0019", 500)
    falhas += not checar(
        [p["numeroProcesso"] for p in escolhidas] == [P_VARA19_A],
        "distribuição e texto curto ficam fora",
        str([p["numeroProcesso"] for p in escolhidas]),
    )
    falhas += not checar(
        contagem["descartadas_pela_limpeza"] == 2,
        f"o relatório diz quantas a limpeza tirou ({contagem})",
    )
    return falhas


def testar_teto() -> int:
    """O teto corta, e corta pelas MAIS RECENTES — a base é uma amostra fechada."""
    falhas = 0
    publicacoes = [
        # 20 dígitos exatos: 7 do sequencial + "0020265080019" (13). Menos que isso
        # e `vara_do_processo` recusa o número — como deve.
        publicacao(f"{n:07d}0020265080019", f"2026-08-{(n % 28) + 1:02d}")
        for n in range(1, 21)
    ]
    escolhidas, contagem = montar(publicacoes, "0019", 5)
    falhas += not checar(len(escolhidas) == 5, f"respeita o teto pedido (veio {len(escolhidas)})")
    falhas += not checar(
        contagem["processos_distintos"] == 20,
        f"mas o relatório mostra o total encontrado ({contagem})",
    )
    datas = [p["dataDisponibilizacao"] for p in escolhidas]
    falhas += not checar(datas == sorted(datas, reverse=True), f"as que ficam são as mais recentes ({datas})")
    return falhas


def main_teste() -> int:
    falhas = 0
    for titulo, teste in (
        ("1. A vara sai do número CNJ", testar_leitura_da_vara),
        ("2. Qual é 'a última vara'", testar_escolha_da_ultima_vara),
        ("3. Um processo, uma linha", testar_um_processo_uma_linha),
        ("4. Estratégia de limpeza", testar_limpeza),
        ("5. Teto de processos", testar_teto),
    ):
        print(f"\n{titulo}")
        falhas += teste()
    print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
