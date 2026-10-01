#!/usr/bin/env python3
"""Etapa 5 — montar um PDF por documento a partir do plano.

Uso:
    python3 montar.py plano.json [--relatorio] [--saida <pasta>]

Formato do plano:

{
  "cliente": "Maria Aparecida da Silva",
  "saida": "/mnt/user-data/outputs/Documentos_Maria_Aparecida_da_Silva",
  "padroes": {"corte": "auto", "endireitar": true, "realce": "suave", "pagina": "A4"},
  "documentos": [
    {"nome": "RG", "pessoal": true, "item": 3, "paginas": [
        {"arquivo": "trabalho/paginas/scan_001.png"},
        {"arquivo": "trabalho/paginas/scan_002.png", "girar": 180}
    ]},
    {"nome": "RG (duplicado)", "pessoal": true, "item": 3,
     "paginas": [{"arquivo": "trabalho/paginas/scan_007.png"}]},
    {"nome": "Atestado Medico 2024-03-11", "data": "2024-03-11", "item": 13,
     "paginas": [{"arquivo": "trabalho/paginas/scan_011.png"}]}
  ]
}

Ordem e numeracao: "pessoal": true marca os documentos pessoais / de
qualificacao, que vao primeiro, na ordem em que aparecem no plano. Os demais
sao ordenados por "data" (AAAA-MM-DD), do mais antigo para o mais recente; os
sem data vao para o fim. Depois de ordenados, cada documento recebe o prefixo
sequencial doc1_, doc2_, ... no nome do arquivo. O duplicado nao consome
numero: herda o do principal e fica logo depois dele.

"item" e o numero do item no checklist do tipo de acao — usado so no relatorio,
nunca no nome do arquivo.

Regra de ouro: 1 documento = 1 PDF. O script não junta documentos diferentes
nem divide o mesmo documento — isso é responsabilidade do plano.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import comum  # noqa: E402

PADROES = {"corte": "auto", "endireitar": True, "realce": "suave", "pagina": "A4", "girar": 0}


def nome_arquivo(doc: dict) -> str:
    """Nome final do arquivo, no formato 'Doc N. Nome Do Documento.pdf'.

    'seq' e atribuido por ordenar_e_numerar(); duplicados herdam o numero do
    documento principal. Cada palavra do nome vai com a primeira letra
    maiuscula e o restante minusculo (Title Case), inclusive o prefixo
    "Doc" — a extensao .pdf fica em minusculo.
    """
    base = comum.normalizar_nome(doc["nome"])
    seq = doc.get("seq")
    if seq in (None, "", 0):
        return base
    return f"Doc {int(seq)}. {base}"


def eh_duplicado(d: dict) -> bool:
    return "(duplicado" in d["nome"].lower()


def nome_base(d: dict) -> str:
    return d["nome"].split("(duplicado")[0].strip()


def ordenar_e_numerar(documentos: list[dict]) -> list[dict]:
    """Ordena a pasta e atribui o numero sequencial de cada documento.

    Ordem: (1) documentos pessoais / de qualificacao, na ordem do plano;
    (2) os demais em ordem cronologica pela chave 'data'; (3) os sem data,
    no fim. Duplicados nao consomem numero e ficam logo apos o principal.
    """
    for i, d in enumerate(documentos):
        d["_i"] = i

    principais = [d for d in documentos if not eh_duplicado(d)]

    def chave(d: dict):
        pessoal = 0 if d.get("pessoal") else 1
        data = str(d.get("data") or "")
        sem_data = 0 if (pessoal == 0 or data) else 1
        return (pessoal, sem_data, "" if pessoal == 0 else data, d["_i"])

    principais.sort(key=chave)

    ordenados: list[dict] = []
    vistos: set[int] = set()
    for n, d in enumerate(principais, 1):
        d["seq"] = n
        ordenados.append(d)
        vistos.add(id(d))
        for dup in documentos:
            if eh_duplicado(dup) and nome_base(dup) == d["nome"].strip() and id(dup) not in vistos:
                dup["seq"] = n
                ordenados.append(dup)
                vistos.add(id(dup))

    for d in documentos:  # duplicado orfao, sem principal correspondente
        if id(d) not in vistos:
            ordenados.append(d)

    for d in ordenados:
        d.pop("_i", None)
    return ordenados


def montar_documento(doc: dict, padroes: dict, saida: Path) -> dict:
    nome = doc["nome"]
    arquivo = saida / f"{nome_arquivo(doc)}.pdf"
    tratadas = []
    problemas = []

    for i, pag in enumerate(doc.get("paginas", []), 1):
        origem = Path(pag["arquivo"])
        if not origem.exists():
            problemas.append(f"página {i}: arquivo não encontrado ({origem})")
            continue
        opcoes = dict(padroes)
        opcoes.update({k: v for k, v in pag.items() if k != "arquivo"})
        try:
            img = comum.carregar(origem)
            antes = comum.medir(img)
            tratada = comum.tratar(img, opcoes)
            depois = comum.medir(tratada)
            if antes["branco"]:
                problemas.append(f"página {i}: parece estar em branco")
            if depois["nitidez"] < comum.LIMIAR_NITIDEZ:
                problemas.append(f"página {i}: legibilidade duvidosa (possível borrão)")
            tratadas.append(tratada)
        except Exception as e:
            problemas.append(f"página {i}: falha no tratamento ({type(e).__name__}: {e})")

    if not tratadas:
        return {"nome": nome, "arquivo": None, "paginas": 0, "problemas": problemas or ["sem páginas"]}

    tratadas[0].save(
        arquivo, "PDF", resolution=comum.DPI_PADRAO,
        save_all=True, append_images=tratadas[1:],
    )
    return {"nome": nome, "arquivo": arquivo, "paginas": len(tratadas),
            "problemas": problemas, "item": doc.get("item", doc.get("doc"))}


def main() -> int:
    ap = argparse.ArgumentParser(description="Monta um PDF por documento.")
    ap.add_argument("plano", type=Path)
    ap.add_argument("--saida", type=Path, default=None, help="sobrepõe 'saida' do plano")
    ap.add_argument("--relatorio", action="store_true")
    args = ap.parse_args()

    plano = json.loads(args.plano.read_text(encoding="utf-8"))
    padroes = dict(PADROES)
    padroes.update(plano.get("padroes", {}))

    saida = args.saida or Path(plano.get("saida", "/mnt/user-data/outputs/Documentos"))
    saida.mkdir(parents=True, exist_ok=True)

    # a pasta sai na ordem de juntada: documentos pessoais primeiro, depois os
    # demais em ordem cronológica; a numeração docN_ segue essa ordem
    documentos = ordenar_e_numerar(plano.get("documentos", []))
    nomes = [nome_arquivo(d) for d in documentos]
    repetidos = {n for n in nomes if nomes.count(n) > 1}
    if repetidos:
        print(f"ERRO: nomes de arquivo repetidos no plano: {', '.join(sorted(repetidos))}")
        print("Use o sufixo '(duplicado)' para a cópia repetida.")
        return 1

    resultados = [montar_documento(d, padroes, saida) for d in documentos]

    for r in resultados:
        marca = "OK " if r["arquivo"] and not r["problemas"] else "!! "
        alvo = r["arquivo"].name if r["arquivo"] else "NÃO GERADO"
        print(f"{marca}{alvo} — {r['paginas']} página(s)")
        for p in r["problemas"]:
            print(f"     - {p}")

    if args.relatorio:
        cliente = plano.get("cliente", "")
        linhas = [f"# Documentos organizados — {cliente}".rstrip(" —"), "", "## Arquivos gerados", ""]
        for r in resultados:
            if r["arquivo"]:
                item = f" — item {int(r['item']):02d} do checklist" if r.get("item") else " — fora do checklist"
                linhas.append(f"- `{r['arquivo'].name}` — {r['paginas']} página(s){item}")
        pend = [(r["nome"], p) for r in resultados for p in r["problemas"]]
        linhas += ["", "## Pendências", ""]
        linhas += [f"- **{n}** — {p}" for n, p in pend] or ["Nenhuma."]
        dups = [r for r in resultados if "(duplicado)" in r["nome"]]
        if dups:
            linhas += ["", "## Duplicados", ""]
            linhas += [f"- `{r['arquivo'].name}` — confirmar se deve ser excluído" for r in dups if r["arquivo"]]
        linhas += [
            "", "## Conferência pendente (fazer à vista)", "",
            "- [ ] orientação de todas as páginas",
            "- [ ] corte rente ao documento, sem mesa/fundo e sem conteúdo amputado",
            "- [ ] numeração docN_ na ordem: pessoais, depois cronológica",
            "- [ ] legibilidade página a página",
            "- [ ] ordem das páginas de cada documento",
            "- [ ] nenhum PDF com documentos misturados",
            "- [ ] checklist do tipo de ação rodado, com todos os obrigatórios reportados",
            "",
        ]
        rel = saida / "RELATORIO.md"
        rel.write_text("\n".join(linhas), encoding="utf-8")
        print(f"\nRelatório: {rel}")

    print(f"Pasta: {saida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
