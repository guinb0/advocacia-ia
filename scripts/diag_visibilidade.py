"""O caso criado no agente fica visível para a leitura seguinte? E depois de esperar?

Ponto em que o diagnóstico chegou: `POST /cases` devolve 201, os workers processam aquele
caso (a saúde mostra `case_classifier` e `strategy` subindo), e mesmo assim a leitura
seguinte responde 404 — o Acervo conclui "vínculo órfão" e cria outro caso. Isso se repete
a cada requisição, então documento, fato e classificação nunca se acumulam no mesmo caso.

Sobram duas causas com tratamentos opostos, e este script separa as duas:

  * **visibilidade atrasada** — a escrita vai para o primário e a leitura cai numa réplica
    (ou num pooler em transação já aberta). O caso aparece depois de alguns segundos.
    Conserto: rota de leitura no primário / `pool_pre_ping` / desligar a réplica.
  * **caso nunca gravado para esta organização** — esperar não muda nada. Conserto é outro:
    a linha existe sob `organization_id` diferente do que a leitura filtra.

Método: sincroniza (cria o caso), espera, sincroniza de novo e compara os `caso_ref`.
Se o segundo `caso_ref` for IGUAL ao primeiro, a espera resolveu — é visibilidade.
Se for diferente, esperar não ajudou — é escopo/gravação.

Uso:

    ./.venv/Scripts/python.exe scripts/diag_visibilidade.py <caso_id> [--espera 15]
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from scripts.diag_pipeline import carregar_env, chamar  # noqa: E402


def main() -> int:
    analisador = argparse.ArgumentParser(description=__doc__)
    analisador.add_argument("caso_id")
    analisador.add_argument("--espera", type=int, default=15)
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
    alvo = f"{base}/api/agente/casos/{argumentos.caso_id}/sincronizar"

    status, primeiro = chamar("POST", alvo, token, {})
    ref_1 = primeiro.get("caso_ref") if isinstance(primeiro, dict) else None
    print(f"1a sincronizacao  HTTP {status}  caso_ref={ref_1}")

    status, imediato = chamar("POST", alvo, token, {})
    ref_2 = imediato.get("caso_ref") if isinstance(imediato, dict) else None
    print(f"2a imediata       HTTP {status}  caso_ref={ref_2}")

    print(f"\nesperando {argumentos.espera}s...")
    time.sleep(argumentos.espera)

    status, depois = chamar("POST", alvo, token, {})
    ref_3 = depois.get("caso_ref") if isinstance(depois, dict) else None
    pipeline = depois.get("pipeline_juridico") if isinstance(depois, dict) else None
    print(f"3a apos espera    HTTP {status}  caso_ref={ref_3}  pipeline={pipeline}")

    print("\n=========== VEREDITO ===========")
    if ref_2 and ref_2 == ref_1:
        print("caso visivel de imediato — a recriacao ja parou; o problema estava alhures.")
    elif ref_3 and ref_3 == ref_2:
        print(
            "VISIBILIDADE ATRASADA: a leitura so encontra o caso depois de alguns segundos.\n"
            "Escrita e leitura nao estao no mesmo no do banco (replica ou pooler)."
        )
    else:
        print(
            "GRAVACAO/ESCOPO: esperar nao mudou nada, cada chamada cria outro caso.\n"
            "A leitura filtra por um organization_id diferente do que a escrita gravou."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
