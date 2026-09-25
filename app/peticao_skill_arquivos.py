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
    "formatacao.md",
    "regras_de_geracao.md",
    "estrutura_peca.md",
    "regras_redacao.md",
    "regras_complementares.md",
    "citacoes_juridicas.md",
    "precedentes_vinculantes.md",
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
            # "que não seja assalto" NEGA a palavra: ela não identifica esta linha.
            afirmativa = re.sub(r"n[ãa]o seja [^,;.)]+", " ", descricao, flags=re.IGNORECASE)
            linhas.append((ref.group(1), _palavras(afirmativa), descricao))
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
    ranking = _ranking_de_assuntos(categoria_nome, categoria_codigo, texto_caso)
    return ranking[0][0] if ranking else _PADRAO


def _ranking_de_assuntos(categoria_nome: str, categoria_codigo: str, texto_caso: str) -> list[tuple[str, int]]:
    """(arquivo, pontos) das linhas da tabela que o caso alcança, da melhor para a pior."""
    nome = _normalizar(f"{categoria_nome} {categoria_codigo}")
    corpo = _normalizar(texto_caso)
    pontuados: list[tuple[str, int]] = []
    for arquivo, palavras, exclusoes in _tabela_de_assuntos():
        if any(corpo.count(e) >= 2 for e in exclusoes):
            continue
        pontos = sum(3 for p in palavras if p in nome) + sum(min(corpo.count(p), 3) for p in palavras)
        # Uma palavra solta ("relação") não identifica assunto: exige ao menos duas
        # palavras distintivas da linha da tabela presentes no nome ou no caso.
        # A escolha da categoria por uma pessoa (o nome) basta com UMA palavra distintiva.
        if sum(1 for p in palavras if p in nome or p in corpo) < 2 and not any(p in nome for p in palavras):
            continue
        pontuados.append((arquivo, pontos))
    return sorted(pontuados, key=lambda x: x[1], reverse=True)


def assuntos_relacionados(
    categoria_nome: str, categoria_codigo: str, texto_caso: str = "", *, maximo: int = 2
) -> list[str]:
    """Os assuntos da tabela que o caso alcança (o principal primeiro), como slugs do acervo.

    O acervo de petições é classificado por assunto GERAL ("doenca_ocupacional_acidente_
    trabalho"); o modelo específico do caso ("assalto_carteiro") é um subtipo dele. Buscar
    só pelo slug do modelo nunca casava com nenhuma peça classificada e o desempate por
    assunto ficava inerte. Vale o principal e os vizinhos com pelo menos metade dos pontos.
    """
    ranking = _ranking_de_assuntos(categoria_nome, categoria_codigo, texto_caso)
    if not ranking:
        return [_PADRAO.removesuffix(".md")]
    topo = ranking[0][1]
    slugs: list[str] = []
    for arquivo, pontos in ranking[:maximo]:
        if pontos * 3 >= topo:
            slug = arquivo.split("/")[0].removesuffix(".md")
            if slug not in slugs:
                slugs.append(slug)
    return slugs


def assunto_slug(categoria_nome: str, categoria_codigo: str, texto_caso: str = "") -> str:
    """O mesmo identificador de `metadados.assunto` das peças do acervo classificado."""
    return _arquivo_do_assunto(categoria_nome, categoria_codigo, texto_caso).split("/")[0].removesuffix(".md")


def _arquivos_do_assunto(arquivo: str) -> list[str]:
    """O arquivo do assunto e, se ele mora numa pasta própria, as regras específicas dela."""
    arquivos = [arquivo]
    if "/" in arquivo:
        pasta = arquivo.rsplit("/", 1)[0]
        for extra in ("regras_redacao_especifica.md", "checklist_especifico.md", "precedentes.md"):
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
        "validacoes": [r.get("id") for r in validacoes_da_skill()["regras"]],
    }


def estrutura_da_skill() -> list[dict[str, str]]:
    """Contrato de blocos extraído de ``estrutura_peca.md``.

    O arquivo da skill continua sendo a autoridade: este leitor só transforma a
    lista numerada em dados auditáveis para o gerador e os validadores.  Não
    contém títulos de clientes, teses ou documentos de nenhum caso.
    """
    itens: list[dict[str, str]] = []
    for ordem, bruto in re.findall(r"(?m)^\s*(\d+)\.\s+\*\*(.+?)\*\*", _ler("estrutura_peca.md")):
        titulo = re.sub(r"\s+", " ", bruto).strip()
        itens.append({"ordem": ordem, "titulo": titulo, "normalizado": _normalizar(titulo)})
    return itens


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
    "preferir_tabelas": False,
}


