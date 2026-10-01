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
_MAX_VERSOES = 60


class AlteradaNoMeioTempo(ValueError):
    """Outra pessoa gravou a skill entre a leitura e a gravação."""


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
        # Sem chave estrangeira: o histórico sobrevive à exclusão da skill.
        con.execute("""
            CREATE TABLE IF NOT EXISTS skills_juridicas_versoes (
                id bigserial PRIMARY KEY,
                skill_id varchar(80) NOT NULL,
                skill_md text NOT NULL,
                referencias_json jsonb NOT NULL DEFAULT '{}'::jsonb,
                motivo varchar(300) NOT NULL DEFAULT '',
                gravado_por varchar(200) NOT NULL DEFAULT '',
                gravado_em timestamptz NOT NULL DEFAULT now()
            )
        """)
        con.execute(
            "CREATE INDEX IF NOT EXISTS skills_juridicas_versoes_skill ON skills_juridicas_versoes (skill_id, id DESC)"
        )


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


def assets(skill_id: str) -> list[tuple[str, str, bytes]]:
    """(caminho no pacote, mime, bytes) das imagens da skill."""
    inicializar()
    with peticao_skills._conectar() as con:
        linhas = con.execute(
            "SELECT caminho, mime, conteudo FROM skills_juridicas_assets WHERE skill_id = %s ORDER BY caminho",
            (skill_id,),
        ).fetchall()
    return [(caminho, mime, bytes(conteudo)) for caminho, mime, conteudo in linhas]


def _em_references(caminho: str) -> bool:
    return caminho.startswith("references/") or "/references/" in caminho


def ler_zip(conteudo: bytes) -> tuple[str, dict[str, str], list[tuple[str, str, bytes]]]:
    """(SKILL.md, referências por caminho no pacote, assets de imagem), sem gravar nada."""
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
    referencias = {caminho: texto for caminho, texto in textos.items() if _em_references(caminho)}
    if not referencias:
        raise ValueError("A skill precisa conter ao menos uma referência em references/.")
    return principal, referencias, assets


def _guardar_versao(con: Any, skill_id: str, skill_md: str, referencias: dict[str, str], motivo: str, por: str) -> None:
    con.execute(
        """INSERT INTO skills_juridicas_versoes (skill_id, skill_md, referencias_json, motivo, gravado_por)
           VALUES (%s, %s, %s::jsonb, %s, %s)""",
        (skill_id, skill_md, json.dumps(referencias, ensure_ascii=False), motivo[:300], por[:200]),
    )


def _gravar_textos(
    con: Any,
    skill_id: str,
    nome: str,
    descricao: str,
    skill_md: str,
    referencias: dict[str, str],
    *,
    motivo: str,
    por: str = "",
    lida_em: str | None = None,
) -> None:
    """Grava o texto e guarda a versão no histórico, na mesma transação.

    `lida_em` é o `atualizado_em` de quando a skill foi lida para editar: se ela
    mudou desde então, nada é gravado (`AlteradaNoMeioTempo`).
    """
    from . import skill_peticao

    atual = con.execute(
        "SELECT skill_md, referencias_json, atualizado_em FROM skills_juridicas WHERE id = %s FOR UPDATE",
        (skill_id,),
    ).fetchone()
    if lida_em is not None and (str(atual[2]) if atual else "") != lida_em:
        raise AlteradaNoMeioTempo("Outra pessoa alterou esta skill enquanto você editava. Nada foi gravado.")
    if atual:
        skill_peticao.conferir_substituicao(skill_id, (atual[0], dict(atual[1] or {})), (skill_md, referencias))
        tem_historico = con.execute(
            "SELECT 1 FROM skills_juridicas_versoes WHERE skill_id = %s LIMIT 1", (skill_id,)
        ).fetchone()
        if not tem_historico:
            _guardar_versao(con, skill_id, atual[0], dict(atual[1] or {}), "Versão anterior ao histórico", "")
    con.execute(
        """INSERT INTO skills_juridicas (id, nome, descricao, skill_md, referencias_json)
           VALUES (%s, %s, %s, %s, %s::jsonb)
           ON CONFLICT (id) DO UPDATE SET nome=EXCLUDED.nome, descricao=EXCLUDED.descricao,
               skill_md=EXCLUDED.skill_md, referencias_json=EXCLUDED.referencias_json,
               atualizado_em=now()""",
        (skill_id, nome[:200], descricao[:500], skill_md, json.dumps(referencias, ensure_ascii=False)),
    )
    _guardar_versao(con, skill_id, skill_md, referencias, motivo, por)
    con.execute(
        """DELETE FROM skills_juridicas_versoes WHERE skill_id = %s AND id NOT IN (
               SELECT id FROM skills_juridicas_versoes WHERE skill_id = %s ORDER BY id DESC LIMIT %s)""",
        (skill_id, skill_id, _MAX_VERSOES),
    )


