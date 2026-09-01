"""Confere que `app/categorias.py` bate com o .docx original do escritório.

Se alguém editar a lista à mão e errar um item, ou se o escritório mandar um
checklist novo sem que o código seja atualizado, este teste acusa.

    .venv\\Scripts\\python.exe -m tests.test_categorias
"""

import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.categorias import (  # noqa: E402
    ACIDENTE_TRABALHO_CORREIOS,
    ASSALTO_CARTEIRO,
    AUXILIO_ACIDENTE,
    CATEGORIAS,
    DOENCA_OCUPACIONAL,
    Categoria,
    listar,
    obter,
)
from tests.ler_checklist_docx import ler  # noqa: E402

DIR_DOCS = Path(__file__).resolve().parent.parent / "docs"


def test_only_categories_with_real_cases_are_offered_for_new_cases() -> None:
    assert [categoria.codigo for categoria in listar()] == [
        "acidente_trabalho_correios",
        "acidente_trabalho_geral",
        "doenca_ocupacional",
        "auxilio_acidente",
    ]
    # Compatibilidade: um caso histórico de assalto ainda pode ser aberto.
    assert obter("assalto_carteiro") is not None
CHECKLISTS = (
    (
        ACIDENTE_TRABALHO_CORREIOS,
        DIR_DOCS / "CHECK LIST ACIDENTE DO TRABALHO 31.07.26.docx",
        tuple(range(1, 34)),
        14,
        {3: "rg", 4: "cpf", 5: "comprovante_residencia", 6: "ctps"},
    ),
    (
        DOENCA_OCUPACIONAL,
        DIR_DOCS / "CHECK LIST DOENÇA OCUPACIONAL.docx",
        tuple(range(1, 38)),
        23,
        {3: "rg", 4: "cpf", 5: "comprovante_residencia", 6: "ctps"},
    ),
    (
        ASSALTO_CARTEIRO,
        DIR_DOCS / "CHECK LIST ASSALTO.docx",
        (*range(1, 17), 18, 19, 20),
        11,
        {3: "rg", 4: "cpf", 5: "comprovante_residencia", 7: "ctps"},
    ),
)

RE_ITEM = re.compile(r"^DOC\.?\s*(\d{1,2})\s*:?\s*(.+?)\.?$", re.IGNORECASE)


# Conectivos: "contracheque último mês" e "contracheque DO último mês" são o
# mesmo documento. Ignorá-los evita falso positivo sem esconder erro de conteúdo.
_CONECTIVOS = {"DE", "DO", "DA", "DOS", "DAS", "E", "COM", "EM", "NO", "NA", "O", "A"}


def _chave(texto: str) -> frozenset[str]:
    """Conjunto de palavras significativas, sem acento, hífen nem pontuação."""
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )
    # Hífen some em vez de virar espaço: "CONTRA-CHEQUE" == "CONTRACHEQUE".
    sem_hifen = sem_acento.upper().replace("-", "")
    palavras = re.sub(r"[^A-Z0-9]+", " ", sem_hifen).split()
    return frozenset(p for p in palavras if p not in _CONECTIVOS)


