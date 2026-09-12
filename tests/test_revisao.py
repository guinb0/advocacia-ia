"""As métricas do Revisor — issue "[Revisão - Perfil] - Criar perfil de Revisor com
métricas de revisão".

SEM BANCO, DE PROPÓSITO

O que está em jogo aqui é a REGRA: quem conta como autor da revisão, como o tempo
de análise é apurado, e o que acontece com as linhas antigas. `conectar` é
substituído por um dublê que devolve linhas prontas — assim o teste roda em
qualquer máquina e não escreve em banco nenhum (ver `tests/banco_de_teste.py`).

O que cada verificação protege, ligado aos critérios de aceite da issue:

- **"métricas são vinculadas ao revisor correto"**: o recorte "minhas revisões"
  era feito pelo NOME de exibição. Dois revisores homônimos viam as revisões um
  do outro como próprias, e quem tivesse o nome editado pelo gestor perdia de
  vista o que já havia revisado. Agora o filtro é pelo `revisor_id`, com o nome
  valendo só para as linhas gravadas antes da coluna existir.
- **"tempo de análise pode ser consultado"**: a duração vem de `iniciada_em` →
  `concluida_em`, e data malformada não pode derrubar o painel inteiro.
- **"sistema registra revisões realizadas"**: revisão aberta conta em
  `em_andamento` e NÃO entra na média de tempo — ela ainda não terminou.

Rodar: .venv\\Scripts\\python.exe -m tests.test_revisao
"""

from __future__ import annotations

from typing import Any

from app import revisao


def checar(condicao: bool, texto: str, detalhe: str = "") -> bool:
    print(("  PASS  " if condicao else "  FALHA ") + texto + (f"\n          {detalhe}" if not condicao and detalhe else ""))
    return condicao


class LinhaFalsa(dict):
    """Uma linha de banco: o código lê por chave, como o `banco.Linha` real."""


class ConexaoFalsa:
    """Responde às duas consultas de `metricas`, aplicando o filtro no Python.

    Guarda o SQL e os parâmetros recebidos: parte do que se quer provar é que o
    filtro chega ao banco pelo `revisor_id`, e não pelo nome.
    """

    def __init__(self, linhas: list[dict[str, Any]]) -> None:
        self.linhas = linhas
        self.consultas: list[tuple[str, tuple]] = []

    def __enter__(self) -> "ConexaoFalsa":
        return self

    def __exit__(self, *_erro: object) -> bool:
        return False

    def execute(self, sql: str, params: tuple = ()) -> "ConexaoFalsa":
        self.consultas.append((" ".join(sql.split()), tuple(params)))
        self._sql, self._params = " ".join(sql.split()), tuple(params)
        return self

    def _filtradas(self) -> list[dict[str, Any]]:
        sql, params = self._sql, self._params
        alvo = self.linhas
        if "revisor_id = ?" in sql:
            ident, nome = params[0], params[1]
            alvo = [
                l
                for l in alvo
                if l.get("revisor_id") == ident
                or (l.get("revisor_id") is None and l.get("revisor") == nome)
            ]
        elif "AND revisor = ?" in sql:
            alvo = [l for l in alvo if l.get("revisor") == params[0]]
        if "concluida_em IS NOT NULL" in sql:
            return [l for l in alvo if l.get("concluida_em")]
        return [l for l in alvo if not l.get("concluida_em")]

    def fetchall(self) -> list[LinhaFalsa]:
        return [LinhaFalsa(l) for l in self._filtradas()]

    def fetchone(self) -> LinhaFalsa:
        return LinhaFalsa({"n": len(self._filtradas())})


def linha(
    revisor: str,
    *,
    revisor_id: str | None,
    inicio: str = "2026-09-01T10:00:00+00:00",
    fim: str | None = "2026-09-01T10:05:00+00:00",
    resultado: str = "aprovada",
) -> dict[str, Any]:
    return {
        "revisor": revisor,
        "revisor_id": revisor_id,
        "iniciada_em": inicio,
        "concluida_em": fim,
        "resultado": resultado,
    }


ACERVO = [
    # Duas "Ana Silva" DIFERENTES — é o caso que o filtro por nome confundia.
    linha("Ana Silva", revisor_id="u-1", fim="2026-09-01T10:05:00+00:00"),
    linha("Ana Silva", revisor_id="u-1", fim="2026-09-01T10:15:00+00:00", resultado="ajustes"),
    linha("Ana Silva", revisor_id="u-2", fim="2026-09-01T10:20:00+00:00"),
    # Linha ANTIGA da primeira Ana: gravada antes de `revisor_id` existir.
    linha("Ana Silva", revisor_id=None, fim="2026-09-01T11:00:00+00:00"),
    linha("Bruno Costa", revisor_id="u-3", fim="2026-09-01T10:02:00+00:00"),
    # Revisão ABERTA: não tem duração, e não pode entrar na média.
    linha("Ana Silva", revisor_id="u-1", fim=None),
]


def usar(linhas: list[dict[str, Any]]) -> ConexaoFalsa:
    conexao = ConexaoFalsa(linhas)
    revisao.conectar = lambda *a, **k: conexao  # type: ignore[assignment]
    return conexao


