"""Carrega a skill de arquivo `escritorio-trabalhista` (SKILL.md + references/)
para dentro do prompt de geração e fornece a ela o layout e o assunto do caso.

POR QUE ISTO EXISTE

A skill nasceu como um artefato usado direto no Claude, fora deste sistema, e
foi o que produziu a petição que o escritório usa como padrão de qualidade
("RASCUNHO - Peticao Inicial - Paulo Sergio Leandro Burcaos x ECT.pdf"). A
geração automática (`peticao_local.gerar`) nunca leu esses arquivos: só existia
`peticao_skills`, uma tabela com um campo de texto livre por categoria.

NADA DE REGRA FIXA AQUI

Nem o layout nem a escolha do assunto moram no código:

- o LAYOUT (fonte, espaçamento, margens, recuo, tamanho de citação) é lido do texto
  da própria skill (`references/formatacao.md`). O que a skill NÃO define não é
  inventado aqui: sai como fallback técnico mínimo, marcado como tal (ver
  `fonte_das_regras`);
- o ASSUNTO vem da tabela "Etapa 1.1" do próprio `SKILL.md` (assunto → arquivo de
  referência): as palavras que distinguem cada linha são lidas dela, e o caso é
  comparado a elas. Trocar a tabela troca a decisão, sem deploy de código.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_DIR = Path(__file__).with_name("skills") / "escritorio-trabalhista"
_REFERENCIAS = _DIR / "references"

#: Lidos em toda geração, independente do assunto — regras de conteúdo,
#: citação e estrutura que valem para qualquer petição trabalhista.
_SEMPRE = (
    "estrutura_peca.md",
    "regras_redacao.md",
    "regras_complementares.md",
    "citacoes_juridicas.md",
)

#: O SKILL.md é explícito: "nunca recusar o caso por falta de modelo pronto".
_PADRAO = "outros_assuntos.md"

#: Palavras gramaticais que não distinguem um assunto do outro.
_SEM_VALOR = frozenset(
    "sobre entre quando sendo mesmo mesma desde ainda depois antes durante contra "
    "pelos pelas essa esse esta este seus suas partir caso casos tipo tipos tipica "
    "tipico avulso geral outro outros outra outras deve pode podem qualquer todos "
    "todas cada onde qual quais cujo cuja sofrido sofrida paga pagas pago pagos "
    "pagamento mais menos como para pela pelo dela dele".split()
)


def _normalizar(texto: str) -> str:
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    return sem_acento.lower()


@lru_cache(maxsize=64)
def _ler(caminho_relativo: str) -> str:
    """Cacheado: são arquivos estáticos do repositório, lidos a toda geração."""
    caminho = _DIR / caminho_relativo if caminho_relativo == "SKILL.md" else _REFERENCIAS / caminho_relativo
    try:
        return caminho.read_text(encoding="utf-8")
    except OSError as erro:
        log.warning("peticao_skill_arquivos: não leu %s: %s", caminho, erro)
        return ""


def _palavras(texto: str) -> set[str]:
    return {p for p in re.findall(r"[a-z]{5,}", _normalizar(texto)) if p not in _SEM_VALOR}


@lru_cache(maxsize=1)
def _tabela_de_assuntos() -> tuple[tuple[str, frozenset[str], frozenset[str]], ...]:
    """(arquivo de referência, palavras que distinguem a linha, exclusões) da tabela do SKILL.md.

    Só entram as palavras que aparecem em UMA linha da tabela — "empregado" ou
    "atividade" estão em várias e não distinguem nada. Exclusão é o "que não
    seja X" da própria descrição (ex.: a linha de doença ocupacional diz "que não
    seja assalto"): se o caso trata de X, essa linha não vale.
    """
    linhas = []
    for linha in _ler("SKILL.md").splitlines():
        if not (linha.startswith("|") and "references/" in linha):
            continue
        colunas = [c.strip() for c in linha.strip().strip("|").split("|")]
        if len(colunas) < 3:
            continue
        ref = re.search(r"references/([\w/\-.]+\.md)", colunas[2])
        if ref:
            descricao = " ".join(colunas[:2])
            linhas.append((ref.group(1), _palavras(descricao), descricao))
    contagem: dict[str, int] = {}
    for _, palavras, _ in linhas:
        for p in palavras:
            contagem[p] = contagem.get(p, 0) + 1
    tabela = []
    for arquivo, palavras, descricao in linhas:
        exclusoes = frozenset(
            _palavras(" ".join(re.findall(r"n[ãa]o seja ([^,;.)]+)", descricao, re.IGNORECASE)))
        )
        tabela.append((arquivo, frozenset(p for p in palavras if contagem[p] == 1), exclusoes))
    return tuple(tabela)


def _arquivo_do_assunto(categoria_nome: str, categoria_codigo: str, texto_caso: str = "") -> str:
    """O arquivo de referência do assunto, decidido pelo caso e pela tabela da skill.

    O SKILL.md manda "a partir dos documentos e do relato recebidos, identifique qual
    conjunto de referência usar": o texto do caso conta, e o nome da categoria conta
    mais (foi escolhido por uma pessoa). Nada casando cai em `outros_assuntos`.
    """
    nome = _normalizar(f"{categoria_nome} {categoria_codigo}")
    corpo = _normalizar(texto_caso)
    melhor, pontos_melhor = _PADRAO, 0
    for arquivo, palavras, exclusoes in _tabela_de_assuntos():
        if any(corpo.count(e) >= 2 for e in exclusoes):
            continue
        pontos = sum(3 for p in palavras if p in nome) + sum(min(corpo.count(p), 3) for p in palavras)
        # Uma palavra solta ("relação") não identifica assunto: exige ao menos duas
        # palavras distintivas da linha da tabela presentes no nome ou no caso.
        if sum(1 for p in palavras if p in nome or p in corpo) < 2:
            continue
        if pontos > pontos_melhor:
            melhor, pontos_melhor = arquivo, pontos
    return melhor


def assunto_slug(categoria_nome: str, categoria_codigo: str, texto_caso: str = "") -> str:
    """O mesmo identificador de `metadados.assunto` das peças do acervo classificado."""
    return _arquivo_do_assunto(categoria_nome, categoria_codigo, texto_caso).split("/")[0].removesuffix(".md")


def _arquivos_do_assunto(arquivo: str) -> list[str]:
    """O arquivo do assunto e, se ele mora numa pasta própria, as regras específicas dela."""
    arquivos = [arquivo]
    if "/" in arquivo:
        pasta = arquivo.rsplit("/", 1)[0]
        for extra in ("regras_redacao_especifica.md", "checklist_especifico.md"):
            if _ler(f"{pasta}/{extra}"):
                arquivos.append(f"{pasta}/{extra}")
    return arquivos


def carregar(categoria_nome: str, categoria_codigo: str, texto_caso: str = "") -> str:
    """O material da skill de arquivo para este caso, pronto para o prompt.

    Sempre os arquivos gerais + o(s) arquivo(s) do assunto identificado (ou
    `outros_assuntos.md`, que o próprio SKILL.md diz para nunca recusar).
    String vazia se os arquivos não existirem no deploy (skill não copiada) —
    a geração continua com a orientação da tabela `peticao_skills`, como antes.
    """
    arquivo_assunto = _arquivo_do_assunto(categoria_nome, categoria_codigo, texto_caso)
    partes = [
        "=== SKILL DO ESCRITÓRIO (regras de execução — prioridade máxima de formato e conteúdo) ===",
        "Esta skill foi a base da petição que o escritório usa como padrão de qualidade. Ela "
        "manda sobre qualquer peça de referência do acervo e sobre qualquer critério geral "
        "deste prompt quando houver conflito de estrutura, profundidade ou regra de conteúdo. "
        "\"MANTER + CORRIGIR + ATUALIZAR + FORTALECER. Nunca RESUMIR + CORTAR + SUBSTITUIR "
        "silenciosamente\" — a petição final deve ser completa, de excelência, usando todas as "
        "teses, fundamentos e precedentes cabíveis ao caso concreto; nunca cortada para "
        "economizar espaço.",
    ]
    corpo = False
    for nome in _SEMPRE:
        texto = _ler(nome)
        if texto:
            partes.append(f"\n--- {nome} ---\n{texto}")
            corpo = True
    for nome in _arquivos_do_assunto(arquivo_assunto):
        texto = _ler(nome)
        if texto:
            partes.append(
                f"\n--- {nome} (assunto identificado: {categoria_nome or categoria_codigo}) ---\n{texto}"
            )
            corpo = True
    return "\n".join(partes) if corpo else ""


def resumo(categoria_nome: str, categoria_codigo: str, texto_caso: str = "") -> dict[str, Any]:
    """O que `carregar` injeta, em forma auditável: quais arquivos, hash e tamanho.

    O hash muda quando qualquer arquivo da skill muda — é o que permite dizer,
    olhando uma peça já gerada, QUAL versão da skill a orientou.
    """
    assunto = _arquivo_do_assunto(categoria_nome, categoria_codigo, texto_caso)
    arquivos = [n for n in (*_SEMPRE, *_arquivos_do_assunto(assunto)) if _ler(n)]
    texto = carregar(categoria_nome, categoria_codigo, texto_caso)
    return {
        "skill": "escritorio-trabalhista",
        "arquivos": arquivos,
        "assunto": assunto.split("/")[0].removesuffix(".md"),
        "sha256": hashlib.sha256(texto.encode("utf-8")).hexdigest()[:16] if texto else "",
        "chars": len(texto),
        "carregada": bool(texto),
    }


#: Só usado se NEM `layout.json` NEM `formatacao.md` puderem ser lidos (deploy sem a
#: skill copiada) — nunca como padrão concorrente. Gerar DOCX exige algum número em
#: cada campo; sem isto, ausência do arquivo derrubaria a geração por causa de margem.
#: É um piso TÉCNICO e GENÉRICO (A4, 1 pol., 11 pt, simples) — não é o padrão de nenhum
#: escritório. Cada campo que a skill define sobrescreve este; os que ela não define
#: ficam listados em `campos_sem_definicao` e aparecem no trace da geração.
_EMERGENCIA_SEM_SKILL: dict[str, Any] = {
    "fonte": "Arial",
    "tamanho_fonte_pt": 11.0,
    "espacamento_linha": 1.0,
    "espacamento_paragrafo_pt": 0.0,
    "linhas_em_branco_entre_paragrafos": False,
    "recuo_primeira_linha_cm": 0.0,
    "margem_superior_cm": 2.54,
    "margem_direita_cm": 2.54,
    "margem_inferior_cm": 2.54,
    "margem_esquerda_cm": 2.54,
    "alinhamento_corpo": "esquerda",
    "alinhamento_titulos": "esquerda",
    "citacao_tamanho_pt": 10.0,
    "rodape_tamanho_pt": 10.0,
    "preferir_tabelas": False,
}


def _numero(padrao_regex: str, texto: str) -> float | None:
    m = re.search(padrao_regex, texto, re.IGNORECASE)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def configuracao_visual_padrao() -> dict[str, Any]:
    """Fonte, espaçamento, margens, recuo e tamanho de citação — lidos do texto da skill.

    Só `references/formatacao.md` decide. O padrão visual do escritório muda quando a
    skill muda, não quando alguém edita `peticao_local.py`. Campo que a skill não
    define cai no piso técnico genérico e é listado em `campos_sem_definicao`.
    """
    cfg = dict(_EMERGENCIA_SEM_SKILL)
    definidos: set[str] = set()
    texto = _ler("formatacao.md")
    if texto:
        margens = re.search(
            r"Margens:\s*superior\s*([\d,.]+)\s*cm,\s*esquerda\s*([\d,.]+)\s*cm,\s*"
            r"inferior\s*([\d,.]+)\s*cm,\s*direita\s*([\d,.]+)\s*cm",
            texto, re.IGNORECASE,
        )
        if margens:
            for chave, grupo in (("margem_superior_cm", 1), ("margem_esquerda_cm", 2),
                                 ("margem_inferior_cm", 3), ("margem_direita_cm", 4)):
                cfg[chave] = float(margens.group(grupo).replace(",", "."))
                definidos.add(chave)
        fonte = re.search(r"Fonte única em toda a peça:\s*([^.\n]+)", texto, re.IGNORECASE)
        if fonte:
            primeira = re.split(r"\bou\b", fonte.group(1), flags=re.IGNORECASE)[0].strip()
            if primeira:
                cfg["fonte"] = primeira
                definidos.add("fonte")
        for chave, regex in (
            ("tamanho_fonte_pt", r"Corpo do texto:\s*tamanho\s*(\d+)"),
            ("citacao_tamanho_pt", r"Cita[çc][õo]es longas e notas de rodap[ée]:\s*tamanho\s*(\d+)"),
            ("espacamento_linha", r"Espaçamento entre linhas:\s*([\d,.]+)"),
            ("recuo_primeira_linha_cm", r"Recuo de primeira linha:\s*([\d,.]+)\s*cm"),
        ):
            valor = _numero(regex, texto)
            if valor is not None:
                cfg[chave] = valor
                definidos.add(chave)
        if re.search(r"Alinhamento\s+justificado", texto, re.IGNORECASE):
            cfg["alinhamento_corpo"] = "justificado"
            definidos.add("alinhamento_corpo")
    cfg["fonte_das_regras"] = "references/formatacao.md" if definidos else "fallback_tecnico_generico"
    cfg["campos_sem_definicao"] = sorted(set(_EMERGENCIA_SEM_SKILL) - definidos)
    return cfg
