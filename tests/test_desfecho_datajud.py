"""A regra que transforma movimento do CNJ em desfecho do processo.

POR QUE ESTA REGRA MERECE TESTE PRÓPRIO

O rótulo que ela devolve entra direto na estatística que o advogado lê para decidir
se entra com a ação ("24/30 favoráveis no mérito", em `rag._estatisticas_amostra`).
Um PROCEDENTE onde era IMPROCEDENTE não aparece como erro na tela: aparece como um
número um pouco diferente, e ninguém tem como desconfiar.

A armadilha principal é linguística e está coberta abaixo: "improcedência" e
"procedência em parte" CONTÊM a palavra "procedência". Testar na ordem errada
transforma derrota em vitória.

Sem rede: o que se testa é a função pura sobre payloads como o DataJud os devolve.

Rodar: .venv\\Scripts\\python.exe -m tests.test_desfecho_datajud
"""

from __future__ import annotations

import sys

# O console do Windows abre em cp1252 e os rótulos aqui usam a seta. Sem isto o
# teste morre ao IMPRIMIR o resultado, não ao verificá-lo (mesmo caso de
# `tests/test_assinatura.py`).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from scripts import enriquecer_desfechos_datajud as enriquecedor
from scripts.enriquecer_desfechos_datajud import (
    ACORDO,
    IMPROCEDENTE,
    PARCIAL,
    PROCEDENTE,
    SEM_DADO,
    _alias_do_tribunal,
    desfecho_do_processo,
    rotulo_do_movimento,
)


def checar(condicao: bool, texto: str, detalhe: str = "") -> bool:
    print(("  PASS  " if condicao else "  FALHA ") + texto + (f"\n          {detalhe}" if not condicao and detalhe else ""))
    return condicao


def testar_nomes_parecidos() -> int:
    """"Improcedência" e "procedência em parte" contêm "procedência"."""
    falhas = 0
    casos = (
        (219, "Procedência", PROCEDENTE),
        (220, "Improcedência", IMPROCEDENTE),
        (221, "Procedência em Parte", PARCIAL),
        (466, "Homologação de Acordo", ACORDO),
        # Como os tribunais realmente escrevem, com variação de caixa e acento.
        (0, "IMPROCEDENCIA DOS PEDIDOS", IMPROCEDENTE),
        (0, "Julgamento parcialmente procedente", PARCIAL),
        (0, "procedencia do pedido", PROCEDENTE),
        (0, "Homologação de transação", ACORDO),
    )
    for codigo, nome, esperado in casos:
        obtido = rotulo_do_movimento(codigo, nome)
        falhas += not checar(obtido == esperado, f"{nome!r} → {esperado}", f"veio {obtido!r}")
    return falhas


def testar_movimento_que_nao_julga() -> int:
    """Distribuição, juntada e audiência NÃO são desfecho."""
    falhas = 0
    for nome in (
        "Distribuição",
        "Juntada de petição",
        "Audiência designada",
        "Expedição de intimação",
        "Recebimento",
        "",
    ):
        obtido = rotulo_do_movimento(26, nome)
        falhas += not checar(obtido == "", f"{nome or '(vazio)'!r} não vira desfecho", f"veio {obtido!r}")
    return falhas


def testar_vale_o_julgamento_mais_recente() -> int:
    """Sentença reformada em recurso deixa os dois movimentos. Vale o último."""
    falhas = 0
    fonte = {
        "orgaoJulgador": {"nome": "18ª VARA DO TRABALHO DE BELÉM"},
        "movimentos": [
            {"codigo": 26, "nome": "Distribuição", "dataHora": "2024-01-10T09:00:00"},
            {"codigo": 220, "nome": "Improcedência", "dataHora": "2024-06-01T12:00:00"},
            {"codigo": 221, "nome": "Procedência em Parte", "dataHora": "2025-02-20T15:00:00"},
        ],
    }
    rotulo, orgao = desfecho_do_processo(fonte)
    falhas += not checar(rotulo == PARCIAL, f"o julgamento mais recente vence (veio {rotulo!r})")
    falhas += not checar(orgao == "18ª VARA DO TRABALHO DE BELÉM", "o órgão julgador vem oficial")

    # Sem nenhum julgamento: o processo fica SEM rótulo, mas o órgão ainda serve —
    # é o que tira "órgão não informado" da lista de decisões consultadas.
    andando = {
        "orgaoJulgador": {"nome": "5ª VARA DO TRABALHO DE BELÉM"},
        "movimentos": [{"codigo": 26, "nome": "Distribuição", "dataHora": "2026-01-01T09:00:00"}],
    }
    rotulo2, orgao2 = desfecho_do_processo(andando)
    falhas += not checar(
        rotulo2 == "" and orgao2 == "5ª VARA DO TRABALHO DE BELÉM",
        f"processo em andamento: sem rótulo, com órgão ({rotulo2!r})",
    )
    falhas += not checar(
        desfecho_do_processo({}) == ("", ""), "documento vazio não inventa nada"
    )
    return falhas


