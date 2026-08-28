"""Descobre se mais de um backend responde pelo nome `ia-juridica`.

O sintoma que trouxe este script: `POST /cases` devolve 201, o worker classifica aquele
caso (a saúde mostra `case_classifier` com sucesso 1.0), e mesmo assim o `GET` seguinte
do MESMO identificador responde 404. Uma linha não pode existir para o worker e não
existir para a API se os dois olharem o mesmo banco.

A hipótese que sobra é DNS: se duas pilhas atendem pelo alias `ia-juridica` na rede
`traefik-public`, cada requisição do Acervo cai numa delas, com bancos diferentes. Criar
num backend e ler no outro dá exatamente 404 alternado.

O teste é de leitura pura: bate N vezes em `/api/agente/saude`, que o Acervo repassa ao
agente, e compara um contador que só cresce (execuções por agente). Um backend só produz
uma sequência monotônica. Dois backends produzem valores que **alternam para trás**.

Uso:

    ./.venv/Scripts/python.exe scripts/diag_backends.py [--vezes 12] [--base URL]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from scripts.diag_pipeline import carregar_env  # noqa: E402


def assinatura(corpo: Any) -> tuple[str, ...]:
    """Contadores que identificam a instância: execuções por agente e latência do banco.

    Escolhidos porque só crescem. Um valor que DIMINUI entre duas chamadas seguidas não é
    flutuação: é outra máquina, com outro banco, respondendo pelo mesmo nome.
    """
    if not isinstance(corpo, dict):
        return ("resposta-nao-json",)
    agentes = corpo.get("agents", {}).get("by_agent", []) or []
    return tuple(f"{a.get('agent_name')}={a.get('runs')}" for a in agentes)


def main() -> int:
    analisador = argparse.ArgumentParser(description=__doc__)
    analisador.add_argument("--vezes", type=int, default=12)
    analisador.add_argument("--base", default="https://advocacia.levelhom.com.br")
    argumentos = analisador.parse_args()

    base = argumentos.base.rstrip("/")
    segredo = carregar_env(RAIZ / ".env").get("JWT_SECRET", "")
    if not segredo:
        print("JWT_SECRET ausente no .env.")
        return 2
    os.environ["JWT_SECRET"] = segredo
    os.environ["JWT_ISSUER"] = base
    os.environ["JWT_AUDIENCE"] = base
    from app.auth import gerar_token

    token = gerar_token(
        codigo="diag", nome="Diagnostico", email="diag@acervo.local", perfil="advogado"
    )

    vistas: Counter[tuple[str, ...]] = Counter()
    sequencia: list[tuple[str, ...]] = []
    for indice in range(argumentos.vezes):
        requisicao = urllib.request.Request(f"{base}/api/agente/saude")
        requisicao.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(requisicao, timeout=60) as resposta:
                corpo = json.loads(resposta.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as erro:
            print(f"{indice:>3}: HTTP {erro.code}")
            continue
        except Exception as erro:  # noqa: BLE001
            print(f"{indice:>3}: rede: {erro}")
            continue
        atual = assinatura(corpo)
        vistas[atual] += 1
        sequencia.append(atual)
        print(f"{indice:>3}: {' '.join(atual) or '(sem agentes)'}")

    print("\n=========== VEREDITO ===========")
    print(f"assinaturas distintas: {len(vistas)}")
    regrediu = any(
        any(
            int(b.split("=")[1]) < int(a.split("=")[1])
            for a, b in zip(anterior, seguinte, strict=False)
            if a.split("=")[0] == b.split("=")[0]
            and a.split("=")[1].isdigit()
            and b.split("=")[1].isdigit()
        )
        for anterior, seguinte in zip(sequencia, sequencia[1:], strict=False)
    )
    if regrediu:
        print(
            "DOIS BACKENDS: um contador que so cresce DIMINUIU entre chamadas seguidas.\n"
            "O nome `ia-juridica` esta resolvendo para mais de uma pilha, com bancos\n"
            "diferentes. Criar num e ler no outro e o 404."
        )
    elif len(vistas) <= 1:
        print("um backend so (contadores estaveis) — a causa do 404 esta em outro lugar.")
    else:
        print("contadores variaram sempre para cima: compativel com um backend so em uso.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
