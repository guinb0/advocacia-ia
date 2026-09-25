"""Carrega a skill de arquivo `escritorio-trabalhista` (SKILL.md + references/)
para dentro do prompt de geração.

POR QUE ISTO EXISTE

A skill nasceu como um artefato usado direto no Claude, fora deste sistema, e
foi o que produziu a petição que o escritório usa como padrão de qualidade
("RASCUNHO - Peticao Inicial - Paulo Sergio Leandro Burcaos x ECT.pdf"). A
geração automática (`peticao_local.gerar`) nunca leu esses arquivos: só existia
`peticao_skills`, uma tabela com um campo de texto livre por categoria — bem
mais rasa que a skill inteira (regras de redação, estrutura obrigatória, forma
de citação, valor mínimo da causa, subteses por assunto, anti-invenção). Essa é
a causa concreta, dentro do código, de a peça automática sair mais rasa que a
de referência: elas não liam o mesmo material.

Só os arquivos SEMPRE aplicáveis + o arquivo do assunto identificado entram no
prompt — a skill inteira soma ~20 arquivos, e o próprio `SKILL.md` instrui
"identifique qual conjunto de referência usar", não "leia tudo de uma vez".
Diluir a atenção do modelo em referências de assuntos que não são deste caso
teria o efeito contrário ao pretendido.
"""

from __future__ import annotations

import hashlib
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

#: (palavras-chave no nome/código da categoria) -> arquivo de assunto, na mesma
#: correspondência da tabela "Etapa 1.1" do SKILL.md. Ordem importa: a primeira
#: combinação vence, e "assalto" precisa vir antes do "acidente" genérico.
_MAPA_ASSUNTOS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("assalto", "carteiro"), "assalto_carteiro/modelo_peticao.md"),
    (("rescis", "verba"), "verbas_rescisorias.md"),
    (("hora extra", "horas extras", "jornada"), "horas_extras.md"),
    (
        ("ocupacional", "acidente", "doenca", "doença", "ler dort", "ler/dort"),
        "doenca_ocupacional_acidente_trabalho.md",
    ),
    (
        ("equipara", "acumulo de funcao", "acúmulo de função", "desvio de funcao", "desvio de função"),
        "equiparacao_salarial_acumulo_funcao.md",
    ),
    (("assedio", "assédio", "dano moral"), "assedio_moral_dano_moral_trabalhista.md"),
    (("vinculo", "vínculo", "terceiriza", "pejotiz"), "vinculo_terceirizacao.md"),
    (("estabilidade", "gestante", "cipeiro", "sindical"), "estabilidades.md"),
    (("insalubridade", "periculosidade"), "adicional_insalubridade_periculosidade.md"),
    (("justa causa", "discriminat"), "justa_causa_dispensa_discriminatoria.md"),
    (("fgts", "plr", "norma coletiva"), "fgts_diferencas_salariais.md"),
)

#: O SKILL.md é explícito: "nunca recusar o caso por falta de modelo pronto".
_PADRAO = "outros_assuntos.md"


def _normalizar(texto: str) -> str:
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    return sem_acento.lower()


def _arquivo_do_assunto(categoria_nome: str, categoria_codigo: str) -> str:
    alvo = _normalizar(f"{categoria_nome} {categoria_codigo}")
    for palavras, arquivo in _MAPA_ASSUNTOS:
        if any(p in alvo for p in palavras):
            return arquivo
    return _PADRAO


@lru_cache(maxsize=64)
def _ler(caminho_relativo: str) -> str:
    """Cacheado: são arquivos estáticos do repositório, lidos a toda geração."""
    caminho = _DIR / caminho_relativo if caminho_relativo == "SKILL.md" else _REFERENCIAS / caminho_relativo
    try:
        return caminho.read_text(encoding="utf-8")
    except OSError as erro:
        log.warning("peticao_skill_arquivos: não leu %s: %s", caminho, erro)
        return ""


def carregar(categoria_nome: str, categoria_codigo: str) -> str:
    """O material da skill de arquivo para esta categoria, pronto para o prompt.

    Sempre os arquivos gerais + o arquivo do assunto identificado (ou
    `outros_assuntos.md`, que o próprio SKILL.md diz para nunca recusar).
    String vazia se os arquivos não existirem no deploy (skill não copiada) —
    a geração continua com a orientação da tabela `peticao_skills`, como antes.
    """
    arquivo_assunto = _arquivo_do_assunto(categoria_nome, categoria_codigo)
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
    texto_assunto = _ler(arquivo_assunto)
    if texto_assunto:
        partes.append(
            f"\n--- {arquivo_assunto} (assunto identificado: {categoria_nome or categoria_codigo}) ---\n"
            f"{texto_assunto}"
        )
        corpo = True
    return "\n".join(partes) if corpo else ""


