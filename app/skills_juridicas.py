"""Biblioteca versionada de skills jurídicas importadas pelo escritório.

Uma skill é conteúdo operacional, não código executável: o ZIP só pode conter
Markdown. Guardamos o texto no banco para que a imagem de produção não dependa
de um arquivo solto no host e para que cada seleção possa ser reproduzida.
"""
from __future__ import annotations

import io
import json
import logging
import re
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import peticao_skills

log = logging.getLogger("skills_juridicas")

_MAX_ARQUIVOS = 80
_MAX_BYTES = 2 * 1024 * 1024


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _slug(valor: str) -> str:
    resultado = re.sub(r"[^a-z0-9]+", "-", valor.lower()).strip("-")
    return resultado[:80] or "skill"


def inicializar() -> None:
    with peticao_skills._conectar() as con:  # mesma base de configuração jurídica
        con.execute("""
            CREATE TABLE IF NOT EXISTS skills_juridicas (
                id varchar(80) PRIMARY KEY,
                nome varchar(200) NOT NULL,
                descricao text NOT NULL DEFAULT '',
                skill_md text NOT NULL,
                referencias_json jsonb NOT NULL DEFAULT '{}'::jsonb,
                criado_em timestamptz NOT NULL DEFAULT now(),
                atualizado_em timestamptz NOT NULL DEFAULT now()
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS skills_juridicas_assets (
                id varchar(80) PRIMARY KEY,
                skill_id varchar(80) NOT NULL REFERENCES skills_juridicas(id) ON DELETE CASCADE,
                caminho varchar(500) NOT NULL,
                mime varchar(100) NOT NULL,
                conteudo bytea NOT NULL,
                criado_em timestamptz NOT NULL DEFAULT now(),
                UNIQUE(skill_id, caminho)
            )
        """)


def listar() -> list[dict[str, Any]]:
    inicializar()
    with peticao_skills._conectar(row_factory=peticao_skills.dict_row) as con:
        linhas = con.execute(
            "SELECT id, nome, descricao, referencias_json, "
            "criado_em, atualizado_em FROM skills_juridicas ORDER BY nome"
        ).fetchall()
    return [{
        **linha,
        "referencias": len(dict(linha.pop("referencias_json") or {})),
        "criado_em": str(linha["criado_em"]),
        "atualizado_em": str(linha["atualizado_em"]),
    } for linha in linhas]


def obter(skill_id: str) -> dict[str, Any] | None:
    inicializar()
    with peticao_skills._conectar(row_factory=peticao_skills.dict_row) as con:
        linha = con.execute("SELECT * FROM skills_juridicas WHERE id = %s", (skill_id,)).fetchone()
    if not linha:
        return None
    linha["referencias"] = dict(linha.pop("referencias_json") or {})
    linha["criado_em"] = str(linha["criado_em"])
    linha["atualizado_em"] = str(linha["atualizado_em"])
    return linha


def importar_zip(nome: str, conteudo: bytes, descricao: str | None = None) -> dict[str, Any]:
    """Importa Markdown de uma `.skill.zip`; nunca extrai nem executa conteúdo."""
    if not conteudo:
        raise ValueError("A skill enviada está vazia.")
    try:
        with zipfile.ZipFile(io.BytesIO(conteudo)) as pacote:
            entradas = [i for i in pacote.infolist() if not i.is_dir()]
            if len(entradas) > _MAX_ARQUIVOS or sum(i.file_size for i in entradas) > _MAX_BYTES:
                raise ValueError("A skill excede os limites de importação.")
            textos: dict[str, str] = {}
            assets: list[tuple[str, str, bytes]] = []
            for entrada in entradas:
                caminho = entrada.filename.replace("\\", "/")
                if caminho.startswith("/") or ".." in caminho.split("/"):
                    raise ValueError("A skill contém caminho inválido.")
                if not caminho.lower().endswith(".md"):
                    extensao = caminho.rsplit(".", 1)[-1].lower() if "." in caminho else ""
                    mimes = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}
                    if (caminho.startswith("assets/") or "/assets/" in caminho) and extensao in mimes:
                        assets.append((caminho, mimes[extensao], pacote.read(entrada)))
                    continue
                textos[caminho] = pacote.read(entrada).decode("utf-8-sig")
    except zipfile.BadZipFile as exc:
        raise ValueError("O arquivo não é uma skill ZIP válida.") from exc

    principal = next((texto for caminho, texto in textos.items() if caminho.endswith("/SKILL.md") or caminho == "SKILL.md"), "")
    if not principal:
        raise ValueError("A skill precisa conter SKILL.md.")
    referencias = {caminho: texto for caminho, texto in textos.items() if "/references/" in caminho}
    if not referencias:
        raise ValueError("A skill precisa conter ao menos uma referência em references/.")
    skill_id = _slug(nome.removesuffix(".skill.zip").removesuffix(".zip"))
    inicializar()
    with peticao_skills._conectar() as con:
        con.execute(
            """INSERT INTO skills_juridicas (id, nome, descricao, skill_md, referencias_json)
               VALUES (%s, %s, %s, %s, %s::jsonb)
               ON CONFLICT (id) DO UPDATE SET nome=EXCLUDED.nome, descricao=EXCLUDED.descricao,
                   skill_md=EXCLUDED.skill_md, referencias_json=EXCLUDED.referencias_json,
                   atualizado_em=now()""",
            (skill_id, nome[:200], (descricao or "Skill jurídica importada do pacote enviado.")[:500], principal, json.dumps(referencias, ensure_ascii=False)),
        )
        # Reimportar substitui os assets da mesma skill, evitando logo antigo
        # sobreviver silenciosamente a uma atualização do pacote.
        con.execute("DELETE FROM skills_juridicas_assets WHERE skill_id = %s", (skill_id,))
        for caminho, mime, dados in assets:
            con.execute(
                "INSERT INTO skills_juridicas_assets (id, skill_id, caminho, mime, conteudo) VALUES (%s, %s, %s, %s, %s)",
                (str(uuid.uuid4()), skill_id, caminho, mime, dados),
            )
    return obter(skill_id) or {"id": skill_id}