_BLOCO_ESTILO = re.compile(r"```estilo\s*\n(.*?)```", re.DOTALL)
_PROPRIEDADES_NUMERICAS = frozenset({
    "tamanho_pt", "tamanho_numero_pt", "espacamento_linha", "antes_pt", "depois_pt",
    "recuo_esquerdo_cm", "recuo_direito_cm", "recuo_primeira_linha_cm",
    "margem_superior_cm", "margem_inferior_cm", "margem_esquerda_cm", "margem_direita_cm",
    "logo_altura_cm",
})
_PROPRIEDADES_BOOLEANAS = frozenset({"negrito", "italico", "caixa_alta", "manter_com_proxima"})


def _valor_do_estilo(propriedade: str, bruto: str) -> Any:
    bruto = bruto.strip()
    if propriedade in _PROPRIEDADES_NUMERICAS:
        try:
            return float(bruto.replace(",", "."))
        except ValueError:
            return None
    if propriedade in _PROPRIEDADES_BOOLEANAS:
        return _normalizar(bruto) in ("sim", "true", "1", "verdadeiro")
    return bruto


def estilos_da_skill() -> dict[str, dict[str, Any]]:
    """O bloco ```estilo``` de `formatacao.md`: `{elemento: {propriedade: valor}}`.

    O motor não conhece nomes de elemento — quem os cria é a skill (`corpo`, `titulo1`,
    `objeto`, `fechamento`, ...). Linha com valor inválido é ignorada, não corrigida.
    """
    casado = _BLOCO_ESTILO.search(_ler("formatacao.md"))
    estilos: dict[str, dict[str, Any]] = {}
    if not casado:
        return estilos
    for linha in casado.group(1).splitlines():
        if ":" not in linha or linha.strip().startswith("#"):
            continue
        chave, _, bruto = linha.partition(":")
        elemento, _, propriedade = chave.strip().partition(".")
        if not elemento or not propriedade:
            continue
        valor = _valor_do_estilo(propriedade.strip(), bruto)
        if valor is not None:
            estilos.setdefault(elemento.strip(), {})[propriedade.strip()] = valor
    return estilos


_BLOCO_VALIDACAO = re.compile(r"```validacao\s*\n(.*?)```", re.DOTALL)


def validacoes_da_skill() -> dict[str, Any]:
    """`references/validacoes.md`: as regras de conferência que a SKILL declara.

    `{"parametros": {...}, "regras": [...]}`. O motor de conferência só executa; sem este
    arquivo (ou com JSON inválido) não há validação de domínio — e isso é registrado, não
    substituído por regra embutida.
    """
    vazio: dict[str, Any] = {"parametros": {}, "regras": []}
    casado = _BLOCO_VALIDACAO.search(_ler("validacoes.md"))
    if not casado:
        return vazio
    try:
        dados = json.loads(casado.group(1))
    except json.JSONDecodeError as erro:
        log.error("peticao_skill_arquivos: validacoes.md com JSON inválido: %s", erro)
        return vazio
    return {"parametros": dados.get("parametros") or {}, "regras": dados.get("regras") or []}


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
    estilos = estilos_da_skill()
    pagina, corpo = estilos.get("pagina", {}), estilos.get("corpo", {})
    for destino, origem in (
        ("fonte", pagina.get("fonte")),
        ("margem_superior_cm", pagina.get("margem_superior_cm")),
        ("margem_direita_cm", pagina.get("margem_direita_cm")),
        ("margem_inferior_cm", pagina.get("margem_inferior_cm")),
        ("margem_esquerda_cm", pagina.get("margem_esquerda_cm")),
        ("tamanho_fonte_pt", corpo.get("tamanho_pt")),
        ("espacamento_linha", corpo.get("espacamento_linha")),
        ("espacamento_paragrafo_pt", corpo.get("depois_pt")),
        ("recuo_primeira_linha_cm", corpo.get("recuo_primeira_linha_cm")),
        ("alinhamento_corpo", corpo.get("alinhamento")),
        ("altura_logo_cm", estilos.get("cabecalho", {}).get("logo_altura_cm")),
    ):
        if origem is not None:
            cfg[destino] = origem
            definidos.add(destino)
    cfg["estilos"] = estilos
    cfg["fonte_das_regras"] = "references/formatacao.md" if definidos else "fallback_tecnico_generico"
    cfg["campos_sem_definicao"] = sorted(set(_EMERGENCIA_SEM_SKILL) - definidos)
    return cfg