#: Só usado se `references/formatacao.md` não puder ser lido (deploy sem a
#: skill copiada) — nunca como padrão concorrente. Gerar DOCX exige algum
#: número em cada campo; sem isto, ausência do arquivo derrubaria a geração
#: inteira por causa de margem.
_EMERGENCIA_SEM_SKILL: dict[str, Any] = {
    "fonte": "Times New Roman",
    "tamanho_fonte_pt": 12.0,
    "espacamento_linha": 1.5,
    "recuo_primeira_linha_cm": 1.25,
    "margem_superior_cm": 3.0,
    "margem_direita_cm": 2.0,
    "margem_inferior_cm": 2.0,
    "margem_esquerda_cm": 3.0,
    "alinhamento_corpo": "justificado",
    "alinhamento_titulos": "esquerda",
    "altura_logo_cm": 2.36,
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
    """Fonte, tamanho, espaçamento, recuo e margens — extraídos de
    `references/formatacao.md`, não fixados em Python.

    O padrão visual do escritório muda quando a skill muda, não quando alguém
    edita `peticao_local.py`. Um número aqui hardcoded ficava desatualizado em
    silêncio: media-se uma vez, numa peça de referência antiga, e a skill podia
    evoluir o padrão (ABNT 3/3/2/2, por exemplo) sem que a geração automática
    acompanhasse — exatamente o "design mudou e o sistema não seguiu" que
    motivou este módulo inteiro.

    Vale só enquanto o escritório não subir um modelo visual próprio
    (`peticao_local.configuracao_visual` prioriza o modelo enviado sobre
    isto, como sempre priorizou — isto é só o piso, não o teto).
    """
    texto = _ler("formatacao.md")
    if not texto:
        log.warning("peticao_skill_arquivos: formatacao.md indisponível — usando emergência sem skill")
        return dict(_EMERGENCIA_SEM_SKILL)

    cfg = dict(_EMERGENCIA_SEM_SKILL)
    margens = re.search(
        r"Margens:\s*superior\s*([\d,.]+)\s*cm,\s*esquerda\s*([\d,.]+)\s*cm,\s*"
        r"inferior\s*([\d,.]+)\s*cm,\s*direita\s*([\d,.]+)\s*cm",
        texto, re.IGNORECASE,
    )
    if margens:
        cfg["margem_superior_cm"] = float(margens.group(1).replace(",", "."))
        cfg["margem_esquerda_cm"] = float(margens.group(2).replace(",", "."))
        cfg["margem_inferior_cm"] = float(margens.group(3).replace(",", "."))
        cfg["margem_direita_cm"] = float(margens.group(4).replace(",", "."))

    fonte = re.search(r"Fonte única em toda a peça:\s*([^.\n]+)", texto, re.IGNORECASE)
    if fonte:
        primeira_opcao = re.split(r"\bou\b", fonte.group(1), flags=re.IGNORECASE)[0].strip()
        if primeira_opcao:
            cfg["fonte"] = primeira_opcao

    tamanho = _numero(r"Corpo do texto:\s*tamanho\s*(\d+)", texto)
    if tamanho is not None:
        cfg["tamanho_fonte_pt"] = tamanho

    espacamento = _numero(r"Espaçamento entre linhas:\s*([\d,.]+)", texto)
    if espacamento is not None:
        cfg["espacamento_linha"] = espacamento

    recuo = _numero(r"Recuo de primeira linha:\s*([\d,.]+)\s*cm", texto)
    if recuo is not None:
        cfg["recuo_primeira_linha_cm"] = recuo

    if re.search(r"Alinhamento\s+justificado", texto, re.IGNORECASE):
        cfg["alinhamento_corpo"] = "justificado"

    return cfg


def resumo(categoria_nome: str, categoria_codigo: str) -> dict[str, Any]:
    """O que `carregar` injeta, em forma auditável: quais arquivos, hash e tamanho.

    O hash muda quando qualquer arquivo da skill muda — é o que permite dizer,
    olhando uma peça já gerada, QUAL versão da skill a orientou.
    """
    assunto = _arquivo_do_assunto(categoria_nome, categoria_codigo)
    arquivos = [n for n in (*_SEMPRE, assunto) if _ler(n)]
    texto = carregar(categoria_nome, categoria_codigo)
    return {
        "skill": "escritorio-trabalhista",
        "arquivos": arquivos,
        "assunto": assunto.split("/")[0].removesuffix(".md"),
        "sha256": hashlib.sha256(texto.encode("utf-8")).hexdigest()[:16] if texto else "",
        "chars": len(texto),
        "carregada": bool(texto),
    }