def criar(nome: str, descricao: str, texto: str) -> dict[str, Any]:
    """Grava uma skill nova a partir do texto. Ela passa a ser um módulo próprio."""
    nome = nome.strip()
    texto = texto.strip()
    if not nome or not texto:
        raise ValueError("A skill precisa de nome e de texto.")
    if not texto.startswith("---"):
        texto = f"---\nname: {_slug(nome)}\ndescription: {descricao.strip()}\n---\n\n# {nome}\n\n{texto}\n"
    pacote = io.BytesIO()
    with zipfile.ZipFile(pacote, "w") as arquivo:
        arquivo.writestr("SKILL.md", texto)
        arquivo.writestr("references/notas.md", "Notas da skill adicionada pelo escritório.\n")
    return importar_zip(nome, pacote.getvalue(), descricao.strip() or None)


def importar_embutida(caminho: Path) -> dict[str, Any] | None:
    """Instala a skill distribuída com a imagem somente quando ela não existe.

    Não atualiza silenciosamente uma versão que o escritório tenha editado ou
    reimportado depois: o pacote embutido é apenas o seed inicial da instalação.
    """
    skill_id = _slug(caminho.name.removesuffix(".skill.zip").removesuffix(".zip"))
    if obter(skill_id) is not None:
        return None
    return importar_zip(caminho.name, caminho.read_bytes())


def catalogo() -> list[dict[str, Any]]:
    """Skills de arquivo e as adicionadas pelo escritório, sem repetir o mesmo id."""
    from . import skill_de_arquivo

    arquivos = skill_de_arquivo.listar()
    ids = {item["id"] for item in arquivos}
    importadas: list[dict[str, Any]] = []
    try:
        importadas = [
            {
                "id": item["id"],
                "origem": "importada",
                "nome": skill_de_arquivo.rotulo(item["id"], item.get("nome") or ""),
                "descricao": str(item.get("descricao") or "")[:400],
            }
            for item in listar()
            if item["id"] not in ids
        ]
    except Exception:
        log.warning("skills importadas indisponíveis", exc_info=True)
    return arquivos + importadas


def detalhe(skill_id: str) -> dict[str, Any] | None:
    """O texto da skill, para o módulo próprio dela."""
    from . import skill_de_arquivo

    try:
        skill = skill_de_arquivo.carregar(skill_id)
    except skill_de_arquivo.SkillAusente:
        skill = None
    if skill is not None:
        texto = skill.ler("SKILL.md")
        return {
            "id": skill_id,
            "origem": "arquivo",
            "nome": skill_de_arquivo.rotulo(skill_id),
            "descricao": skill.frontmatter().get("description", "")[:400],
            "texto": texto[:20000],
            "cortado": len(texto) > 20000,
        }
    try:
        registro = obter(skill_id)
    except Exception:
        return None
    if not registro:
        return None
    texto = str(registro.get("skill_md") or "")
    return {
        "id": skill_id,
        "origem": "importada",
        "nome": skill_de_arquivo.rotulo(skill_id, str(registro.get("nome") or "")),
        "descricao": str(registro.get("descricao") or "")[:400],
        "texto": texto[:20000],
        "cortado": len(texto) > 20000,
    }
