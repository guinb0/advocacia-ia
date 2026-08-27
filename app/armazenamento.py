"""Persistência do Acervo, no SQL Server.

Este módulo fala SQL e nada mais: a conexão, o schema e as diferenças de dialeto vivem
em `banco.py`. É o que permitiu trocar o motor sem reescrever as 44 funções daqui.

Antes o banco era um arquivo SQLite na máquina do advogado (`dados/casos.db`). Servia
enquanto era uma pessoa só — mas não é alcançável de outro computador, não tem backup e
recusa duas escritas ao mesmo tempo. Os arquivos enviados pelo cliente continuam em
disco (`dados/casos/`); o que foi para o servidor é o registro, não o binário.
"""

from __future__ import annotations

import hashlib
import json
import logging
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from . import banco
from .banco import conectar

log = logging.getLogger("armazenamento")

BASE = Path(__file__).resolve().parent.parent
DIR_DADOS = BASE / "dados"
DIR_ARQUIVOS = DIR_DADOS / "casos"
#: Contratos assinados baixados da ZapSign. Ficam fora de `casos/` porque o
#: contrato existe antes do caso: ele é assinado na entrevista, e o caso só é
#: aberto depois. Apagar um caso não pode levar junto o contrato assinado.
DIR_CONTRATOS = DIR_DADOS / "contratos"
CAMINHO_BANCO = DIR_DADOS / "casos.db"

# O schema mora em `banco.py`, em T-SQL.


def agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalizar_nome_cliente(cliente: object) -> str:
    """Chave estável para reencontrar contratos criados antes do caso."""
    return " ".join(str(cliente or "").split())


def _normalizar_cpf(cpf: object) -> str:
    texto = unicodedata.normalize("NFKC", str(cpf or ""))
    return "".join(c for c in texto if "0" <= c <= "9")


# A conexão vive em `banco.py`: é lá que o SQL Server entra, com a mesma interface que o
# SQLite oferecia (`?` como marcador, linha acessível por nome de coluna). Este módulo
# continua falando SQL e não sabe qual motor está do outro lado.


def inicializar() -> None:
    """Garante o schema e as pastas de arquivo.

    As migrações de coluna que existiam aqui eram para bancos SQLite criados antes de
    campos como `status_proc` e `portal_token` — o schema do SQL Server já nasce com
    todos eles, então não há nada a remendar.
    """
    banco.inicializar_schema()
    DIR_ARQUIVOS.mkdir(parents=True, exist_ok=True)
    DIR_CONTRATOS.mkdir(parents=True, exist_ok=True)


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


def _tocar_caso(con: banco.Conexao, caso_id: str) -> None:
    con.execute("UPDATE casos SET atualizado_em = ? WHERE id = ?", (agora(), caso_id))


def _normalizar_entrega(linha: banco.Linha) -> dict[str, Any]:
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


def _sha256(conteudo: bytes | None) -> str | None:
    return hashlib.sha256(conteudo).hexdigest() if conteudo else None


def _bytes(valor: Any) -> bytes | None:
    if valor is None:
        return None
    if isinstance(valor, bytes):
        return valor
    if isinstance(valor, bytearray):
        return bytes(valor)
    if isinstance(valor, memoryview):
        return valor.tobytes()
    return None


def _dentro_dos_arquivos(caminho: Path) -> bool:
    raiz = DIR_ARQUIVOS.resolve()
    resolvido = caminho.resolve()
    return resolvido == raiz or raiz in resolvido.parents


def _dentro_de_pasta_legada(caminho: Path, entrega: dict[str, Any]) -> bool:
    caso_id = str(entrega.get("caso_id") or "").lower()
    if not caso_id:
        return False
    partes = caminho.resolve().parts
    baixos = [p.lower() for p in partes]
    for indice in range(len(baixos) - 2):
        if (
            baixos[indice] == "dados"
            and baixos[indice + 1] == "casos"
            and baixos[indice + 2] == caso_id
        ):
            return True
    return False


def _candidatos_de_entrega(entrega: dict[str, Any]) -> Iterator[Path]:
    """Caminhos possíveis para uma entrega, incluindo registros de pasta antiga."""
    vistos: set[str] = set()

    def incluir(caminho: Path | None) -> Iterator[Path]:
        if caminho is None:
            return
        chave = str(caminho)
        if chave not in vistos:
            vistos.add(chave)
            yield caminho

    bruto = str(entrega.get("caminho") or "")
    salvo = Path(bruto) if bruto else None
    yield from incluir(salvo)

    if salvo is not None:
        partes = salvo.parts
        baixos = [p.lower() for p in partes]
        for indice in range(len(baixos) - 1):
            if baixos[indice] == "dados" and baixos[indice + 1] == "casos":
                # Banco migrado de outra pasta/máquina: preserva o trecho
                # `caso_id/arquivo.ext`, mas troca a raiz para a instalação atual.
                yield from incluir(DIR_ARQUIVOS.joinpath(*partes[indice + 2:]))
                break

    caso_id = str(entrega.get("caso_id") or "")
    if caso_id:
        nomes: list[str] = []
        if salvo is not None and salvo.name:
            nomes.append(salvo.name)
        if entrega.get("arquivo"):
            nomes.append(Path(str(entrega["arquivo"])).name)
        for nome in nomes:
            yield from incluir(DIR_ARQUIVOS / caso_id / nome)


def caminho_arquivo_entrega(entrega: dict[str, Any]) -> Path | None:
    """Arquivo original da entrega dentro da pasta atual de documentos, se existir."""
    for candidato in _candidatos_de_entrega(entrega):
        try:
            permitido = _dentro_dos_arquivos(candidato) or _dentro_de_pasta_legada(candidato, entrega)
            if permitido and candidato.is_file():
                return candidato.resolve()
        except OSError:
            continue
    return None


