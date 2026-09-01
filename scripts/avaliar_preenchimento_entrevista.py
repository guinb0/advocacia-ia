"""Avalia o preenchimento consolidado do roteiro a partir de TXT reais.

Uso (na pasta do projeto, com .venv e DEEPSEEK_API_KEY):

    .venv\\Scripts\\python.exe -m scripts.avaliar_preenchimento_entrevista
    .venv\\Scripts\\python.exe -m scripts.avaliar_preenchimento_entrevista --caso 01_pe_quebrado_demissao

Compara o que `processar_entrevista` extraiu com o ouro em
`tests/fixtures/entrevistas/esperado.json`. Serve para iterar o prompt até
os campos críticos (rastreio + fatos narrados) batem.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FIX = ROOT / "tests" / "fixtures" / "entrevistas"
OUT = ROOT / "tmp" / "avaliacao_entrevista"


def _carregar_env() -> None:
    env = ROOT / ".env"
    if not env.is_file():
        return
    for linha in env.read_text(encoding="utf-8").splitlines():
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        chave = chave.strip()
        if chave and chave not in os.environ:
            os.environ[chave] = valor.strip().strip('"').strip("'")


def _norm(texto: object) -> str:
    s = unicodedata.normalize("NFKD", str(texto or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s.casefold()).strip()


def _valor_bate(obtido: object, esperado: object) -> bool:
    o = _norm(obtido)
    e = _norm(esperado)
    if not e:
        return True
    if o == e:
        return True
    # sim/não toleram "nao." / variações curtas
    if e in {"sim", "nao"} and o.rstrip(".") == e:
        return True
    # escolha / dado: aceita se o esperado está contido (ou o contrário)
    if e in o or o in e:
        return True
    return False


def _contem_algum(obtido: object, pistas: list[str]) -> bool:
    o = _norm(obtido)
    if not o:
        return False
    return any(_norm(p) in o for p in pistas)


def avaliar_caso(nome: str, meta: dict) -> dict:
    from app import escuta

    txt = (FIX / f"{nome}.txt").read_text(encoding="utf-8")
    resultado = escuta.processar_entrevista(txt, meta.get("iniciais") or {})
    respostas = resultado.get("respostas") or {}

    ok: list[str] = []
    falhas: list[str] = []
    # União dos campos avaliados (sem duplicar se está em esperadas e contem).
    campos = sorted(
        set(meta.get("esperadas") or {}) | set(meta.get("contem") or {})
    )

    for campo in campos:
        obtido = respostas.get(campo, "")
        if isinstance(obtido, list):
            obtido = ", ".join(str(x) for x in obtido)
        esperado = (meta.get("esperadas") or {}).get(campo)
        pistas = (meta.get("contem") or {}).get(campo)

        passou = False
        if esperado is not None and _valor_bate(obtido, esperado):
            passou = True
        if pistas and _contem_algum(obtido, pistas):
            passou = True
        # Relato/dado: se há pistas de conteúdo, elas bastam (texto pode variar).
        if pistas and esperado is not None and not passou:
            # Já falhou nos dois critérios acima.
            pass

        if passou:
            ok.append(campo)
        else:
            detalhe = []
            if esperado is not None:
                detalhe.append(f"esperado={esperado!r}")
            if pistas:
                detalhe.append(f"contem={pistas!r}")
            detalhe.append(f"obtido={obtido!r}")
            falhas.append(f"{campo}: " + " ".join(detalhe))

    total = len(ok) + len(falhas)
    taxa = (100 * len(ok) / total) if total else 0.0
    return {
        "caso": nome,
        "ok": ok,
        "falhas": falhas,
        "taxa": round(taxa, 1),
        "respostas": respostas,
        "faltando": resultado.get("faltando") or [],
        "incertas": resultado.get("incertas") or [],
    }


def main() -> int:
    _carregar_env()
    if not os.getenv("DEEPSEEK_API_KEY", "").strip():
        print("Falta DEEPSEEK_API_KEY no ambiente/.env")
        return 2

    parser = argparse.ArgumentParser()
    parser.add_argument("--caso", help="Roda só este caso (stem do txt)")
    parser.add_argument("--prefixo", help="Só casos cujo nome começa com este prefixo")
    parser.add_argument("--workers", type=int, default=3, help="Chamadas paralelas (default 3)")
    parser.add_argument("--meta", type=float, default=90.0, help="Média mínima de sucesso")
    args = parser.parse_args()

    ouro = json.loads((FIX / "esperado.json").read_text(encoding="utf-8"))
    if args.caso:
        casos = [args.caso]
    else:
        casos = sorted(ouro.keys())
        if args.prefixo:
            casos = [c for c in casos if c.startswith(args.prefixo)]

    OUT.mkdir(parents=True, exist_ok=True)
    relatorio: list[dict] = []
    falhas_campo: dict[str, int] = {}

    print(f"Avaliando {len(casos)} caso(s) com {args.workers} worker(s)…\n")

    def _rodar(nome: str) -> dict:
        try:
            r = avaliar_caso(nome, ouro[nome])
            r["erro"] = None
            return r
        except Exception as exc:
            return {"caso": nome, "erro": str(exc), "taxa": 0, "ok": [], "falhas": [], "incertas": []}

    from concurrent.futures import ThreadPoolExecutor, as_completed

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futuros = {pool.submit(_rodar, nome): nome for nome in casos if nome in ouro}
        for fut in as_completed(futuros):
            nome = futuros[fut]
            r = fut.result()
            if r.get("erro"):
                print(f"=== {nome} ===\n  ERRO: {r['erro']}")
                relatorio.append({"caso": nome, "erro": r["erro"], "taxa": 0})
                continue
            print(f"=== {nome} ===  taxa={r['taxa']}%  ok={len(r['ok'])}  falhas={len(r['falhas'])}")
            for f in r["falhas"]:
                print(f"  FALHA  {f}")
                campo = f.split(":", 1)[0].strip()
                falhas_campo[campo] = falhas_campo.get(campo, 0) + 1
            (OUT / f"{nome}.json").write_text(
                json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            relatorio.append({k: r[k] for k in ("caso", "taxa", "ok", "falhas")})

    media = sum(c.get("taxa", 0) for c in relatorio) / max(1, len(relatorio))
    print(f"\nMédia: {media:.1f}%")
    if falhas_campo:
        print("Falhas por campo:")
        for campo, n in sorted(falhas_campo.items(), key=lambda x: (-x[1], x[0])):
            print(f"  {campo}: {n}")
    (OUT / "resumo.json").write_text(
        json.dumps(
            {"media": media, "falhas_campo": falhas_campo, "casos": relatorio},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0 if media >= args.meta else 1


if __name__ == "__main__":
    raise SystemExit(main())
