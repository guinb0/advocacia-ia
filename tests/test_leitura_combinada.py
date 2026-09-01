"""A leitura do caso inteiro depois que a entrevista chega no agente.

O agente e o banco sao dublados: o que se testa aqui e a ORDEM e a espera, nao a
qualidade da classificacao — essa e do outro lado da ponte.

O que esta coberto e o que estraga a leitura se quebrar:

- pesquisar jurisprudencia ANTES de a classificacao ficar pronta. A pesquisa sai
  "a partir das questoes do caso", e as questoes sao produto da analise: disparar
  junto devolve pesquisa vazia, que e pior que nao ter rodado porque parece
  resposta;
- reanalisar quando a entrevista ja tinha sido lida antes, gastando duas chamadas
  de modelo para chegar ao mesmo lugar;
- desistir da pesquisa por um soluco de rede no meio da espera;
- deixar a falha do agente escapar e derrubar a thread que roda depois de o
  atendimento ja estar salvo.

Rodar: .venv\\Scripts\\python.exe -m tests.test_leitura_combinada
"""

from __future__ import annotations

import os

os.environ["JWT_SECRET"] = ""

from app.agente import espelho  # noqa: E402
from app.agente.cliente import ErroDoAgente  # noqa: E402

falhas = 0


def checar(condicao: bool, descricao: str, detalhe: str = "") -> None:
    global falhas
    if condicao:
        print(f"  PASS  {descricao}")
    else:
        falhas += 1
        print(f"  FALHA {descricao}" + (f"\n          {detalhe}" if detalhe else ""))


class ClienteFalso:
    """O agente do outro lado, com a analise ficando pronta quando mandarmos."""

    def __init__(self, pronta_na_leitura=1, erro_ate=0):
        self.chamadas: list[str] = []
        self.leituras = 0
        self.pronta_na_leitura = pronta_na_leitura
        self.erro_ate = erro_ate

    def analisar(self, caso_ref):
        self.chamadas.append("analisar")
        return {"accepted": True}

    def analise(self, caso_ref):
        self.leituras += 1
        self.chamadas.append("analise")
        if self.leituras <= self.erro_ate:
            raise ErroDoAgente("rede fora")
        pronta = self.leituras >= self.pronta_na_leitura
        return {"classifications": [{"code": "ACIDENTE"}] if pronta else []}

    def pesquisar(self, caso_ref):
        self.chamadas.append("pesquisar")
        return {"accepted": True}


def montar(**kwargs):
    """Instala os dubles e devolve o cliente falso. Sem espera de verdade."""
    falso = ClienteFalso(**kwargs)
    espelho.Cliente = lambda *a, **k: falso
    espelho.garantir_caso = lambda caso_id, **k: {"caso_ref": "CASO-1"}
    espelho.time.sleep = lambda _s: None
    return falso


_cliente_real = espelho.Cliente
_garantir_real = espelho.garantir_caso
_sleep_real = espelho.time.sleep

try:
    # ------------------------------------------------------------- a ordem

    print("\nA ordem entre analise e pesquisa")

    falso = montar(pronta_na_leitura=1)
    r = espelho.analisar_caso_inteiro("c1")
    checar(falso.chamadas[0] == "analisar", "a analise vem primeiro", str(falso.chamadas))
    checar("pesquisar" in falso.chamadas, "a pesquisa e disparada")
    checar(
        falso.chamadas.index("analisar") < falso.chamadas.index("pesquisar"),
        "e a pesquisa NUNCA vem antes da analise",
        str(falso.chamadas),
    )
    checar(r["analise"] and r["pesquisa"], "o resultado diz que as duas rodaram", str(r))

    # ------------------------------------------------------ a espera de verdade

    print("\nA espera pela classificacao")

    falso = montar(pronta_na_leitura=4)
    espelho.analisar_caso_inteiro("c1")
    checar(
        falso.leituras == 4,
        f"espera a classificacao ficar pronta (leu {falso.leituras}x antes de pesquisar)",
    )
    checar(
        falso.chamadas.index("pesquisar") > falso.chamadas.index("analise"),
        "a pesquisa so sai depois de a analise ter classificacao",
    )

    # Classificacao que nunca fica pronta: NAO pesquisa. Uma pesquisa sem questao
    # nenhuma volta vazia parecendo resposta.
    falso = montar(pronta_na_leitura=999)
    r = espelho.analisar_caso_inteiro("c1")
    checar("pesquisar" not in falso.chamadas, "sem classificacao, nao pesquisa")
    checar(r["analise"] and not r["pesquisa"], "e o resultado diz isso", str(r))
    checar(
        falso.leituras == espelho.TENTATIVAS_ANALISE,
        f"tentou {espelho.TENTATIVAS_ANALISE}x e parou (nao fica em laco)",
        str(falso.leituras),
    )

    # ------------------------------------------------------ soluco de rede

    print("\nSoluco de rede no meio da espera")

    falso = montar(pronta_na_leitura=3, erro_ate=2)
    r = espelho.analisar_caso_inteiro("c1")
    checar(
        r["pesquisa"],
        "duas leituras falhando nao fazem desistir da pesquisa",
        str(falso.chamadas),
    )
finally:
    espelho.Cliente = _cliente_real
    espelho.garantir_caso = _garantir_real
    espelho.time.sleep = _sleep_real

print(f"\n{'TUDO OK' if not falhas else f'{falhas} FALHA(S)'}")
raise SystemExit(1 if falhas else 0)