def conteudo_arquivo_entrega(entrega: dict[str, Any]) -> bytes | None:
    """Conteúdo original: disco primeiro, banco como fallback de migração."""
    caminho = caminho_arquivo_entrega(entrega)
    if caminho is not None:
        return caminho.read_bytes()
    return _bytes(entrega.get("conteudo"))


def _resumo_validacao(veredito: str | None, dados_utilizaveis: bool) -> str:
    if veredito == "APROVADO":
        return "Documento aprovado pelos dados salvos no banco."
    if veredito == "REPROVADO":
        return "Documento reprovado pelos dados salvos no banco."
    if veredito == "APROVADO_COM_RESSALVAS":
        return "Documento aprovado com ressalvas pelos dados salvos no banco."
    return (
        "Registro salvo no banco como utilizável."
        if dados_utilizaveis
        else "Registro salvo no banco sem conferência detalhada."
    )


def _completar_extracao(registro: dict[str, Any]) -> dict[str, Any]:
    extracao = registro.get("extracao")
    if not isinstance(extracao, dict):
        extracao = {}

    tipo_detectado = registro.get("tipo_detectado") or "desconhecido"
    tipo = extracao.get("tipo")
    if not isinstance(tipo, dict):
        tipo = {}
    tipo.setdefault("codigo", tipo_detectado)
    tipo.setdefault("detectado", tipo_detectado)
    tipo.setdefault("descricao", tipo.get("codigo") or tipo_detectado)
    tipo.setdefault("descricao_detectado", tipo.get("detectado") or tipo_detectado)
    extracao["tipo"] = tipo

    extracao.setdefault("id", registro.get("id"))
    extracao.setdefault("arquivo", registro.get("arquivo"))
    extracao.setdefault("processado_em", registro.get("criado_em"))
    extracao.setdefault("campos", [])
    extracao.setdefault("texto_linhas", [])
    extracao.setdefault("texto_completo", "")

    validacao = extracao.get("validacao")
    if not isinstance(validacao, dict):
        validacao = {}
    veredito = validacao.get("veredito") or registro.get("veredito")
    dados_utilizaveis = bool(
        validacao.get("dados_utilizaveis")
        if "dados_utilizaveis" in validacao
        else registro.get("dados_utilizaveis")
    )
    if veredito:
        validacao["veredito"] = veredito
    validacao.setdefault("dados_utilizaveis", dados_utilizaveis)
    validacao.setdefault("aprovado", dados_utilizaveis and veredito == "APROVADO")
    if registro.get("score_legibilidade") is not None:
        validacao.setdefault("score_legibilidade", registro.get("score_legibilidade"))
    if "completude_percentual" not in validacao:
        validacao["completude_percentual"] = 100 if dados_utilizaveis else 0
    validacao.setdefault("campos_esperados", [])
    validacao.setdefault("campos_faltando", [])
    validacao.setdefault("campos_invalidos", [])
    validacao.setdefault("campos_baixa_confianca", [])
    validacao.setdefault("erros", [])
    validacao.setdefault("avisos", [])
    validacao.setdefault("sugestoes", [])
    validacao.setdefault("resumo", _resumo_validacao(veredito, dados_utilizaveis))
    extracao["validacao"] = validacao

    return extracao


def _tipo_do_agente(codigo: str | None) -> tuple[str, str] | None:
    if not codigo:
        return None
    texto = str(codigo)
    curto = texto.removeprefix("DOCUMENT.").lower()
    if not curto:
        return None
    return curto, texto


def _enriquecer_extracao_do_agente(registro: dict[str, Any]) -> None:
    """Busca OCR/classificação espelhados no agente para entregas antigas."""
    entrega_id = str(registro.get("id") or "")
    if not entrega_id:
        return

    refs = (
        f"ocr://entregas/{entrega_id}",
        f"ocr://entregas/{entrega_id}/%",
    )
    try:
        with conectar() as con:
            doc = con.execute(
                """
                SELECT TOP 1 CONVERT(varchar(64), id) AS id,
                       document_type, detected_type, status, verdict,
                       CONVERT(varchar(40), processed_at, 126) AS processed_at
                  FROM documents
                 WHERE source_reference = ? OR source_reference LIKE ?
                 ORDER BY
                       CASE WHEN document_type LIKE 'DOCUMENT.%' THEN 0 ELSE 1 END,
                       CASE WHEN status = 'PROCESSED' THEN 0 ELSE 1 END,
                       updated_at DESC
                """,
                refs,
            ).fetchone()
            if not doc:
                return

            doc_id = doc["id"]
            payload_linha = con.execute(
                """
                SELECT TOP 1 payload
                  FROM document_extractions
                 WHERE CONVERT(varchar(64), document_id) = ?
                 ORDER BY received_at DESC
                """,
                (doc_id,),
            ).fetchone()
            paginas = con.execute(
                """
                SELECT number, legibility_score, legible, text
                  FROM document_pages
                 WHERE CONVERT(varchar(64), document_id) = ?
                 ORDER BY number
                """,
                (doc_id,),
            ).fetchall()
    except Exception:
        return

    extracao = registro.get("extracao")
    if not isinstance(extracao, dict):
        extracao = {}
        registro["extracao"] = extracao

    if payload_linha and payload_linha["payload"]:
        try:
            payload = json.loads(payload_linha["payload"])
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            if payload.get("campos") and not extracao.get("campos"):
                extracao["campos"] = payload["campos"]
            if payload.get("texto_linhas") and not extracao.get("texto_linhas"):
                extracao["texto_linhas"] = payload["texto_linhas"]
            if payload.get("texto_completo") and not extracao.get("texto_completo"):
                extracao["texto_completo"] = payload["texto_completo"]
            if payload.get("validacao"):
                validacao = extracao.get("validacao") if isinstance(extracao.get("validacao"), dict) else {}
                validacao.update({k: v for k, v in payload["validacao"].items() if v is not None})
                extracao["validacao"] = validacao

    tipo_agente = _tipo_do_agente(doc["document_type"]) or _tipo_do_agente(doc["detected_type"])
    if tipo_agente:
        codigo, descricao = tipo_agente
        tipo = extracao.get("tipo") if isinstance(extracao.get("tipo"), dict) else {}
        if tipo.get("codigo") in (None, "", "desconhecido"):
            tipo["codigo"] = codigo
            tipo["descricao"] = descricao
        if tipo.get("detectado") in (None, "", "desconhecido"):
            tipo["detectado"] = codigo
            tipo["descricao_detectado"] = descricao
        extracao["tipo"] = tipo

    if doc["verdict"]:
        validacao = extracao.get("validacao") if isinstance(extracao.get("validacao"), dict) else {}
        validacao.setdefault("veredito", doc["verdict"])
        extracao["validacao"] = validacao
    if doc["processed_at"] and not extracao.get("processado_em"):
        extracao["processado_em"] = doc["processed_at"]

    textos = [str(p["text"] or "").strip() for p in paginas if str(p["text"] or "").strip()]
    if textos and not extracao.get("texto_completo"):
        extracao["texto_completo"] = "\n".join(textos)
    if textos and not extracao.get("texto_linhas"):
        extracao["texto_linhas"] = [
            {"texto": texto, "confianca": 0}
            for texto in textos
        ]

    scores = [p["legibility_score"] for p in paginas if p["legibility_score"] is not None]
    if scores:
        validacao = extracao.get("validacao") if isinstance(extracao.get("validacao"), dict) else {}
        validacao.setdefault("score_legibilidade", max(scores))
        extracao["validacao"] = validacao


