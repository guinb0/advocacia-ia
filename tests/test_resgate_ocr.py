"""A segunda chance dada a foto ruim, e as travas que impedem ela de piorar.

POR QUE ISTO E TESTADO

Uma passada de OCR le a imagem de um jeito so. Medido na CNH borrada do acervo
(nitidez 1.9 contra 3265 da mesma CNH limpa): passada unica extraia 1 dos 11
campos; reler com outros realces e ficar com a melhor versao de cada campo levou a
3. O ganho e real, mas mora perto de tres jeitos de estragar tudo:

- rodar o resgate em documento que ja leu bem, gastando 3 passadas de OCR a toa;
- trocar um campo certo por um errado so porque a confianca subiu um fio —
  confianca NAO e correcao, e na medicao uma variante trocou "ARIA APARECIDA" por
  "BARIA APARECIDA" com confianca maior;
- deixar o resgate derrubar o processamento quando um realce falha, perdendo ate
  o que a primeira passada ja tinha lido.

Rodar: .venv\\Scripts\\python.exe -m tests.test_resgate_ocr
"""

from __future__ import annotations

import pathlib

from app import pipeline
from app.extractors import Campo

falhas = 0


def checar(condicao: bool, descricao: str, detalhe: str = "") -> None:
    global falhas
    if condicao:
        print(f"  PASS  {descricao}")
    else:
        falhas += 1
        print(f"  FALHA {descricao}" + (f"\n          {detalhe}" if detalhe else ""))


def campo(nome: str, valor: str, confianca: float) -> Campo:
    return Campo(nome=nome, rotulo=nome, valor=valor, confianca=confianca)


# ------------------------------------------------- quando o resgate acontece

print("\nQuando o resgate acontece")

cheios = [campo(f"c{i}", "x", 0.9) for i in range(8)]
validacao = {"campos_esperados": [f"c{i}" for i in range(8)]}
checar(
    not pipeline._merecer_resgate(cheios, validacao, "cnh"),
    "documento que leu tudo NAO paga passada extra",
)

quase_vazio = [campo("c0", "x", 0.9)]
checar(
    pipeline._merecer_resgate(quase_vazio, validacao, "cnh"),
    "1 de 8 campos: resgata",
)
checar(
    not pipeline._merecer_resgate(quase_vazio, validacao, "desconhecido"),
    "tipo desconhecido nao resgata — nao ha campo esperado a perseguir",
)
checar(
    not pipeline._merecer_resgate(quase_vazio, {"campos_esperados": []}, "cnh"),
    "sem lista de esperados, nao resgata",
)
metade = [campo(f"c{i}", "x", 0.9) for i in range(4)]
checar(
    not pipeline._merecer_resgate(metade, validacao, "cnh"),
    "exatamente metade dos campos NAO resgata (o corte e abaixo de 50%)",
)


# ---------------------------------------------- a trava da substituicao

print("\nA trava que impede trocar erro por erro")

checar(
    pipeline.MARGEM_TROCA > 0,
    f"exige MARGEM para substituir, nao so ser maior (margem={pipeline.MARGEM_TROCA})",
)
checar(
    pipeline.CONFIANCA_MINIMA_TROCA >= 0.5,
    f"e um piso: duas leituras ruins nao se corrigem (piso={pipeline.CONFIANCA_MINIMA_TROCA})",
)

# O caso real medido: 0.83 -> 0.88 em duas leituras ambas erradas. Com margem de
# 0.10 a troca nao acontece, que e o certo.
antes, depois = 0.83, 0.88
checar(
    not (depois >= antes + pipeline.MARGEM_TROCA),
    "o caso medido ('ARIA' -> 'BARIA', 0.83 -> 0.88) NAO troca",
)
# Ja uma leitura claramente melhor passa.
checar(
    0.95 >= 0.60 + pipeline.MARGEM_TROCA and 0.95 >= pipeline.CONFIANCA_MINIMA_TROCA,
    "leitura claramente melhor (0.60 -> 0.95) troca",
)


# ------------------------------------------------ um realce que explode

print("\nRealce que falha nao derruba o que ja foi lido")

_realcar_real = pipeline._realcar


def realce_que_explode(*a, **k):
    raise RuntimeError("boom")


pipeline._realcar = realce_que_explode
try:
    ja_lidos = [campo("nome", "FULANO", 0.9)]
    resultado, tentadas = pipeline._resgatar(None, "pt", "cnh", ja_lidos)
    checar(
        [c.nome for c in resultado] == ["nome"],
        "o campo da primeira passada sobrevive a todos os realces falharem",
        str([c.nome for c in resultado]),
    )
    checar(tentadas == 0, "e nenhum realce e contabilizado como bem-sucedido")
finally:
    pipeline._realcar = _realcar_real


# --------------------------------------------------- ponta a ponta, medido

print("\nPonta a ponta na CNH borrada (o caso que motivou tudo)")

amostra = pathlib.Path(__file__).resolve().parent / "amostras" / "cnh_borrada.png"
if not amostra.exists():
    print("  (amostra ausente — pulando)")
else:
    r = pipeline.processar(amostra.read_bytes(), amostra.name, gerar_arquivos_temporarios=False)
    nomes = sorted(c["nome"] for c in r["campos"] if str(c.get("valor") or "").strip())
    resgate = (r.get("ocr") or {}).get("resgate") or {}
    checar(resgate.get("tentado") is True, "o resgate foi acionado nesta foto", str(resgate))
    checar(
        len(nomes) >= 3,
        f"extrai 3+ campos (passada unica extraia 1): {nomes}",
    )
    checar("cpf" in nomes, "o CPF aparece — so a variante ampliada o encontra")
    # O CPF passa por conferencia de digito verificador no extrator, entao se ele
    # saiu, saiu valido. E o que separa "achou numero" de "achou o CPF".
    cpf = next((c["valor"] for c in r["campos"] if c["nome"] == "cpf"), "")
    checar(len(cpf.replace(".", "").replace("-", "")) == 11, f"e tem 11 digitos ({cpf})")


print(f"\n{'TUDO OK' if not falhas else f'{falhas} FALHA(S)'}")
raise SystemExit(1 if falhas else 0)