def testar_panorama() -> int:
    falhas = 0
    usar(ACERVO)
    m = revisao.metricas()
    falhas += not checar(m["revisadas"] == 5, f"conta as revisões concluídas (veio {m['revisadas']})")
    falhas += not checar(m["em_andamento"] == 1, f"a aberta conta à parte ({m['em_andamento']})")
    falhas += not checar(m["aprovadas"] == 4 and m["ajustes"] == 1, "separa aprovadas de ajustes")
    # 300 + 900 + 1200 + 3600 + 120 = 6120 / 5 = 1224
    falhas += not checar(m["tempo_medio_s"] == 1224, f"o tempo médio sai em segundos ({m['tempo_medio_s']})")
    nomes = [x["revisor"] for x in m["por_revisor"]]
    falhas += not checar(nomes[0] == "Ana Silva", f"o corte por revisor vem do maior volume ({nomes})")
    return falhas


def testar_recorte_por_identidade() -> int:
    """O critério "métricas são vinculadas ao revisor correto", medido."""
    falhas = 0
    conexao = usar(ACERVO)
    m = revisao.metricas("Ana Silva", "u-1")

    # Duas de u-1 concluídas + a linha antiga sem id, mas NÃO a da homônima u-2.
    falhas += not checar(
        m["revisadas"] == 3,
        f"o recorte pega as do id, mais a linha antiga sem id (veio {m['revisadas']})",
    )
    falhas += not checar(m["em_andamento"] == 1, "e a revisão aberta dela")
    falhas += not checar(
        any("revisor_id = ?" in sql for sql, _ in conexao.consultas),
        "o filtro chega ao banco pelo id, não só pelo nome",
    )
    falhas += not checar(
        all(
            params[:2] == ("u-1", "Ana Silva")
            for sql, params in conexao.consultas
            if "revisor_id = ?" in sql
        ),
        "id primeiro, nome como reserva das linhas antigas",
        str(conexao.consultas),
    )

    # A homônima vê SÓ o que é dela. Era exatamente isto que o nome misturava.
    outra = revisao.metricas("Ana Silva", "u-2")
    falhas += not checar(
        outra["revisadas"] == 2,
        f"a homônima vê as próprias (1) + a antiga sem id (1) = 2, e não as 3 da outra ({outra['revisadas']})",
    )
    return falhas


def testar_sem_id_cai_no_nome() -> int:
    """Sessão sem id (ou chamada antiga) continua respondendo pelo nome."""
    falhas = 0
    conexao = usar(ACERVO)
    m = revisao.metricas("Bruno Costa")
    falhas += not checar(m["revisadas"] == 1, f"filtra pelo nome quando não há id ({m['revisadas']})")
    falhas += not checar(
        all("revisor_id = ?" not in sql for sql, _ in conexao.consultas),
        "e aí o SQL não menciona id nenhum",
    )
    return falhas


def testar_tempo_torto_nao_derruba() -> int:
    falhas = 0
    usar(
        [
            linha("Ana Silva", revisor_id="u-1", inicio="data ruim", fim="2026-09-01T10:05:00+00:00"),
            linha("Ana Silva", revisor_id="u-1", fim="2026-09-01T10:10:00+00:00"),
            # Concluída ANTES de iniciada (relógio do servidor corrigido no meio):
            # duração negativa viraria média negativa.
            linha(
                "Ana Silva",
                revisor_id="u-1",
                inicio="2026-09-01T10:30:00+00:00",
                fim="2026-09-01T10:00:00+00:00",
            ),
        ]
    )
    m = revisao.metricas()
    falhas += not checar(m["revisadas"] == 3, "a linha com data torta continua contando como revisão")
    falhas += not checar(
        m["tempo_medio_s"] == 200,
        f"a duração impossível entra como zero, não como negativo ({m['tempo_medio_s']})",
    )
    falhas += not checar(
        revisao._duracao_s("2026-09-01T10:30:00+00:00", "2026-09-01T10:00:00+00:00") == 0,
        "tempo que anda para trás é zero",
    )
    return falhas


def testar_aviso_de_uso() -> int:
    """A issue pede expressamente que a métrica não seja lida como qualidade."""
    falhas = 0
    usar(ACERVO)
    aviso = revisao.metricas().get("aviso") or ""
    falhas += not checar(
        "qualidade" in aviso.lower(),
        "o painel vai com a ressalva de que não mede qualidade",
        aviso,
    )
    return falhas


def main_teste() -> int:
    original = revisao.conectar
    falhas = 0
    try:
        for titulo, teste in (
            ("1. Panorama do escritório", testar_panorama),
            ("2. Recorte por identidade, não por nome", testar_recorte_por_identidade),
            ("3. Sem id, vale o nome", testar_sem_id_cai_no_nome),
            ("4. Data torta não derruba a métrica", testar_tempo_torto_nao_derruba),
            ("5. A ressalva da issue", testar_aviso_de_uso),
        ):
            print(f"\n{titulo}")
            falhas += teste()
    finally:
        revisao.conectar = original  # type: ignore[assignment]
    print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