# ---------------------------------------------------------------- entregas


def registrar_entrega_pendente(
    caso_id: str,
    item_codigo: str,
    arquivo: str,
    caminho: Path,
    itens_atendidos: list[str] | None = None,
    conteudo: bytes | None = None,
) -> dict[str, Any]:
    """Cria a entrega antes do OCR: o arquivo já está salvo, a leitura vem depois.

    É o que permite responder o upload na hora. Até `concluir_entrega`, esta
    linha não conta como documento entregue em lugar nenhum.
    """
    entrega_id = str(uuid.uuid4())
    itens = list(dict.fromkeys(itens_atendidos or [item_codigo]))
    if item_codigo not in itens:
        itens.append(item_codigo)
    if conteudo is None:
        conteudo = caminho.read_bytes()
    checksum = _sha256(conteudo)

    with conectar() as con:
        con.execute(
            """
            INSERT INTO entregas (id, caso_id, item_codigo, arquivo, caminho, conteudo,
                                  conteudo_sha256, tipo_detectado,
                                  tipo_confere, veredito, dados_utilizaveis, confirmado_manual,
                                  score_legibilidade, itens_atendidos, extracao_json,
                                  status_proc, criado_em)
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, 0, 0, NULL, ?, NULL, 'na_fila', ?)
            """,
            (
                entrega_id,
                caso_id,
                item_codigo,
                arquivo,
                str(caminho),
                conteudo,
                checksum,
                json.dumps(itens),
                agora(),
            ),
        )
        _tocar_caso(con, caso_id)

    return obter_entrega(entrega_id) or {}


def marcar_entrega_processando(entrega_id: str) -> None:
    """Diferencia espera no broker de uma leitura que realmente começou."""
    with conectar() as con:
        con.execute(
            "UPDATE entregas SET status_proc = 'processando', erro_proc = NULL WHERE id = ?",
            (entrega_id,),
        )


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


def entregas_travadas(minutos: int) -> list[dict[str, Any]]:
    """Entregas paradas há tempo demais em `na_fila` ou `processando`.

    Quem lê o documento é outro processo (`ocr@`, em `app/tasks/ocr.py`). Se ele
    morre — ou se a mensagem se perde numa reinicialização do Redis —, a entrega
    fica exatamente no estado em que estava e ninguém volta para ela: o arquivo
    aparece como recebido, o item do checklist fica "Lendo" e não sai mais dali.
    Foi o que aconteceu: o worker de OCR caiu com o resto do sistema no ar, e
    todo upload seguinte parou em "aguardando a vez na fila de leitura".

    Nada aqui decide o que fazer com a entrega — só a encontra. Vem com a
    categoria do caso porque quem reenfileira precisa dela para remontar os
    argumentos de `processar_entrega`.
    """
    limite = (datetime.now(timezone.utc) - timedelta(minutes=minutos)).isoformat(
        timespec="seconds"
    )
    with conectar() as con:
        linhas = con.execute(
            """
            SELECT e.id, e.caso_id, e.item_codigo, e.arquivo, e.caminho,
                   e.itens_atendidos, e.status_proc, e.criado_em, c.categoria
              FROM entregas e
              JOIN casos c ON c.id = e.caso_id
             WHERE e.status_proc IN ('na_fila', 'processando')
               AND e.criado_em < ?
             ORDER BY e.criado_em
            """,
            (limite,),
        ).fetchall()

    return [
        {
            "id": l["id"],
            "caso_id": l["caso_id"],
            "item_codigo": l["item_codigo"],
            "arquivo": l["arquivo"],
            "caminho": l["caminho"],
            "categoria": l["categoria"],
            "status_proc": l["status_proc"],
            "criado_em": l["criado_em"],
            "itens_atendidos": json.loads(l["itens_atendidos"] or "[]"),
        }
        for l in linhas
    ]


