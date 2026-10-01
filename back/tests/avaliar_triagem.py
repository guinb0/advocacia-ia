"""Mede a acurácia da triagem contra entrevistas geradas por um LLM.

Por que existe: as entrevistas de teste que eu escreveria seriam enviesadas —
quem escreve as pistas do classificador escreve os testes com as mesmas palavras,
e o resultado dá 100% sem provar nada. Aqui um modelo externo escreve os relatos
sem ver as pistas, então o vocabulário é independente.

    .venv\\Scripts\\python.exe -m tests.avaliar_triagem            # 3 por categoria
    .venv\\Scripts\\python.exe -m tests.avaliar_triagem 6          # 6 por categoria

A chave sai de `dados/.env.local` (fora do versionamento) ou da variável de
ambiente DEEPSEEK_API_KEY. Nada é gravado com a chave dentro.

Limite honesto do número: isto mede acerto em relato SINTÉTICO. Serve para achar
buraco de vocabulário e regressão, não para prometer acurácia em cliente real.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

from app import triagem

URL = "https://api.deepseek.com/chat/completions"
MODELO = "deepseek-chat"

CATEGORIAS = {
    "acidente_trabalho_correios": "acidente de trabalho sofrido por empregado dos Correios (ECT)",
    "acidente_trabalho_geral": "acidente de trabalho em empresa comum, não os Correios",
    "doenca_ocupacional": "doença adquirida ou agravada pelo trabalho, de instalação gradual",
    "assalto_carteiro": "assalto/roubo sofrido por carteiro durante a jornada",
    "auxilio_acidente": "pedido de auxílio-acidente ao INSS por sequela que reduz a capacidade",
}

PROMPT = """Você é um advogado trabalhista brasileiro. Escreva {n} relatos DIFERENTES
de entrevista inicial de cliente, cada um descrevendo um caso de: {descricao}.

Regras:
- Português brasileiro informal, como o advogado anota depois de ouvir o cliente.
- 3 a 6 linhas cada. Comece com "Nome: <nome plausível>".
- Use o vocabulário que um cliente REAL usaria, não jargão jurídico.
- NÃO use o nome da categoria nem termos de classificação.
- Varie profissão, cidade e circunstância.

Responda APENAS um JSON: {{"relatos": ["texto 1", "texto 2", ...]}}"""


def carregar_chave() -> str:
    chave = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if chave:
        return chave
    env = Path(__file__).resolve().parent.parent / "dados" / ".env.local"
    if env.is_file():
        for linha in env.read_text(encoding="utf-8").splitlines():
            if linha.startswith("DEEPSEEK_API_KEY="):
                return linha.split("=", 1)[1].strip()
    raise SystemExit("Defina DEEPSEEK_API_KEY ou grave em dados/.env.local")


def gerar(chave: str, codigo: str, descricao: str, n: int) -> list[str]:
    r = httpx.post(
        URL,
        headers={"Authorization": f"Bearer {chave}", "Content-Type": "application/json"},
        json={
            "model": MODELO,
            "messages": [{"role": "user", "content": PROMPT.format(n=n, descricao=descricao)}],
            "temperature": 1.0,  # variedade importa mais que consistência aqui
            "response_format": {"type": "json_object"},
        },
        timeout=180,
    )
    r.raise_for_status()
    conteudo = r.json()["choices"][0]["message"]["content"]
    return json.loads(conteudo).get("relatos", [])


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    chave = carregar_chave()

    print(f"Gerando {n} relatos por categoria com {MODELO}…\n", flush=True)

    amostras: list[tuple[str, str]] = []
    for codigo, descricao in CATEGORIAS.items():
        try:
            relatos = gerar(chave, codigo, descricao, n)
            amostras += [(codigo, t) for t in relatos if isinstance(t, str) and t.strip()]
            print(f"  {codigo:30} {len(relatos)} relatos", flush=True)
        except Exception as exc:
            print(f"  {codigo:30} FALHOU: {exc}", flush=True)
        time.sleep(1)

    if not amostras:
        print("\nNenhum relato gerado.")
        return 1

    total = len(amostras)
    resumo = {}

    # Os dois métodos veem exatamente as mesmas amostras — é o que torna a
    # comparação honesta.
    for rotulo, fn in (("PISTAS (local)", triagem.classificar_entrevista),
                       ("LLM (deepseek)", triagem.classificar_com_llm)):
        acertos = confiantes = confiantes_certos = 0
        confusao: Counter[tuple[str, str]] = Counter()
        erros: list[tuple[str, str, str]] = []

        for esperado, texto in amostras:
            r = fn(texto)
            if not r or "_erro" in r:
                obtido = "—"
                r = {"sugestoes": [], "confiante": False}
            else:
                obtido = r["sugestoes"][0]["codigo"] if r["sugestoes"] else "—"
            ok = obtido == esperado
            acertos += ok
            if r.get("confiante"):
                confiantes += 1
                confiantes_certos += ok
            if not ok:
                confusao[(esperado, obtido)] += 1
                erros.append((esperado, obtido, " ".join(texto.split())[:130]))
            if fn is triagem.classificar_com_llm:
                time.sleep(0.3)  # não estourar limite de taxa

        resumo[rotulo] = (acertos, confiantes, confiantes_certos, confusao, erros)

    print(f"\n{'='*74}")
    print(f"{'MÉTODO':18} {'ACERTOS':>12} {'CONFIANTE':>12} {'ACERTO SE CONFIANTE':>22}")
    print("-" * 74)
    for rotulo, (a, c, cc, _, _) in resumo.items():
        conf_txt = f"{cc}/{c} = {cc/c:.0%}" if c else "—"
        print(f"{rotulo:18} {a}/{total} = {a/total:>4.0%} {c/total:>11.0%} {conf_txt:>22}")

    for rotulo, (_, _, _, confusao, erros) in resumo.items():
        if not confusao:
            continue
        print(f"\n{'-'*74}\n{rotulo} — confusões (esperado -> sugerido)")
        for (esp, obt), q in confusao.most_common(6):
            print(f"  {q}x  {esp}  ->  {obt}")
        for esp, obt, trecho in erros[:3]:
            print(f"    · {esp} lido como {obt}: {trecho[:110]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