def testar_alias_do_tribunal() -> int:
    """O índice do DataJud é por tribunal, e sai do próprio número CNJ."""
    falhas = 0
    falhas += not checar(_alias_do_tribunal("00005493520255080018") == "trt8", "TRT8 pelo número")
    falhas += not checar(_alias_do_tribunal("0000549-35.2025.5.02.0001") == "trt2", "TRT2, com pontuação")
    # Fora da Justiça do Trabalho não há índice conhecido aqui: não se consulta.
    falhas += not checar(_alias_do_tribunal("00001234520234036100") == "", "outro segmento não tem alias")
    falhas += not checar(_alias_do_tribunal("123") == "", "número curto não tem alias")
    falhas += not checar(_alias_do_tribunal("00005493520255990018") == "", "regional 99 não existe")
    return falhas


class _CursorFalso:
    """Guarda a consulta e os parametros, e devolve fila vazia."""

    def __init__(self) -> None:
        self.sql = ""
        self.parametros: tuple = ()

    def execute(self, sql, parametros=None):
        self.sql = sql
        self.parametros = parametros or ()
        return self

    def fetchall(self):
        return []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def testar_fila_nao_reconsulta() -> int:
    """A fila da proxima passada nao pode devolver processo ja consultado.

    POR QUE ISTO MERECE TESTE

    A cota da API do CNJ e o unico recurso escasso do script. Processo em andamento
    (tem vara, nao tem julgamento) e processo que o CNJ nao conhece nao produzem
    rotulo nenhum: se voltarem para a fila, cada passada seguinte gasta a cota para
    receber o mesmo nada, e o desperdicio cresce justamente quando o resto ja foi
    preenchido. O teste olha a consulta que monta a fila, sem tocar no banco.
    """
    falhas = 0
    cursor = _CursorFalso()
    original = enriquecedor.psycopg.connect
    enriquecedor.psycopg.connect = lambda *a, **k: cursor
    try:
        enriquecedor.processos_sem_rotulo(10, "datajud_djen")
        sql_normal, par_normal = cursor.sql, cursor.parametros
        enriquecedor.processos_sem_rotulo(10, "datajud_djen", rever_sem_dado=True)
        par_rever = cursor.parametros
    finally:
        enriquecedor.psycopg.connect = original

    falhas += not checar("'orgao_julgador') IS NULL" in sql_normal, "quem tem vara nao volta a fila")
    falhas += not checar(f"'{SEM_DADO}') IS NULL" in sql_normal, "quem o CNJ nao conhece nao volta a fila")
    falhas += not checar(par_normal[1] is False, f"sem a flag, a marca exclui (veio {par_normal!r})")
    falhas += not checar(par_rever[1] is True, f"--rever-sem-dado traz os marcados (veio {par_rever!r})")
    # A marca e so controle de fila: se ela virasse desfecho, entraria na estatistica.
    falhas += not checar(
        SEM_DADO not in (PROCEDENTE, PARCIAL, IMPROCEDENTE, ACORDO),
        "a marca nao e um desfecho",
    )
    return falhas


def main_teste() -> int:
    falhas = 0
    for titulo, teste in (
        ("1. Nomes que se parecem e significam o oposto", testar_nomes_parecidos),
        ("2. Movimento que não é julgamento", testar_movimento_que_nao_julga),
        ("3. Vale o julgamento mais recente", testar_vale_o_julgamento_mais_recente),
        ("4. Qual índice consultar", testar_alias_do_tribunal),
        ("5. A fila não reconsulta o que já foi perguntado", testar_fila_nao_reconsulta),
    ):
        print(f"\n{titulo}")
        falhas += teste()
    print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
