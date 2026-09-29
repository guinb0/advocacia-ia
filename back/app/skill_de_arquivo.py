"""Carregador genérico de skills em arquivo (`ia/skills/<nome>/`; `app/skills/` na imagem).

Uma skill de arquivo é a pasta `SKILL.md` + `references/*.md` + (opcional) `scripts/*.py`.
Este módulo só sabe LER: achar arquivos, extrair seções do `SKILL.md` por título, calcular o
hash do conjunto (versão auditável) e apontar onde estão os scripts. O que a skill ENSINA —
regras, estrutura, nomenclatura — nunca é copiado para o código: é lido em tempo de execução.

Não substitui `peticao_skill_arquivos` (que também decide assunto e layout de PEÇA); convive
com ele. A skill documental (`analise-e-organizacao-documental`) usa este carregador.
"""

from __future__ import annotations

import hashlib
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from .caminhos import SKILLS

log = logging.getLogger("skill_de_arquivo")

RAIZ_DAS_SKILLS = SKILLS

#: A skill que ensina a ler e organizar documentos. Toda leitura de documento do sistema
#: (por arquivo, do caso inteiro, triagem do protocolo) usa os critérios dela.
SKILL_DOCUMENTAL = "analise-e-organizacao-documental"


class SkillAusente(RuntimeError):
    """A pasta da skill não existe neste deploy."""


class SkillDeArquivo:
    def __init__(self, nome: str, raiz: Path | None = None) -> None:
        self.nome = nome
        self.dir = (raiz or RAIZ_DAS_SKILLS) / nome
        if not (self.dir / "SKILL.md").is_file():
            raise SkillAusente(f"Skill '{nome}' não encontrada em {self.dir}")

    # ---- leitura
    def ler(self, relativo: str) -> str:
        caminho = self.dir / relativo
        try:
            return caminho.read_text(encoding="utf-8")
        except OSError:
            return ""

    def arquivos(self) -> list[str]:
        """Todos os arquivos da skill (relativos, ordenados) — a base do hash."""
        return sorted(
            str(p.relative_to(self.dir)).replace("\\", "/")
            for p in self.dir.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
        )

    def sha256(self) -> str:
        """Hash de TODO o conteúdo da skill: muda quando qualquer arquivo muda."""
        h = hashlib.sha256()
        for rel in self.arquivos():
            h.update(rel.encode("utf-8"))
            h.update((self.dir / rel).read_bytes().replace(b"\r\n", b"\n"))
        return h.hexdigest()

    def frontmatter(self) -> dict[str, str]:
        texto = self.ler("SKILL.md")
        m = re.match(r"---\s*\n(.*?)\n---", texto, re.DOTALL)
        dados: dict[str, str] = {}
        if m:
            for linha in m.group(1).splitlines():
                if ":" in linha:
                    k, _, v = linha.partition(":")
                    dados[k.strip()] = v.strip().strip("'\"")
        return dados

    # ---- seções do SKILL.md
    def secao(self, padrao_do_titulo: str, arquivo: str = "SKILL.md") -> str:
        """Texto de uma seção (do título até o próximo título de nível igual ou menor).

        `padrao_do_titulo` é regex sobre o texto do título (sem os `#`).
        """
        texto = self.ler(arquivo)
        titulos = [(m.start(), len(m.group(1)), m.group(2)) for m in re.finditer(r"^(#{1,6})\s+(.*)$", texto, re.MULTILINE)]
        for i, (inicio, nivel, titulo) in enumerate(titulos):
            if re.search(padrao_do_titulo, titulo, re.IGNORECASE):
                fim = len(texto)
                for proximo_inicio, proximo_nivel, _ in titulos[i + 1 :]:
                    if proximo_nivel <= nivel:
                        fim = proximo_inicio
                        break
                return texto[inicio:fim].strip()
        return ""

    def scripts(self) -> Path:
        return self.dir / "scripts"

    def resumo(self) -> dict[str, Any]:
        return {
            "skill_name": self.nome,
            "skill_sha256": self.sha256(),
            "arquivos": self.arquivos(),
            "descricao": self.frontmatter().get("description", "")[:200],
        }


def listar() -> list[dict[str, Any]]:
    """Skills instaladas em `RAIZ_DAS_SKILLS`, uma pasta com `SKILL.md` cada."""
    if not RAIZ_DAS_SKILLS.is_dir():
        return []
    saida = []
    for pasta in sorted(p for p in RAIZ_DAS_SKILLS.iterdir() if p.is_dir()):
        if not (pasta / "SKILL.md").is_file():
            continue
        skill = SkillDeArquivo(pasta.name)
        saida.append({
            "id": pasta.name,
            "origem": "arquivo",
            "nome": rotulo(pasta.name),
            "descricao": skill.frontmatter().get("description", "")[:400],
        })
    return saida


def rotulo(skill_id: str, nome: str = "") -> str:
    """Nome curto para o módulo. As skills do sistema têm rótulo fixo; as demais usam o nome enviado."""
    conhecidos = {
        "analise-e-organizacao-documental": "Análise e organização documental",
        "escritorio-trabalhista": "Escritório trabalhista",
    }
    if skill_id in conhecidos:
        return conhecidos[skill_id]
    base = nome.removesuffix(".skill.zip").removesuffix(".zip").replace("-", " ").replace("_", " ").strip()
    return (base or skill_id)[:80]


@lru_cache(maxsize=8)
def carregar(nome: str) -> SkillDeArquivo:
    skill = SkillDeArquivo(nome)
    log.info("skill carregada: %s sha256=%s arquivos=%d", nome, skill.sha256()[:16], len(skill.arquivos()))
    return skill


def criterios_documentais(*titulos: str) -> str:
    """Seções da skill documental (regex sobre o título), prontas para entrar numa instrução.

    Sem a skill no deploy devolve "": a leitura segue com a instrução própria, e o log avisa.
    """
    try:
        skill = carregar(SKILL_DOCUMENTAL)
    except SkillAusente:
        log.warning("skill documental ausente: leitura de documentos sem os critérios dela")
        return ""
    corpo = "\n\n".join(p for p in (skill.secao(t) for t in titulos) if p)
    if not corpo:
        return ""
    return (
        f"=== CRITÉRIOS DA SKILL DOCUMENTAL ({SKILL_DOCUMENTAL}) — siga-os ao ler os documentos; "
        f"o formato da resposta continua sendo o pedido acima ===\n{corpo}"
    )
