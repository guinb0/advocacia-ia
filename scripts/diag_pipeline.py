"""Diagnóstico do pipeline jurídico contra um Acervo no ar.

Existe por um sintoma que só aparece em produção: o dossiê mostra "Falta fazer" em
classificação, jurisprudência, estratégia e petição, e o log da IA Jurídica responde
404 em `GET /api/v1/cases/{ref}/strategy`. Esse 404 não é "não há estratégia" — essa
rota devolve 204 nesse caso. É a dependência `require_case` dizendo que o **caso** não
existe no banco do agente. Este script mede exatamente isso, de fora, sem adivinhação:

  1. o Acervo enxerga o agente? (`GET /api/agente/saude`)
  2. qual `caso_ref` o dossiê carrega agora?
  3. o `caso_ref` continua o MESMO depois de sincronizar e analisar?

O passo 3 é o teste que interessa. Se o `caso_ref` mudar entre as chamadas, o Acervo
está recriando o caso a cada ação — `garantir_caso` pergunta `caso_existe`, leva 404,
conclui "vínculo órfão" e cria outro. Documento, entrevista e fato nunca acumulam no
mesmo caso, e toda etapa morre em 404 antes de enfileirar qualquer trabalho.

Uso:

    ./.venv/Scripts/python.exe scripts/diag_pipeline.py <caso_id> [--base URL]

O token de serviço é assinado aqui com o `JWT_SECRET` do `.env` local, com issuer e
audience apontando para a base escolhida — é a mesma sessão que a tela usa. O segredo
nunca é impresso.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parent.parent


def carregar_env(caminho: Path) -> dict[str, str]:
    """Lê o `.env` sem depender de python-dotenv, que é dependência de app e não de script."""
    valores: dict[str, str] = {}
    if not caminho.exists():
        return valores
    for linha in caminho.read_text(encoding="utf-8", errors="replace").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        valores[chave.strip()] = valor.strip().strip('"').strip("'")
    return valores


def chamar(
    metodo: str, url: str, token: str, corpo: dict[str, Any] | None = None
) -> tuple[int, Any]:
    """Uma chamada, devolvendo status e corpo já decodificado quando for JSON.

    Erro HTTP não levanta: o 404 e o 422 **são** o dado que este script procura, e
    interromper no primeiro deles esconderia o resto da sequência.
    """
    dados = json.dumps(corpo).encode() if corpo is not None else None
    requisicao = urllib.request.Request(url, data=dados, method=metodo)
    requisicao.add_header("Authorization", f"Bearer {token}")
    if dados is not None:
        requisicao.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(requisicao, timeout=180) as resposta:
            bruto = resposta.read().decode("utf-8", "replace")
            status = resposta.status
    except urllib.error.HTTPError as erro:
        bruto = erro.read().decode("utf-8", "replace")
        status = erro.code
    except Exception as erro:  # noqa: BLE001 - rede fora do ar é resultado, não exceção do script
        return 0, {"erro_de_rede": str(erro)}
    try:
        return status, json.loads(bruto)
    except json.JSONDecodeError:
        return status, bruto[:2000]


def resumir(rotulo: str, status: int, corpo: Any) -> None:
    texto = json.dumps(corpo, ensure_ascii=False)[:1200] if not isinstance(corpo, str) else corpo
    print(f"\n--- {rotulo} :: HTTP {status}")
    print(texto)


def ref_do_dossie(corpo: Any) -> str | None:
    if not isinstance(corpo, dict):
        return None
    for chave in ("caso_ref", "case_ref", "agente_ref"):
        if corpo.get(chave):
            return str(corpo[chave])
    agente = corpo.get("agente")
    if isinstance(agente, dict) and agente.get("caso_ref"):
        return str(agente["caso_ref"])
    return None


def main() -> int:
    analisador = argparse.ArgumentParser(description=__doc__)
    analisador.add_argument("caso_id", help="UUID do caso no Acervo")
    analisador.add_argument("--base", default="https://advocacia.levelhom.com.br")
    argumentos = analisador.parse_args()

    base = argumentos.base.rstrip("/")
    env = carregar_env(RAIZ / ".env")
    segredo = env.get("JWT_SECRET", "")
    if not segredo:
        print("JWT_SECRET ausente no .env — sem ele não há como assinar a sessão.")
        return 2

    # Precisa vir antes do import: `app.auth` lê o segredo no import do módulo.
    os.environ["JWT_SECRET"] = segredo
    os.environ["JWT_ISSUER"] = base
    os.environ["JWT_AUDIENCE"] = base
    sys.path.insert(0, str(RAIZ))
    from app.auth import gerar_token

    token = gerar_token(
        codigo="diag", nome="Diagnostico", email="diag@acervo.local", perfil="advogado"
    )

    caso = argumentos.caso_id
    raiz_caso = f"{base}/api/agente/casos/{caso}"

    status, corpo = chamar("GET", f"{base}/api/agente/saude", token)
    resumir("saude do agente", status, corpo)

    status, dossie_antes = chamar("GET", raiz_caso, token)
    resumir("dossie ANTES", status, dossie_antes)
    ref_antes = ref_do_dossie(dossie_antes)

    status, corpo = chamar("POST", f"{raiz_caso}/sincronizar", token, {})
    resumir("sincronizar", status, corpo)
    ref_sync = ref_do_dossie(corpo)

    status, corpo = chamar("POST", f"{raiz_caso}/analise", token)
    resumir("analise (classificacao + jurisprudencia)", status, corpo)

    status, corpo = chamar("POST", f"{raiz_caso}/estrategia", token)
    resumir("estrategia", status, corpo)

    status, dossie_depois = chamar("GET", raiz_caso, token)
    resumir("dossie DEPOIS", status, dossie_depois)
    ref_depois = ref_do_dossie(dossie_depois)

    print("\n=========== VEREDITO ===========")
    print(f"caso_ref antes      : {ref_antes}")
    print(f"caso_ref sincronizar: {ref_sync}")
    print(f"caso_ref depois     : {ref_depois}")
    refs = {r for r in (ref_antes, ref_sync, ref_depois) if r}
    if len(refs) > 1:
        print(
            "LACO DE RECRIACAO CONFIRMADO: o caso muda de identidade entre as chamadas.\n"
            "Toda etapa aponta para um caso que o agente ja considera inexistente."
        )
    elif refs:
        print("caso_ref estavel — a recriacao NAO e a causa; olhar o worker da IA Juridica.")
    else:
        print("nenhum caso_ref no dossie — o vinculo com o agente nao chegou a ser criado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
