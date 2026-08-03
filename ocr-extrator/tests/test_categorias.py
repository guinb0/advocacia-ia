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

from app.categorias import ACIDENTE_TRABALHO_CORREIOS, CATEGORIAS  # noqa: E402
from tests.ler_checklist_docx import ler  # noqa: E402

DOCX = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "CHECK LIST ACIDENTE DO TRABALHO 31.07.26.docx"
)

# Quantidades conferidas na leitura do documento original.
TOTAL_ESPERADO = 33
OBRIGATORIOS_ESPERADOS = 14

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


def main() -> int:
    falhas = 0
    categoria = ACIDENTE_TRABALHO_CORREIOS

    # ---------------------------------------------------- contagens internas
    if len(categoria.itens) != TOTAL_ESPERADO:
        print(f"FALHA: categoria tem {len(categoria.itens)} itens, esperava {TOTAL_ESPERADO}")
        falhas += 1
    if len(categoria.obrigatorios) != OBRIGATORIOS_ESPERADOS:
        print(
            f"FALHA: {len(categoria.obrigatorios)} obrigatórios, "
            f"esperava {OBRIGATORIOS_ESPERADOS}"
        )
        falhas += 1

    numeros = [i.numero for i in categoria.itens]
    if numeros != list(range(1, TOTAL_ESPERADO + 1)):
        print(f"FALHA: numeração fora de sequência: {numeros}")
        falhas += 1

    for item in categoria.itens:
        if item.codigo != f"DOC.{item.numero:02d}":
            print(f"FALHA: código {item.codigo!r} não bate com o número {item.numero}")
            falhas += 1

    for codigo, cat in CATEGORIAS.items():
        if codigo != cat.codigo:
            print(f"FALHA: chave {codigo!r} difere de Categoria.codigo {cat.codigo!r}")
            falhas += 1

    # ------------------------------------------------- comparação com o .docx
    if not DOCX.is_file():
        print(f"AVISO: {DOCX.name} não encontrado — pulei a comparação com o original.")
        print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
        return 1 if falhas else 0

    do_docx: dict[int, tuple[str, bool]] = {}
    for linha in ler(str(DOCX)):
        m = RE_ITEM.match(linha["texto"].strip())
        if m:
            do_docx[int(m.group(1))] = (m.group(2).strip(), linha["obrigatorio"])

    if len(do_docx) != TOTAL_ESPERADO:
        print(f"FALHA: o .docx tem {len(do_docx)} itens, esperava {TOTAL_ESPERADO}")
        falhas += 1

    for item in categoria.itens:
        if item.numero not in do_docx:
            print(f"FALHA: DOC.{item.numero:02d} não existe no .docx")
            falhas += 1
            continue

        nome_docx, obrigatorio_docx = do_docx[item.numero]

        if item.obrigatorio != obrigatorio_docx:
            print(
                f"FALHA: DOC.{item.numero:02d} ({item.nome}) está como "
                f"{'obrigatório' if item.obrigatorio else 'opcional'}, mas no .docx é "
                f"{'obrigatório (vermelho)' if obrigatorio_docx else 'opcional (preto)'}"
            )
            falhas += 1

        # O nome foi reescrito em caixa normal e às vezes expandido ("CAT" ->
        # "CAT (Comunicação de Acidente de Trabalho)"), então aceitamos que o do
        # código contenha o do .docx — nunca que perca palavra do original.
        do_codigo, do_arquivo = _chave(item.nome), _chave(nome_docx)
        if not do_arquivo.issubset(do_codigo):
            print(f"FALHA: DOC.{item.numero:02d} nome divergente:")
            print(f"         código: {item.nome!r}")
            print(f"         .docx : {nome_docx!r}")
            print(f"         faltou no código: {sorted(do_arquivo - do_codigo)}")
            falhas += 1

    print(f"\n{TOTAL_ESPERADO} documentos, {OBRIGATORIOS_ESPERADOS} obrigatórios, "
          f"conferidos contra {DOCX.name}")
    print(f"{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
