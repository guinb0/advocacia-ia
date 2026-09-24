"""Biblioteca versionada de skills jurídicas importadas pelo escritório.

Uma skill é conteúdo operacional, não código executável: o ZIP só pode conter
Markdown. Guardamos o texto no banco para que a imagem de produção não dependa
de um arquivo solto no host e para que cada seleção possa ser reproduzida.
"""
from __future__ import annotations

import io
import json
import re
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import peticao_skills

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


def importar_zip(nome: str, conteudo: bytes) -> dict[str, Any]:
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
            (skill_id, nome[:200], "Skill jurídica importada do pacote enviado.", principal, json.dumps(referencias, ensure_ascii=False)),
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


def importar_embutida(caminho: Path) -> dict[str, Any] | None:
    """Instala a skill distribuída com a imagem somente quando ela não existe.

    Não atualiza silenciosamente uma versão que o escritório tenha editado ou
    reimportado depois: o pacote embutido é apenas o seed inicial da instalação.
    """
    skill_id = _slug(caminho.name.removesuffix(".skill.zip").removesuffix(".zip"))
    if obter(skill_id) is not None:
        return None
    return importar_zip(caminho.name, caminho.read_bytes())