def registrar_entrega(
    caso_id: str,
    item_codigo: str,
    arquivo: str,
    caminho: Path,
    extracao: dict[str, Any],
    tipo_confere: bool | None,
    itens_atendidos: list[str] | None = None,
    conteudo: bytes | None = None,
) -> dict[str, Any]:
    entrega_id = str(uuid.uuid4())
    validacao = extracao.get("validacao", {})

    itens = list(dict.fromkeys(itens_atendidos or [item_codigo]))
    if item_codigo not in itens:
        itens.insert(0, item_codigo)

    # O que o classificador leu sozinho — não o tipo que a extração usou, que pode
    # ter sido forçado pelo item do checklist. É este que denuncia a troca.
    tipo_detectado = extracao.get("tipo", {}).get("detectado") or extracao.get("tipo", {}).get("codigo")
    tipo_confere_db = None if tipo_confere is None else int(tipo_confere)
    veredito = validacao.get("veredito")
    dados_utilizaveis = int(bool(validacao.get("dados_utilizaveis")))
    score_legibilidade = validacao.get("score_legibilidade")
    itens_json = json.dumps(itens)
    extracao_json = json.dumps(extracao, ensure_ascii=False)
    criado_em = agora()

    with conectar() as con:
        con.execute(
            """
            INSERT INTO entregas (id, caso_id, item_codigo, arquivo, caminho, conteudo,
                                  conteudo_sha256, tipo_detectado,
                                  tipo_confere, veredito, dados_utilizaveis, confirmado_manual,
                                  score_legibilidade, itens_atendidos, extracao_json, criado_em)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
            """,
            (
                entrega_id, caso_id, item_codigo, arquivo, str(caminho),
                conteudo, _sha256(conteudo), tipo_detectado,
                tipo_confere_db, veredito, dados_utilizaveis,
                score_legibilidade, itens_json, extracao_json, criado_em,
            ),
        )
        _tocar_caso(con, caso_id)

    return {
        "id": entrega_id,
        "caso_id": caso_id,
        "item_codigo": item_codigo,
        "arquivo": arquivo,
        "caminho": str(caminho),
        "tipo_detectado": tipo_detectado,
        "tipo_confere": tipo_confere,
        "veredito": veredito,
        "dados_utilizaveis": bool(dados_utilizaveis),
        "confirmado_manual": False,
        "score_legibilidade": score_legibilidade,
        "itens_atendidos": itens,
        "criado_em": criado_em,
    }


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