def gravar_textos(
    skill_id: str,
    nome: str,
    descricao: str,
    skill_md: str,
    referencias: dict[str, str],
    *,
    motivo: str,
    por: str = "",
    lida_em: str | None = None,
) -> None:
    """Regrava o texto da skill (edição pela tela). Os assets ficam como estão."""
    inicializar()
    with peticao_skills._conectar() as con:
        _gravar_textos(con, skill_id, nome, descricao, skill_md, referencias, motivo=motivo, por=por, lida_em=lida_em)


def versoes(skill_id: str) -> list[dict[str, Any]]:
    """O histórico da skill, da gravação mais nova para a mais antiga."""
    inicializar()
    with peticao_skills._conectar(row_factory=peticao_skills.dict_row) as con:
        linhas = con.execute(
            """SELECT id, motivo, gravado_por, gravado_em FROM skills_juridicas_versoes
               WHERE skill_id = %s ORDER BY id DESC""",
            (skill_id,),
        ).fetchall()
    return [{**linha, "gravado_em": str(linha["gravado_em"])} for linha in linhas]


def versao(skill_id: str, versao_id: int) -> dict[str, Any] | None:
    """Uma versão do histórico no mesmo formato de `obter`."""
    inicializar()
    with peticao_skills._conectar(row_factory=peticao_skills.dict_row) as con:
        linha = con.execute(
            "SELECT * FROM skills_juridicas_versoes WHERE skill_id = %s AND id = %s", (skill_id, versao_id)
        ).fetchone()
    if not linha:
        return None
    linha["referencias"] = dict(linha.pop("referencias_json") or {})
    linha["gravado_em"] = str(linha["gravado_em"])
    return linha


def id_do_nome(nome: str) -> str:
    return _slug(nome.removesuffix(".skill.zip").removesuffix(".zip"))


def importar_zip(
    nome: str,
    conteudo: bytes,
    descricao: str | None = None,
    *,
    por: str = "",
    motivo: str = "Pacote .skill.zip importado",
    manter: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Importa Markdown de uma `.skill.zip`; nunca extrai nem executa conteúdo.

    `manter`: referências (caminho no pacote → texto) que entram só se o pacote não
    trouxer um arquivo com o mesmo nome.
    """
    principal, referencias, assets = ler_zip(conteudo)
    nomes_no_pacote = {Path(caminho).name for caminho in referencias}
    for caminho, texto in (manter or {}).items():
        if Path(caminho).name not in nomes_no_pacote:
            referencias[caminho] = texto
    skill_id = id_do_nome(nome)
    inicializar()
    with peticao_skills._conectar() as con:
        _gravar_textos(
            con, skill_id, nome, descricao or "Skill jurídica importada do pacote enviado.", principal, referencias,
            motivo=motivo, por=por,
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


def criar(nome: str, descricao: str, texto: str, *, por: str = "") -> dict[str, Any]:
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
    return importar_zip(nome, pacote.getvalue(), descricao.strip() or None, por=por, motivo="Skill escrita na tela")


def importar_embutida(caminho: Path) -> dict[str, Any] | None:
    """Instala a skill distribuída com a imagem somente quando ela não existe.

    Não atualiza silenciosamente uma versão que o escritório tenha editado ou
    reimportado depois: o pacote embutido é apenas o seed inicial da instalação.
    """
    skill_id = _slug(caminho.name.removesuffix(".skill.zip").removesuffix(".zip"))
    if obter(skill_id) is not None:
        return None
    return importar_zip(caminho.name, caminho.read_bytes(), motivo="Instalação do sistema")


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
