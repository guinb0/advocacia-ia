#!/usr/bin/env python3
"""Etapa 1 — inspecionar o lote recebido.

Uso:
    python3 inspecionar.py <pasta_entrada> <pasta_trabalho>

Explode PDFs e imagens em páginas individuais, gera miniaturas, mede cada
página e escreve <pasta_trabalho>/inventario.md.

Os originais NUNCA são alterados: tudo é escrito na pasta de trabalho.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import comum  # noqa: E402
from PIL import Image  # noqa: E402

EXT_IMAGEM = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic"}
EXT_PDF = {".pdf"}
LARGURA_MINIATURA = 900


def explodir_pdf(pdf: Path, destino: Path, base: str, dpi: int = comum.DPI_PADRAO) -> list[Path]:
    """Rasteriza o PDF em PNGs com pdftoppm (mais estável que pdf2image aqui)."""
    with tempfile.TemporaryDirectory() as tmp:
        prefixo = Path(tmp) / "p"
        subprocess.run(
            ["pdftoppm", "-r", str(dpi), "-png", str(pdf), str(prefixo)],
            check=True, capture_output=True,
        )
        saidas = []
        for i, png in enumerate(sorted(Path(tmp).glob("p-*.png")), 1):
            alvo = destino / f"{base}_p{i:03d}.png"
            shutil.copy(png, alvo)
            saidas.append(alvo)
    return saidas


def coletar(entrada: Path, paginas_dir: Path, dpi: int = comum.DPI_PADRAO,
            continuar: bool = False) -> list[tuple[Path, str]]:
    """Devolve [(caminho_pagina, origem)] para todo o lote."""
    resultado = []
    arquivos = sorted(p for p in entrada.rglob("*") if p.is_file())
    for arq in arquivos:
        ext = arq.suffix.lower()
        base = comum.normalizar_nome(arq.stem)[:40]
        try:
            if ext in EXT_PDF:
                if continuar:
                    ja = sorted(paginas_dir.glob(f"{base}_p*.png"))
                    if ja:
                        resultado.extend((x, arq.name) for x in ja)
                        continue
                for pag in explodir_pdf(arq, paginas_dir, base, dpi):
                    resultado.append((pag, arq.name))
            elif ext in EXT_IMAGEM:
                img = comum.carregar(arq)
                alvo = paginas_dir / f"{base}_p001.png"
                n = 1
                while alvo.exists():
                    n += 1
                    alvo = paginas_dir / f"{base}_{n}_p001.png"
                img.save(alvo)
                resultado.append((alvo, arq.name))
            else:
                print(f"  ignorado (formato não suportado): {arq.name}")
        except Exception as e:  # arquivo corrompido não derruba o lote
            print(f"  ERRO ao ler {arq.name}: {type(e).__name__}: {e}")
    return resultado


def agrupar_duplicados(dados: list[dict]) -> dict[str, list[str]]:
    """Agrupa páginas idênticas (hash exato) e quase idênticas (dhash <= 3)."""
    grupos: dict[str, list[str]] = {}
    for d in dados:
        grupos.setdefault(d["hash"], []).append(d["pagina"])
    exatos = {h: v for h, v in grupos.items() if len(v) > 1}

    proximos = []
    restantes = [d for d in dados if len(grupos[d["hash"]]) == 1]
    usados = set()
    for i, a in enumerate(restantes):
        if a["pagina"] in usados:
            continue
        par = [a["pagina"]]
        for b in restantes[i + 1:]:
            if b["pagina"] in usados:
                continue
            if comum.distancia_hash(a["dhash"], b["dhash"]) <= 2:
                par.append(b["pagina"])
                usados.add(b["pagina"])
        if len(par) > 1:
            proximos.append(par)
    return {"exatos": list(exatos.values()), "proximos": proximos}


def main() -> int:
    ap = argparse.ArgumentParser(description="Inspeciona o lote de digitalizações.")
    ap.add_argument("entrada", type=Path)
    ap.add_argument("trabalho", type=Path)
    ap.add_argument("--dpi", type=int, default=comum.DPI_PADRAO,
                    help="resolução da rasterização de PDFs (padrão 200)")
    ap.add_argument("--sem-osd", action="store_true",
                    help="não roda a detecção de orientação (bem mais rápido em lotes grandes)")
    ap.add_argument("--continuar", action="store_true",
                    help="não refaz páginas já explodidas na pasta de trabalho")
    args = ap.parse_args()
    comum.USAR_OSD = not args.sem_osd

    if not args.entrada.is_dir():
        print(f"Pasta de entrada não encontrada: {args.entrada}")
        return 1

    paginas_dir = args.trabalho / "paginas"
    minis_dir = args.trabalho / "miniaturas"
    paginas_dir.mkdir(parents=True, exist_ok=True)
    minis_dir.mkdir(parents=True, exist_ok=True)

    print(f"Lendo {args.entrada} ...")
    paginas = coletar(args.entrada, paginas_dir, args.dpi, args.continuar)
    if not paginas:
        print("Nenhuma página legível encontrada.")
        return 1

    dados = []
    for caminho, origem in paginas:
        img = comum.carregar(caminho)
        m = comum.medir(img)
        mini = img.copy()
        mini.thumbnail((LARGURA_MINIATURA, LARGURA_MINIATURA), Image.LANCZOS)
        mini.save(minis_dir / caminho.name)
        m.update({
            "pagina": caminho.name,
            "origem": origem,
            "hash": comum.hash_conteudo(img),
            "dhash": comum.dhash(img),
        })
        dados.append(m)
        print(f"  {caminho.name}: {'; '.join(m['alertas']) or 'sem alertas'}")

    dup = agrupar_duplicados(dados)

    linhas = [
        "# Inventário do lote",
        "",
        f"- Páginas: **{len(dados)}**",
        f"- Arquivos de origem: **{len({d['origem'] for d in dados})}**",
        f"- Miniaturas: `{minis_dir}`",
        "",
        "> Os alertas abaixo são **pistas, não veredito**. Abra as miniaturas e",
        "> confira visualmente antes de decidir giro, corte e tipo de documento.",
        "",
        "| Página | Origem | Tamanho | Inclinação | OSD | Alertas |",
        "|---|---|---|---|---|---|",
    ]
    for d in dados:
        osd = f"{d['giro_osd']}°" if d["giro_osd"] else "—"
        linhas.append(
            f"| `{d['pagina']}` | {d['origem']} | {d['largura']}×{d['altura']} | "
            f"{d['inclinacao']}° | {osd} | {'; '.join(d['alertas']) or '—'} |"
        )

    linhas += ["", "## Duplicidade", ""]
    if dup["exatos"]:
        linhas.append("**Idênticas (mesmo conteúdo):**")
        for grupo in dup["exatos"]:
            linhas.append(f"- {' ↔ '.join(f'`{g}`' for g in grupo)}")
    if dup["proximos"]:
        linhas.append("")
        linhas.append("**Quase idênticas (conferir se é a mesma página):**")
        for grupo in dup["proximos"]:
            linhas.append(f"- {' ↔ '.join(f'`{g}`' for g in grupo)}")
    if not dup["exatos"] and not dup["proximos"]:
        linhas.append("Nenhuma duplicidade detectada.")
    linhas += [
        "",
        "Duplicado **não se descarta**: monta-se como arquivo próprio com o sufixo",
        "`(duplicado)` e pergunta-se ao usuário se deve excluir.",
        "",
        "## Próximo passo",
        "",
        "Abrir as miniaturas, identificar cada página (Etapa 2), rodar a pré-análise",
        "e o checklist (Etapa 3) e escrever o `plano.json` para o `montar.py`.",
        "",
    ]

    inventario = args.trabalho / "inventario.md"
    inventario.write_text("\n".join(linhas), encoding="utf-8")
    print(f"\nInventário: {inventario}")
    print(f"Miniaturas: {minis_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
