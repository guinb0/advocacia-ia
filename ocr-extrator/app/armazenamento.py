"""Persistência dos casos e das entregas de documentos (SQLite).

SQLite e não um banco de verdade porque isto roda na máquina do advogado: os
arquivos são de clientes e não devem sair dali. Sem servidor, sem dependência,
o banco é um arquivo só — dá para levar num pendrive ou fazer backup copiando.

Os arquivos enviados ficam em `dados/casos/<id do caso>/`, fora do git.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

BASE = Path(__file__).resolve().parent.parent
DIR_DADOS = BASE / "dados"
DIR_ARQUIVOS = DIR_DADOS / "casos"
CAMINHO_BANCO = DIR_DADOS / "casos.db"

ESQUEMA = """
CREATE TABLE IF NOT EXISTS casos (
    id            TEXT PRIMARY KEY,
    cliente       TEXT NOT NULL,
    categoria     TEXT NOT NULL,
    observacao    TEXT NOT NULL DEFAULT '',
    criado_em     TEXT NOT NULL,
    atualizado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entregas (
    id                 TEXT PRIMARY KEY,
    caso_id            TEXT NOT NULL REFERENCES casos(id) ON DELETE CASCADE,
    item_codigo        TEXT NOT NULL,
    arquivo            TEXT NOT NULL,
    caminho            TEXT NOT NULL,
    tipo_detectado     TEXT,
    tipo_confere       INTEGER,
    veredito           TEXT,
    dados_utilizaveis  INTEGER NOT NULL DEFAULT 0,
    confirmado_manual  INTEGER NOT NULL DEFAULT 0,
    score_legibilidade INTEGER,
    itens_atendidos    TEXT NOT NULL DEFAULT '[]',
    extracao_json      TEXT,
    criado_em          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_entregas_caso ON entregas(caso_id);
CREATE INDEX IF NOT EXISTS idx_entregas_item ON entregas(caso_id, item_codigo);
"""


def agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def conectar() -> Iterator[sqlite3.Connection]:
    DIR_DADOS.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(CAMINHO_BANCO, timeout=15)
    con.row_factory = sqlite3.Row
    # WAL deixa leitura e escrita coexistirem; sem ele o upload de um documento
    # travaria quem estivesse só consultando a lista de casos.
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def inicializar() -> None:
    with conectar() as con:
        con.executescript(ESQUEMA)
        # Bancos criados antes da identidade unificada ainda não têm esta coluna.
        colunas = {linha["name"] for linha in con.execute("PRAGMA table_info(entregas)")}
        if "itens_atendidos" not in colunas:
            con.execute("ALTER TABLE entregas ADD COLUMN itens_atendidos TEXT NOT NULL DEFAULT '[]'")
        if "confirmado_manual" not in colunas:
            con.execute("ALTER TABLE entregas ADD COLUMN confirmado_manual INTEGER NOT NULL DEFAULT 0")

        # Portal do cliente. Guardamos o hash da senha, nunca a senha: nem esta
        # tabela nem a tela do advogado conseguem revelá-la depois de gerada.
        # Upload assíncrono: a entrega existe antes do OCR terminar. Bancos
        # antigos só têm entregas já processadas, daí o default 'pronto'.
        if "status_proc" not in colunas:
            con.execute(
                "ALTER TABLE entregas ADD COLUMN status_proc TEXT NOT NULL DEFAULT 'pronto'"
            )
            con.execute("ALTER TABLE entregas ADD COLUMN erro_proc TEXT")

        colunas_casos = {linha["name"] for linha in con.execute("PRAGMA table_info(casos)")}
        if "portal_token" not in colunas_casos:
            con.execute("ALTER TABLE casos ADD COLUMN portal_token TEXT")
            con.execute("ALTER TABLE casos ADD COLUMN portal_senha_hash TEXT")
            con.execute("ALTER TABLE casos ADD COLUMN portal_sal TEXT")
            con.execute("ALTER TABLE casos ADD COLUMN portal_criado_em TEXT")
            # Busca por token acontece a cada requisição do cliente.
            con.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_casos_portal_token "
                "ON casos(portal_token) WHERE portal_token IS NOT NULL"
            )
    DIR_ARQUIVOS.mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------------------- casos


def criar_caso(cliente: str, categoria: str, observacao: str = "") -> dict[str, Any]:
    caso_id = str(uuid.uuid4())
    instante = agora()
    with conectar() as con:
        con.execute(
            "INSERT INTO casos (id, cliente, categoria, observacao, criado_em, atualizado_em)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (caso_id, cliente.strip(), categoria, observacao.strip(), instante, instante),
        )
    (DIR_ARQUIVOS / caso_id).mkdir(parents=True, exist_ok=True)
    return {
        "id": caso_id,
        "cliente": cliente.strip(),
        "categoria": categoria,
        "observacao": observacao.strip(),
        "criado_em": instante,
        "atualizado_em": instante,
    }


def listar_casos() -> list[dict[str, Any]]:
    with conectar() as con:
        linhas = con.execute(
            """
            SELECT c.*,
                   (SELECT COUNT(*) FROM entregas e WHERE e.caso_id = c.id) AS total_entregas
              FROM casos c
             ORDER BY c.atualizado_em DESC
            """
        ).fetchall()
    return [_sem_segredos(l) for l in linhas]


# Colunas que jamais podem sair numa resposta HTTP: com o hash e o sal em mãos,
# a senha do portal vira alvo de força bruta offline, sem o limite de tentativas.
SEGREDOS_DO_CASO = ("portal_senha_hash", "portal_sal")


def _sem_segredos(linha: Any) -> dict[str, Any]:
    caso = dict(linha)
    for chave in SEGREDOS_DO_CASO:
        caso.pop(chave, None)
    # O cliente do portal não precisa saber que existe senha; o advogado sim.
    caso["portal_ativo"] = bool(caso.get("portal_token"))
    return caso


def obter_caso(caso_id: str) -> dict[str, Any] | None:
    """Caso pronto para ir à API — sem hash nem sal da senha do portal."""
    with conectar() as con:
        linha = con.execute("SELECT * FROM casos WHERE id = ?", (caso_id,)).fetchone()
    return _sem_segredos(linha) if linha else None


def obter_caso_com_segredos(caso_id: str) -> dict[str, Any] | None:
    """Uso interno da autenticação do portal. Nunca devolva isto pela API."""
    with conectar() as con:
        linha = con.execute("SELECT * FROM casos WHERE id = ?", (caso_id,)).fetchone()
    return dict(linha) if linha else None


def obter_caso_por_token(token: str) -> dict[str, Any] | None:
    """Uso interno da autenticação do portal. Nunca devolva isto pela API."""
    if not token:
        return None
    with conectar() as con:
        linha = con.execute("SELECT * FROM casos WHERE portal_token = ?", (token,)).fetchone()
    return dict(linha) if linha else None


def definir_portal(caso_id: str, token: str, senha_hash: str, sal: str) -> bool:
    """Grava (ou troca) as credenciais do portal do caso."""
    with conectar() as con:
        cur = con.execute(
            """
            UPDATE casos
               SET portal_token = ?, portal_senha_hash = ?, portal_sal = ?, portal_criado_em = ?
             WHERE id = ?
            """,
            (token, senha_hash, sal, agora(), caso_id),
        )
    return cur.rowcount > 0


def atualizar_caso(caso_id: str, cliente: str | None = None, observacao: str | None = None) -> bool:
    campos, valores = [], []
    if cliente is not None:
        campos.append("cliente = ?")
        valores.append(cliente.strip())
    if observacao is not None:
        campos.append("observacao = ?")
        valores.append(observacao.strip())
    if not campos:
        return False

    campos.append("atualizado_em = ?")
    valores.extend([agora(), caso_id])

    with conectar() as con:
        cur = con.execute(f"UPDATE casos SET {', '.join(campos)} WHERE id = ?", valores)
    return cur.rowcount > 0


def excluir_caso(caso_id: str) -> bool:
    """Apaga o caso, suas entregas e os arquivos enviados."""
    with conectar() as con:
        cur = con.execute("DELETE FROM casos WHERE id = ?", (caso_id,))
        removido = cur.rowcount > 0

    if removido:
        import shutil

        shutil.rmtree(DIR_ARQUIVOS / caso_id, ignore_errors=True)
    return removido


def _tocar_caso(con: sqlite3.Connection, caso_id: str) -> None:
    con.execute("UPDATE casos SET atualizado_em = ? WHERE id = ?", (agora(), caso_id))


def _normalizar_entrega(linha: sqlite3.Row) -> dict[str, Any]:
    """SQLite devolve booleano como inteiro; aqui volta a ser bool/None.

    Sem isto, `tipo_confere` chega como 0 e um `is False` lá em cima nunca casa
    (`0 is False` é falso em Python) — um arquivo trocado passaria como correto.
    """
    registro = dict(linha)
    if "dados_utilizaveis" in registro:
        registro["dados_utilizaveis"] = bool(registro["dados_utilizaveis"])
    if "confirmado_manual" in registro:
        registro["confirmado_manual"] = bool(registro["confirmado_manual"])
    if "tipo_confere" in registro:
        valor = registro["tipo_confere"]
        registro["tipo_confere"] = None if valor is None else bool(valor)
    itens_atendidos = registro.get("itens_atendidos")
    if isinstance(itens_atendidos, str):
        try:
            itens_atendidos = json.loads(itens_atendidos)
        except json.JSONDecodeError:
            itens_atendidos = []
    # Entregas antigas atendem apenas ao item em que foram enviadas.
    registro["itens_atendidos"] = itens_atendidos or [registro["item_codigo"]]
    return registro


# ---------------------------------------------------------------- entregas


def registrar_entrega_pendente(
    caso_id: str,
    item_codigo: str,
    arquivo: str,
    caminho: Path,
    itens_atendidos: list[str] | None = None,
) -> dict[str, Any]:
    """Cria a entrega antes do OCR: o arquivo já está salvo, a leitura vem depois.

    É o que permite responder o upload na hora. Até `concluir_entrega`, esta
    linha não conta como documento entregue em lugar nenhum.
    """
    entrega_id = str(uuid.uuid4())
    itens = list(dict.fromkeys(itens_atendidos or [item_codigo]))
    if item_codigo not in itens:
        itens.append(item_codigo)

    with conectar() as con:
        con.execute(
            """
            INSERT INTO entregas (id, caso_id, item_codigo, arquivo, caminho, tipo_detectado,
                                  tipo_confere, veredito, dados_utilizaveis, confirmado_manual,
                                  score_legibilidade, itens_atendidos, extracao_json,
                                  status_proc, criado_em)
            VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, 0, 0, NULL, ?, NULL, 'processando', ?)
            """,
            (entrega_id, caso_id, item_codigo, arquivo, str(caminho), json.dumps(itens), agora()),
        )
        _tocar_caso(con, caso_id)

    return obter_entrega(entrega_id) or {}


def concluir_entrega(
    entrega_id: str,
    extracao: dict[str, Any],
    tipo_confere: bool | None,
    itens_atendidos: list[str],
) -> dict[str, Any] | None:
    """Preenche a entrega com o resultado do OCR."""
    validacao = extracao.get("validacao", {})
    with conectar() as con:
        con.execute(
            """
            UPDATE entregas
               SET tipo_detectado = ?, tipo_confere = ?, veredito = ?, dados_utilizaveis = ?,
                   score_legibilidade = ?, itens_atendidos = ?, extracao_json = ?,
                   status_proc = 'pronto', erro_proc = NULL
             WHERE id = ?
            """,
            (
                extracao.get("tipo", {}).get("detectado") or extracao.get("tipo", {}).get("codigo"),
                None if tipo_confere is None else int(tipo_confere),
                validacao.get("veredito"),
                int(bool(validacao.get("dados_utilizaveis"))),
                validacao.get("score_legibilidade"),
                json.dumps(list(dict.fromkeys(itens_atendidos))),
                json.dumps(extracao, ensure_ascii=False),
                entrega_id,
            ),
        )
        linha = con.execute("SELECT caso_id FROM entregas WHERE id = ?", (entrega_id,)).fetchone()
        if linha:
            _tocar_caso(con, linha["caso_id"])
    return obter_entrega(entrega_id)


def falhar_entrega(entrega_id: str, mensagem: str) -> None:
    """Marca a entrega como não lida. O arquivo continua salvo para reprocessar."""
    with conectar() as con:
        con.execute(
            "UPDATE entregas SET status_proc = 'erro', erro_proc = ? WHERE id = ?",
            (mensagem[:500], entrega_id),
        )


def registrar_entrega(
    caso_id: str,
    item_codigo: str,
    arquivo: str,
    caminho: Path,
    extracao: dict[str, Any],
    tipo_confere: bool | None,
    itens_atendidos: list[str] | None = None,
) -> dict[str, Any]:
    entrega_id = str(uuid.uuid4())
    validacao = extracao.get("validacao", {})

    itens = list(dict.fromkeys(itens_atendidos or [item_codigo]))
    if item_codigo not in itens:
        itens.insert(0, item_codigo)

    registro = {
        "id": entrega_id,
        "caso_id": caso_id,
        "item_codigo": item_codigo,
        "arquivo": arquivo,
        "caminho": str(caminho),
        # O que o classificador leu sozinho — não o tipo que a extração usou, que
        # pode ter sido forçado pelo item do checklist. É este que denuncia a troca.
        "tipo_detectado": extracao.get("tipo", {}).get("detectado")
        or extracao.get("tipo", {}).get("codigo"),
        "tipo_confere": None if tipo_confere is None else int(tipo_confere),
        "veredito": validacao.get("veredito"),
        "dados_utilizaveis": int(bool(validacao.get("dados_utilizaveis"))),
        "confirmado_manual": 0,
        "score_legibilidade": validacao.get("score_legibilidade"),
        "itens_atendidos": json.dumps(itens),
        "extracao_json": json.dumps(extracao, ensure_ascii=False),
        "criado_em": agora(),
    }

    with conectar() as con:
        con.execute(
            """
            INSERT INTO entregas (id, caso_id, item_codigo, arquivo, caminho, tipo_detectado,
                                  tipo_confere, veredito, dados_utilizaveis, confirmado_manual,
                                  score_legibilidade, itens_atendidos, extracao_json, criado_em)
            VALUES (:id, :caso_id, :item_codigo, :arquivo, :caminho, :tipo_detectado,
                    :tipo_confere, :veredito, :dados_utilizaveis, :confirmado_manual,
                    :score_legibilidade, :itens_atendidos, :extracao_json, :criado_em)
            """,
            registro,
        )
        _tocar_caso(con, caso_id)

    registro.pop("extracao_json")
    # Devolve bool/None, como quem lê do banco recebe.
    registro["dados_utilizaveis"] = bool(registro["dados_utilizaveis"])
    registro["confirmado_manual"] = False
    registro["tipo_confere"] = tipo_confere
    registro["itens_atendidos"] = itens
    return registro


def listar_entregas(caso_id: str) -> list[dict[str, Any]]:
    """Entregas do caso, sem o JSON completo da extração (que é grande)."""
    with conectar() as con:
        linhas = con.execute(
            """
            SELECT id, caso_id, item_codigo, arquivo, tipo_detectado, tipo_confere,
                   veredito, dados_utilizaveis, confirmado_manual, score_legibilidade,
                   itens_atendidos, status_proc, erro_proc, criado_em
              FROM entregas
             WHERE caso_id = ?
             ORDER BY criado_em
            """,
            (caso_id,),
        ).fetchall()
    return [_normalizar_entrega(l) for l in linhas]


def atualizar_para_identidade_unificada(
    entrega_id: str,
    extracao: dict[str, Any],
    itens_atendidos: list[str],
) -> dict[str, Any] | None:
    """Vincula uma entrega existente aos dois itens após confirmar que é uma CIN."""
    validacao = extracao.get("validacao", {})
    itens = list(dict.fromkeys(itens_atendidos))
    with conectar() as con:
        linha = con.execute("SELECT * FROM entregas WHERE id = ?", (entrega_id,)).fetchone()
        if not linha:
            return None

        con.execute(
            """
            UPDATE entregas
               SET tipo_detectado = ?, tipo_confere = 1, veredito = ?,
                   dados_utilizaveis = ?, confirmado_manual = 1, score_legibilidade = ?,
                   itens_atendidos = ?, extracao_json = ?
             WHERE id = ?
            """,
            (
                extracao.get("tipo", {}).get("detectado") or extracao.get("tipo", {}).get("codigo"),
                validacao.get("veredito"),
                int(bool(validacao.get("dados_utilizaveis"))),
                validacao.get("score_legibilidade"),
                json.dumps(itens),
                json.dumps(extracao, ensure_ascii=False),
                entrega_id,
            ),
        )
        _tocar_caso(con, linha["caso_id"])
        atualizada = con.execute("SELECT * FROM entregas WHERE id = ?", (entrega_id,)).fetchone()

    registro = _normalizar_entrega(atualizada)
    registro.pop("extracao_json", None)
    return registro


def obter_entrega(entrega_id: str) -> dict[str, Any] | None:
    with conectar() as con:
        linha = con.execute("SELECT * FROM entregas WHERE id = ?", (entrega_id,)).fetchone()
    if not linha:
        return None
    registro = _normalizar_entrega(linha)
    if registro.get("extracao_json"):
        registro["extracao"] = json.loads(registro.pop("extracao_json"))
    return registro


def excluir_entrega(entrega_id: str) -> bool:
    with conectar() as con:
        linha = con.execute(
            "SELECT caso_id, caminho FROM entregas WHERE id = ?", (entrega_id,)
        ).fetchone()
        if not linha:
            return False
        con.execute("DELETE FROM entregas WHERE id = ?", (entrega_id,))
        _tocar_caso(con, linha["caso_id"])

    Path(linha["caminho"]).unlink(missing_ok=True)
    return True