def marcos_por_caso(caso_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Entregas, entrevistas, assinaturas e vínculo de vários casos, em quatro consultas.

    O painel mede as etapas de cada caso anterior da categoria para ter uma mediana de
    referência. Lendo caso a caso, isso eram seis idas ao banco por caso da amostra —
    trezentas e sessenta viagens de rede para calcular cinco medianas. Aqui a amostra
    inteira sai em quatro consultas, e o agrupamento é feito em memória.

    Devolve uma entrada por caso pedido, inclusive para o caso sem nada — quem chama
    precisa distinguir "não tem entrega" de "não perguntei por ele".
    """
    reunido: dict[str, dict[str, Any]] = {
        caso_id: {"entregas": [], "entrevistas": [], "assinaturas": [], "vinculo": None}
        for caso_id in caso_ids
    }
    if not caso_ids:
        return reunido

    # `IN` com lista variável: o pyodbc não expande sequência num parâmetro só, então
    # os marcadores são montados aqui — a partir da contagem, nunca do conteúdo.
    marcadores = ",".join("?" for _ in caso_ids)

    with conectar() as con:
        for linha in con.execute(
            f"""
            SELECT id, caso_id, item_codigo, arquivo, tipo_detectado, tipo_confere,
                   veredito, dados_utilizaveis, confirmado_manual, score_legibilidade,
                   itens_atendidos, status_proc, erro_proc, criado_em
              FROM entregas
             WHERE caso_id IN ({marcadores})
             ORDER BY criado_em
            """,
            caso_ids,
        ).fetchall():
            reunido[linha["caso_id"]]["entregas"].append(_normalizar_entrega(linha))

        for linha in con.execute(
            f"""
            SELECT id, caso_id, arquivo, realizada_em, entrevistador, fatos_gerados,
                   enviada_em, avaliacao_google_em, gravacao_id, criado_em
              FROM entrevistas
             WHERE caso_id IN ({marcadores})
             ORDER BY criado_em DESC
            """,
            caso_ids,
        ).fetchall():
            reunido[linha["caso_id"]]["entrevistas"].append(_normalizar_entrevista(linha))

        for linha in con.execute(
            f"SELECT * FROM assinaturas WHERE caso_id IN ({marcadores}) ORDER BY criado_em DESC",
            caso_ids,
        ).fetchall():
            reunido[linha["caso_id"]]["assinaturas"].append(_normalizar_assinatura(linha))

        for linha in con.execute(
            f"SELECT * FROM vinculos_agente WHERE caso_id IN ({marcadores})",
            caso_ids,
        ).fetchall():
            reunido[linha["caso_id"]]["vinculo"] = _normalizar_vinculo(linha)

    return reunido


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
    registro.pop("conteudo", None)
    registro.pop("extracao_json", None)
    return registro


def obter_entrega(entrega_id: str) -> dict[str, Any] | None:
    with conectar() as con:
        linha = con.execute(
            """
            SELECT id, caso_id, item_codigo, arquivo, caminho, conteudo_sha256,
                   tipo_detectado, tipo_confere, veredito, dados_utilizaveis,
                   confirmado_manual, score_legibilidade, itens_atendidos,
                   extracao_json, criado_em, status_proc, erro_proc
              FROM entregas WHERE id = ?
            """,
            (entrega_id,),
        ).fetchone()
    if not linha:
        return None
    registro = _normalizar_entrega(linha)
    if registro.get("extracao_json"):
        registro["extracao"] = json.loads(registro.pop("extracao_json"))
    _enriquecer_extracao_do_agente(registro)
    registro["extracao"] = _completar_extracao(registro)
    return registro


def caminho_duravel_da_entrega(entrega_id: str) -> Path | None:
    """Localiza o anexo e restaura o cache local a partir do SQL Server quando preciso.

    O checksum é conferido antes e depois. Um binário corrompido jamais é servido com
    os campos extraídos de outro conteúdo.
    """
    with conectar() as con:
        linha = con.execute(
            "SELECT caso_id, caminho, conteudo, conteudo_sha256 FROM entregas WHERE id = ?",
            (entrega_id,),
        ).fetchone()
    if linha is None:
        return None

    original = Path(str(linha["caminho"]))
    nome_fisico = original.name
    destino = (DIR_ARQUIVOS / str(linha["caso_id"]) / nome_fisico).resolve()
    raiz = DIR_ARQUIVOS.resolve()
    if raiz not in destino.parents:
        return None

    esperado = str(linha.get("conteudo_sha256") or "").lower()

    def valido(caminho: Path) -> bool:
        if not caminho.is_file():
            return False
        if not esperado:
            return True
        return hashlib.sha256(caminho.read_bytes()).hexdigest() == esperado

    # Caminhos antigos fora da raiz não são servidos diretamente, mas podem ser
    # recuperados para a localização canônica se ainda existirem após uma mudança.
    if valido(destino):
        return destino
    if valido(original):
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(original.read_bytes())
        return destino

    conteudo = linha.get("conteudo")
    if conteudo is None:
        return None
    bytes_duraveis = bytes(conteudo)
    if esperado and hashlib.sha256(bytes_duraveis).hexdigest() != esperado:
        log.error("anexo %s corrompido no armazenamento durável", entrega_id)
        return None

    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_suffix(destino.suffix + ".restaurando")
    parcial.write_bytes(bytes_duraveis)
    parcial.replace(destino)
    return destino


def excluir_entrega(entrega_id: str) -> bool:
    with conectar() as con:
        linha = con.execute(
            "SELECT caso_id, caminho FROM entregas WHERE id = ?", (entrega_id,)
        ).fetchone()
        if not linha:
            return False
        con.execute("DELETE FROM entregas WHERE id = ?", (entrega_id,))
        _tocar_caso(con, linha["caso_id"])

    caminho = caminho_arquivo_entrega(dict(linha))
    if caminho is not None:
        caminho.unlink(missing_ok=True)
    return True


# ------------------------------------------------------------- assinaturas


def _normalizar_assinatura(linha: banco.Linha) -> dict[str, Any]:
    registro = dict(linha)
    bruto = registro.get("signatarios")
    if isinstance(bruto, str):
        try:
            registro["signatarios"] = json.loads(bruto)
        except json.JSONDecodeError:
            registro["signatarios"] = []
    registro["signatarios"] = registro.get("signatarios") or []

    signatarios = registro["signatarios"]
    registro["assinaram"] = sum(1 for s in signatarios if s.get("estado") == "assinou")
    registro["total"] = len(signatarios)
    registro["faltam"] = [
        s.get("nome", "")
        for s in signatarios
        if s.get("estado") not in ("assinou", "recusou", "cancelado")
    ]
    # O caminho é de disco e não interessa ao navegador; o que ele precisa saber
    # é se já existe cópia baixada.
    registro["arquivo_local"] = bool(registro.pop("arquivo", None))
    return registro


def registrar_assinatura(
    doc_token: str,
    nome: str,
    cliente: str,
    signatarios: list[dict[str, Any]],
    cpf: str = "",
    estado: str = "pendente",
    caso_id: str | None = None,
) -> dict[str, Any]:
    """Guarda o contrato recém-enviado para assinatura.

    `doc_token` é único: reenviar o mesmo documento cria outro token do lado da
    ZapSign, então colisão aqui significaria registro duplicado do mesmo envio.
    """
    assinatura_id = str(uuid.uuid4())
    instante = agora()
    with conectar() as con:
        con.execute(
            """
            INSERT INTO assinaturas (id, doc_token, nome, cliente, cpf, caso_id, estado,
                                     signatarios, arquivo, criado_em, atualizado_em)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
            """,
            (
                assinatura_id,
                doc_token,
                nome.strip(),
                _normalizar_nome_cliente(cliente),
                _normalizar_cpf(cpf),
                caso_id,
                estado,
                json.dumps(signatarios, ensure_ascii=False),
                instante,
                instante,
            ),
        )
    return obter_assinatura(assinatura_id) or {}


def atualizar_assinatura(
    assinatura_id: str, estado: str, signatarios: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Grava o que a última consulta à ZapSign devolveu."""
    with conectar() as con:
        con.execute(
            """
            UPDATE assinaturas
               SET estado = ?, signatarios = ?, atualizado_em = ?
             WHERE id = ?
            """,
            (estado, json.dumps(signatarios, ensure_ascii=False), agora(), assinatura_id),
        )
    return obter_assinatura(assinatura_id)


def definir_arquivo_assinatura(assinatura_id: str, caminho: Path) -> None:
    with conectar() as con:
        con.execute(
            "UPDATE assinaturas SET arquivo = ?, atualizado_em = ? WHERE id = ?",
            (str(caminho), agora(), assinatura_id),
        )


def vincular_assinatura_ao_caso(assinatura_id: str, caso_id: str) -> bool:
    with conectar() as con:
        cur = con.execute(
            "UPDATE assinaturas SET caso_id = ?, atualizado_em = ? WHERE id = ?",
            (caso_id, agora(), assinatura_id),
        )
    return cur.rowcount > 0


def listar_assinaturas(
    caso_id: str | None = None,
    cliente: str | None = None,
    cpf: str | None = None,
) -> list[dict[str, Any]]:
    """Do mais novo para o mais antigo, opcionalmente filtrado.

    O painel combina nome normalizado e CPF canônico para retomar o documento
    depois de um F5. Nome sozinho não identifica: dois clientes podem ser homônimos.
    """
    condicoes, parametros = [], []
    if caso_id:
        condicoes.append("caso_id = ?")
        parametros.append(caso_id)
    if cliente:
        # O SQLite aceitava uma função Python registrada na conexão; o SQL Server não
        # roda Python dentro da consulta. Como o nome já é gravado normalizado, comparar
        # direto basta — e o collation do banco (`Latin1_General_CI_AS`) ignora
        # maiúsculas, o que dispensa o antigo `COLLATE NOCASE`.
        condicoes.append("cliente = ?")
        parametros.append(_normalizar_nome_cliente(cliente))
    if cpf:
        condicoes.append("cpf = ?")
        parametros.append(_normalizar_cpf(cpf))

    consulta = "SELECT * FROM assinaturas"
    if condicoes:
        consulta += " WHERE " + " AND ".join(condicoes)
    consulta += " ORDER BY criado_em DESC"

    with conectar() as con:
        linhas = con.execute(consulta, parametros).fetchall()
    return [_normalizar_assinatura(l) for l in linhas]


def obter_assinatura(assinatura_id: str) -> dict[str, Any] | None:
    with conectar() as con:
        linha = con.execute(
            "SELECT * FROM assinaturas WHERE id = ?", (assinatura_id,)
        ).fetchone()
    return _normalizar_assinatura(linha) if linha else None


# --------------------------------------------------------- agente jurídico


def vincular_agente(caso_id: str, caso_ref: str, cliente_ref: str) -> dict[str, Any]:
    """Guarda (ou atualiza) o caso correspondente no agente.

    `MERGE` e não `INSERT`: revincular é operação legítima — o agente
    pode ter sido recriado do zero em desenvolvimento —, e falhar aqui deixaria o
    caso preso a um identificador que não existe mais do outro lado.
    """
    instante = agora()
    with conectar() as con:
        anterior = con.execute(
            "SELECT caso_ref, enviados, criado_em FROM vinculos_agente WHERE caso_id = ?",
            (caso_id,),
        ).fetchone()
        # Trocar de caso no agente zera a lista de entregas enviadas: o outro lado
        # não conhece nenhuma delas, e manter a lista faria o sistema achar que já
        # mandou o que nunca chegou lá.
        trocou = bool(anterior) and anterior["caso_ref"] != caso_ref
        enviados = anterior["enviados"] if anterior and not trocou else "[]"
        if trocou:
            # Pela mesma razão, a entrevista volta a contar como não enviada. Ela é a
            # origem dos fatos que o cliente relatou — sem isto, o caso recriado herda os
            # documentos e perde justamente o que o advogado ouviu no atendimento.
            con.execute(
                "UPDATE dbo.acervo_entrevistas SET enviada_em = NULL WHERE caso_id = ?",
                (caso_id,),
            )
        con.execute(
            """
            MERGE dbo.acervo_vinculos_agente AS alvo
            USING (SELECT ? AS caso_id, ? AS caso_ref, ? AS cliente_ref, ? AS enviados,
                          ? AS criado_em, ? AS atualizado_em) AS origem
               ON alvo.caso_id = origem.caso_id
             WHEN MATCHED THEN UPDATE SET caso_ref = origem.caso_ref,
                                          cliente_ref = origem.cliente_ref,
                                          enviados = origem.enviados,
                                          ultimo_erro = NULL,
                                          atualizado_em = origem.atualizado_em
             WHEN NOT MATCHED THEN
                  INSERT (caso_id, caso_ref, cliente_ref, enviados, ultimo_erro,
                          criado_em, atualizado_em)
                  VALUES (origem.caso_id, origem.caso_ref, origem.cliente_ref,
                          origem.enviados, NULL, origem.criado_em, origem.atualizado_em);
            """,
            (
                caso_id,
                caso_ref,
                cliente_ref,
                enviados,
                anterior["criado_em"] if anterior else instante,
                instante,
            ),
        )
    return obter_vinculo_agente(caso_id) or {}


def _normalizar_vinculo(linha: Any) -> dict[str, Any]:
    registro = dict(linha)
    bruto = registro.get("enviados")
    try:
        registro["enviados"] = json.loads(bruto) if isinstance(bruto, str) else []
    except json.JSONDecodeError:
        registro["enviados"] = []
    return registro


def obter_vinculo_agente(caso_id: str) -> dict[str, Any] | None:
    with conectar() as con:
        linha = con.execute(
            "SELECT * FROM vinculos_agente WHERE caso_id = ?", (caso_id,)
        ).fetchone()
    return _normalizar_vinculo(linha) if linha else None


def marcar_entrega_enviada(caso_id: str, entrega_id: str) -> None:
    """Registra que esta entrega já foi entregue ao agente.

    O agente também é idempotente pelo `external_event_id`, então isto não é a
    garantia — é a economia: sem a lista, cada abertura do dossiê reenviaria todos
    os documentos do caso.
    """
    vinculo = obter_vinculo_agente(caso_id)
    if vinculo is None:
        return
    enviados = list(dict.fromkeys([*vinculo["enviados"], entrega_id]))
    with conectar() as con:
        con.execute(
            "UPDATE vinculos_agente SET enviados = ?, ultimo_erro = NULL, atualizado_em = ?"
            " WHERE caso_id = ?",
            (json.dumps(enviados), agora(), caso_id),
        )


def registrar_erro_agente(caso_id: str, mensagem: str | None) -> None:
    with conectar() as con:
        con.execute(
            "UPDATE vinculos_agente SET ultimo_erro = ?, atualizado_em = ? WHERE caso_id = ?",
            (mensagem[:500] if mensagem else None, agora(), caso_id),
        )


# ------------------------------------------------------------------ entrevistas


def _normalizar_entrevista(linha: banco.Linha) -> dict[str, Any]:
    registro = dict(linha)
    bruto = registro.get("perguntas")
    try:
        registro["perguntas"] = json.loads(bruto) if isinstance(bruto, str) else []
    except json.JSONDecodeError:
        registro["perguntas"] = []
    registro["enviada"] = bool(registro.get("enviada_em"))
    # Coluna nova (ver `COLUNAS_NOVAS` em `app/banco.py`): entrevista gravada antes
    # dela volta sem a chave, e `.get` a trata como não marcada — que é o certo. O
    # booleano é o que a tela lê; a data fica para quem quiser auditar quando foi.
    registro["avaliacao_google"] = bool(registro.get("avaliacao_google_em"))
    # Idem: coluna nova. Preenchida só na entrevista gravada ao vivo — a que foi
    # anexada como arquivo não tem gravação a que se ligar.
    registro["gravacao_id"] = registro.get("gravacao_id") or ""
    return registro


def registrar_entrevista(
    caso_id: str,
    *,
    arquivo: str,
    caminho: Path,
    texto: str,
    realizada_em: str = "",
    entrevistador: str = "",
    gravacao_id: str = "",
) -> dict[str, Any]:
    """Guarda a entrevista do atendimento: o arquivo original e o texto lido dele.

    `gravacao_id` só vem da entrevista conduzida ao vivo pelo roteiro — é a chave
    pela qual ela se reconhece entre duas gravações do mesmo atendimento. A
    entrevista anexada como arquivo não tem gravação, e vai com o campo vazio.
    """
    identificador = uuid.uuid4().hex
    with conectar() as con:
        con.execute(
            """
            INSERT INTO entrevistas
                   (id, caso_id, arquivo, caminho, texto, realizada_em, entrevistador,
                    resumo, perguntas, fatos_gerados, enviada_em, gravacao_id, criado_em)
            VALUES (?, ?, ?, ?, ?, ?, ?, '', '[]', 0, NULL, ?, ?)
            """,
            (
                identificador,
                caso_id,
                arquivo,
                str(caminho),
                texto,
                realizada_em,
                entrevistador,
                gravacao_id,
                agora(),
            ),
        )
        _tocar_caso(con, caso_id)
    return obter_entrevista(identificador) or {}


def obter_entrevista_por_gravacao(gravacao_id: str) -> dict[str, Any] | None:
    """A entrevista de uma gravação, se ela já foi registrada.

    É o que torna a rota do atendimento ao vivo repetível. Ela é chamada duas vezes
    por atendimento — ao criar o caso e ao encerrar — e pode ser chamada mais vezes
    se o atendente voltar ao roteiro. Sem esta busca, cada chamada inseriria outra
    linha, e a supervisão contaria três entrevistas onde houve uma.
    """
    if not gravacao_id:
        return None
    with conectar() as con:
        linha = con.execute(
            "SELECT * FROM entrevistas WHERE gravacao_id = ?", (gravacao_id,)
        ).fetchone()
    return _normalizar_entrevista(linha) if linha else None


def atualizar_transcricao(entrevista_id: str, texto: str, realizada_em: str = "") -> bool:
    """Regrava a transcrição de uma entrevista já registrada.

    O atendimento ao vivo continua depois de o caso nascer — a avaliação no Google,
    os documentos e o encerramento acontecem com a gravação correndo, e é justamente
    ali que a atendente lê o fechamento do roteiro. Gravar a transcrição só uma vez,
    no meio, deixaria a supervisão auditando uma conversa que termina antes do fim.
    """
    with conectar() as con:
        cur = con.execute(
            "UPDATE entrevistas SET texto = ?, realizada_em = ? WHERE id = ?",
            (texto, realizada_em, entrevista_id),
        )
    return cur.rowcount > 0


def listar_entrevistas(caso_id: str) -> list[dict[str, Any]]:
    with conectar() as con:
        linhas = con.execute(
            "SELECT * FROM entrevistas WHERE caso_id = ? ORDER BY criado_em DESC",
            (caso_id,),
        ).fetchall()
    return [_normalizar_entrevista(linha) for linha in linhas]


def listar_todas_entrevistas() -> list[dict[str, Any]]:
    """Todas as entrevistas, de todos os casos — a visão da supervisão.

    Separada da `listar_entrevistas` de propósito: aquela é por caso e é a que
    todo advogado usa; esta atravessa o escritório inteiro e só a supervisão
    chama (ver `app/supervisao.py`).
    """
    with conectar() as con:
        linhas = con.execute(
            "SELECT * FROM entrevistas ORDER BY criado_em DESC"
        ).fetchall()
    return [_normalizar_entrevista(linha) for linha in linhas]


def listar_resumo_supervisao() -> list[dict[str, Any]]:
    """Lista gerencial sem transportar as transcrições inteiras pelo banco.

    `LEN` calcula o tamanho no SQL Server e o JOIN traz o cliente na mesma viagem.
    O texto completo só é lido quando alguém abre uma entrevista específica.
    """
    with conectar() as con:
        linhas = con.execute(
            """
            SELECT e.id, e.caso_id, c.cliente, e.arquivo, e.realizada_em,
                   e.entrevistador, e.fatos_gerados, e.enviada_em,
                   e.avaliacao_google_em, e.gravacao_id, e.criado_em,
                   LEN(e.texto) AS caracteres
              FROM entrevistas e
              JOIN casos c ON c.id = e.caso_id
             ORDER BY e.criado_em DESC
            """
        ).fetchall()
    return [_normalizar_entrevista(linha) for linha in linhas]


def obter_entrevista(entrevista_id: str) -> dict[str, Any] | None:
    with conectar() as con:
        linha = con.execute(
            "SELECT * FROM entrevistas WHERE id = ?", (entrevista_id,)
        ).fetchone()
    return _normalizar_entrevista(linha) if linha else None


def marcar_entrevista_lida(
    entrevista_id: str,
    *,
    resumo: str,
    perguntas: list[str],
    fatos_gerados: int,
) -> None:
    """Registra o que o agente entendeu da entrevista, e que ela já foi lida.

    Guardar o resumo aqui — e não só do lado do agente — é o que faz o dossiê continuar
    explicando a entrevista quando o agente está fora do ar.
    """
    with conectar() as con:
        con.execute(
            "UPDATE entrevistas SET resumo = ?, perguntas = ?, fatos_gerados = ?,"
            " enviada_em = ? WHERE id = ?",
            (resumo[:4000], json.dumps(perguntas[:15]), fatos_gerados, agora(), entrevista_id),
        )


def marcar_avaliacao_google(entrevista_id: str, concluida: bool) -> bool:
    """Registra que o cliente avaliou o escritório no Google, ou desfaz a marcação.

    Quem marca é o atendente, com o cliente ainda na videoconferência — é o que o
    `FECHAMENTO` do roteiro manda (ver `app/roteiros.py`). Guardar a HORA e não um
    booleano é de graça e responde a pergunta seguinte da supervisão: se a marcação
    saiu junto do atendimento ou dias depois, de memória.

    Desmarcar apaga a data em vez de guardar "false". Uma marcação feita por engano
    não deve deixar rastro de que a avaliação aconteceu.
    """
    with conectar() as con:
        cur = con.execute(
            "UPDATE entrevistas SET avaliacao_google_em = ? WHERE id = ?",
            (agora() if concluida else None, entrevista_id),
        )
    return cur.rowcount > 0


def excluir_entrevista(entrevista_id: str) -> bool:
    """Tira a entrevista do caso, junto com o arquivo.

    Os fatos que ela gerou **continuam** no agente: apagar o registro do atendimento não
    apaga o que o cliente disse, e um fato órfão de origem é pior que um arquivo a menos.
    """
    with conectar() as con:
        linha = con.execute(
            "SELECT caminho FROM entrevistas WHERE id = ?", (entrevista_id,)
        ).fetchone()
        if not linha:
            return False
        con.execute("DELETE FROM entrevistas WHERE id = ?", (entrevista_id,))
    caminho = Path(linha["caminho"])
    if caminho.exists():
        caminho.unlink(missing_ok=True)
    return True


def caminho_do_assinado(assinatura_id: str) -> Path | None:
    """O PDF assinado guardado em disco, se já foi baixado uma vez."""
    with conectar() as con:
        linha = con.execute(
            "SELECT arquivo FROM assinaturas WHERE id = ?", (assinatura_id,)
        ).fetchone()
    if not linha or not linha["arquivo"]:
        return None
    caminho = Path(linha["arquivo"])
    return caminho if caminho.exists() else None


def token_da_assinatura(assinatura_id: str) -> str | None:
    with conectar() as con:
        linha = con.execute(
            "SELECT doc_token FROM assinaturas WHERE id = ?", (assinatura_id,)
        ).fetchone()
    return linha["doc_token"] if linha else None


def excluir_assinatura(assinatura_id: str) -> bool:
    """Tira o contrato da lista local. O documento na ZapSign continua lá.

    De propósito: o contrato assinado é prova, e o painel deles é o registro com
    trilha de auditoria. Apagar daqui só limpa o índice do escritório.
    """
    with conectar() as con:
        linha = con.execute(
            "SELECT arquivo FROM assinaturas WHERE id = ?", (assinatura_id,)
        ).fetchone()
        if not linha:
            return False
        con.execute("DELETE FROM assinaturas WHERE id = ?", (assinatura_id,))

    if linha["arquivo"]:
        Path(linha["arquivo"]).unlink(missing_ok=True)
    return True


# ------------------------------------------------------- catálogo de roteiros
#
# O roteiro do `app/roteiros.py` é código: veio de um `.docx` transcrito à mão.
# Estes aqui vieram de um arquivo que alguém anexou, ou da tela de edição durante
# um atendimento. Guardar o roteiro inteiro como JSON numa coluna, e não em
# tabelas de bloco e pergunta, é deliberado: ninguém consulta "todas as perguntas
# do tipo data do escritório" — o roteiro é sempre lido e salvo por inteiro, e
# normalizá-lo custaria três tabelas e um JOIN para nunca ser usado.


def _normalizar_roteiro(linha: banco.Linha) -> dict[str, Any]:
    registro = dict(linha)
    bruto = registro.get("corpo")
    try:
        registro["conteudo"] = json.loads(bruto) if isinstance(bruto, str) else {}
    except json.JSONDecodeError:
        registro["conteudo"] = {}
    registro.pop("corpo", None)
    return registro


def salvar_roteiro(
    codigo: str,
    *,
    nome: str,
    descricao: str,
    conteudo: dict[str, Any],
    origem: str = "",
    criado_por: str = "",
) -> dict[str, Any]:
    """Grava (ou regrava) um roteiro do catálogo. Idempotente pelo código.

    `criado_por` guarda quem salvou. Não é enfeite de auditoria: um roteiro
    salvo no catálogo passa a reger os atendimentos de todo o escritório, e
    quando um aparecer estranho na segunda-feira alguém precisa saber com quem
    conversar. `UPDATE` não o toca — quem criou continua sendo quem criou.
    """
    instante = agora()
    corpo = json.dumps(conteudo, ensure_ascii=False)
    with conectar() as con:
        atualizadas = con.execute(
            """
            UPDATE roteiros
               SET nome = ?, descricao = ?, corpo = ?, origem = ?, atualizado_em = ?
             WHERE codigo = ?
            """,
            (nome, descricao, corpo, origem, instante, codigo),
        ).rowcount
        if not atualizadas:
            con.execute(
                """
                INSERT INTO roteiros
                       (codigo, nome, descricao, corpo, criado_por, origem,
                        criado_em, atualizado_em)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (codigo, nome, descricao, corpo, criado_por, origem, instante, instante),
            )
    return obter_roteiro(codigo) or {}


def listar_roteiros() -> list[dict[str, Any]]:
    with conectar() as con:
        linhas = con.execute("SELECT * FROM roteiros ORDER BY criado_em").fetchall()
    return [_normalizar_roteiro(linha) for linha in linhas]


def obter_roteiro(codigo: str) -> dict[str, Any] | None:
    with conectar() as con:
        linha = con.execute("SELECT * FROM roteiros WHERE codigo = ?", (codigo,)).fetchone()
    return _normalizar_roteiro(linha) if linha else None


def excluir_roteiro(codigo: str) -> bool:
    """Tira o roteiro do catálogo.

    Quando o código é o de um roteiro escrito em `app/roteiros.py`, isto não
    apaga nada de verdade: desfaz a edição e devolve o roteiro do módulo. É a
    saída de emergência de uma edição malfeita no meio do expediente.
    """
    with conectar() as con:
        return bool(con.execute("DELETE FROM roteiros WHERE codigo = ?", (codigo,)).rowcount)