def _conferir(
    categoria: Categoria,
    caminho_docx: Path,
    numeros_esperados: tuple[int, ...],
    obrigatorios_esperados: int,
    tipos_ocr_esperados: dict[int, str],
) -> int:
    falhas = 0
    total_esperado = len(numeros_esperados)

    # ---------------------------------------------------- contagens internas
    if len(categoria.itens) != total_esperado:
        print(
            f"FALHA [{categoria.nome}]: categoria tem {len(categoria.itens)} itens, "
            f"esperava {total_esperado}"
        )
        falhas += 1
    if len(categoria.obrigatorios) != obrigatorios_esperados:
        print(
            f"FALHA [{categoria.nome}]: {len(categoria.obrigatorios)} obrigatórios, "
            f"esperava {obrigatorios_esperados}"
        )
        falhas += 1

    numeros = [i.numero for i in categoria.itens]
    if numeros != list(numeros_esperados):
        print(
            f"FALHA [{categoria.nome}]: numeração {numeros}, "
            f"esperava {list(numeros_esperados)}"
        )
        falhas += 1

    for item in categoria.itens:
        if item.codigo != f"DOC.{item.numero:02d}":
            print(
                f"FALHA [{categoria.nome}]: código {item.codigo!r} "
                f"não bate com o número {item.numero}"
            )
            falhas += 1

    tipos_ocr = {item.numero: item.tipo_ocr for item in categoria.itens if item.tipo_ocr}
    if tipos_ocr != tipos_ocr_esperados:
        print(
            f"FALHA [{categoria.nome}]: classificadores OCR {tipos_ocr}, "
            f"esperava {tipos_ocr_esperados}"
        )
        falhas += 1

    # ------------------------------------------------- comparação com o .docx
    if not caminho_docx.is_file():
        print(
            f"AVISO: {caminho_docx.name} não encontrado — "
            "pulei a comparação com o original."
        )
        return falhas

    do_docx: dict[int, tuple[str, bool]] = {}
    for linha in ler(str(caminho_docx)):
        m = RE_ITEM.match(linha["texto"].strip())
        if m:
            do_docx[int(m.group(1))] = (m.group(2).strip(), linha["obrigatorio"])

    if len(do_docx) != total_esperado:
        print(
            f"FALHA [{categoria.nome}]: o .docx tem {len(do_docx)} itens, "
            f"esperava {total_esperado}"
        )
        falhas += 1

    for item in categoria.itens:
        if item.numero not in do_docx:
            print(
                f"FALHA [{categoria.nome}]: DOC.{item.numero:02d} não existe no .docx"
            )
            falhas += 1
            continue

        nome_docx, obrigatorio_docx = do_docx[item.numero]

        if item.obrigatorio != obrigatorio_docx:
            print(
                f"FALHA [{categoria.nome}]: DOC.{item.numero:02d} ({item.nome}) está como "
                f"{'obrigatório' if item.obrigatorio else 'opcional'}, mas no .docx é "
                f"{'obrigatório (vermelho)' if obrigatorio_docx else 'opcional (preto)'}"
            )
            falhas += 1

        # O nome foi reescrito em caixa normal e às vezes expandido ("CAT" ->
        # "CAT (Comunicação de Acidente de Trabalho)"), então aceitamos que o do
        # código contenha o do .docx — nunca que perca palavra do original.
        do_codigo, do_arquivo = _chave(item.nome), _chave(nome_docx)
        if not do_arquivo.issubset(do_codigo):
            print(f"FALHA [{categoria.nome}]: DOC.{item.numero:02d} nome divergente:")
            print(f"         código: {item.nome!r}")
            print(f"         .docx : {nome_docx!r}")
            print(f"         faltou no código: {sorted(do_arquivo - do_codigo)}")
            falhas += 1

    print(
        f"{categoria.nome}: {total_esperado} documentos, "
        f"{obrigatorios_esperados} obrigatórios, conferidos contra {caminho_docx.name}"
    )
    return falhas


def main() -> int:
    falhas = 0

    for codigo, categoria in CATEGORIAS.items():
        if codigo != categoria.codigo:
            print(f"FALHA: chave {codigo!r} difere de Categoria.codigo {categoria.codigo!r}")
            falhas += 1

    # Auxílio-Acidente veio de um checklist textual, sem arquivo .docx.
    numeros_auxilio = [item.numero for item in AUXILIO_ACIDENTE.itens]
    if numeros_auxilio != list(range(1, 12)):
        print(f"FALHA [Auxílio-Acidente]: numeração incorreta: {numeros_auxilio}")
        falhas += 1

    obrigatorios_auxilio = [item.numero for item in AUXILIO_ACIDENTE.obrigatorios]
    if obrigatorios_auxilio != [1, 2, 4, 5, 10]:
        print(
            "FALHA [Auxílio-Acidente]: obrigatórios incorretos: "
            f"{obrigatorios_auxilio}"
        )
        falhas += 1

    tipos_ocr_auxilio = {
        item.numero: item.tipo_ocr for item in AUXILIO_ACIDENTE.itens if item.tipo_ocr
    }
    if tipos_ocr_auxilio != {2: "comprovante_residencia"}:
        print(
            "FALHA [Auxílio-Acidente]: classificadores OCR incorretos: "
            f"{tipos_ocr_auxilio}"
        )
        falhas += 1

    sem_orientacao = [item.codigo for item in AUXILIO_ACIDENTE.itens if not item.observacao]
    if sem_orientacao:
        print(
            "FALHA [Auxílio-Acidente]: itens sem orientação detalhada: "
            f"{sem_orientacao}"
        )
        falhas += 1

    for checklist in CHECKLISTS:
        falhas += _conferir(*checklist)

    print()
    print(f"{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
