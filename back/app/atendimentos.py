"""O atendimento como fonte única da verdade: do agendamento à documentação.

POR QUE EXISTE

Antes, o "estado" de uma entrevista estava espalhado: o React sabia se a chamada
estava aberta, a fila da documentação guardava `entrevista/solicitado/assumido`
sem nunca encerrar, e o caso só nascia depois do contrato. Cada tela deduzia a
etapa por conta própria, e o resultado mais visível eram alertas de chamadas que
já tinham acabado.

Aqui cada atendimento — agendado ou avulso — tem um `estado` gravado, e só muda
por `transicionar`, que é um UPDATE condicional (`WHERE estado IN (...)`): duas
abas, dois usuários ou a API e o worker disputando a mesma mudança nunca levam o
atendimento a dois lugares. Cada mudança vira uma linha em `atendimento_eventos`.

    AGENDADA ─► CLIENTE_AGUARDANDO ─► EM_ATENDIMENTO ─► ENTREVISTA_FINALIZADA
       │                                                     │
       ├─► CLIENTE_FALTOU                         ANALISE_JURIDICA
       └─► CANCELADA                                         │
                                          AGUARDANDO_CONFIRMACAO_ACOES
                                                             │ (cria os casos)
                       CONCLUIDA ◄─ DOCUMENTACAO_PENDENTE ◄─ AVALIACAO_ESCRITORIO ◄─ QUALIFICACAO

A PRESENÇA NA SALA

O Jitsi não avisa o servidor de quem entrou. Quem avisa é o navegador: a página
do cliente chama a rota pública de presença ao entrar e a cada 30 s; a tela do
escritório faz o mesmo, autenticada. Sem batida por `PRESENCA_VALIDA_S`, a pessoa
é considerada fora da sala — é isso que impede um alerta de sobreviver a uma aba
fechada.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from . import banco, chamada
from .banco import PREFIXO, SCHEMA
from .esquema_portavel import Coluna, Tabela, criar as criar_tabelas

log = logging.getLogger("atendimentos")

TABELA = f"{SCHEMA}.{PREFIXO}atendimentos"
TABELA_EVENTOS = f"{SCHEMA}.{PREFIXO}atendimento_eventos"
TABELA_CONFIG = f"{SCHEMA}.{PREFIXO}config_atendimento"

AGENDADA = "AGENDADA"
CLIENTE_AGUARDANDO = "CLIENTE_AGUARDANDO"
EM_ATENDIMENTO = "EM_ATENDIMENTO"
ENTREVISTA_FINALIZADA = "ENTREVISTA_FINALIZADA"
ANALISE_JURIDICA = "ANALISE_JURIDICA"
AGUARDANDO_CONFIRMACAO_ACOES = "AGUARDANDO_CONFIRMACAO_ACOES"
QUALIFICACAO = "QUALIFICACAO"
AVALIACAO_ESCRITORIO = "AVALIACAO_ESCRITORIO"
DOCUMENTACAO_PENDENTE = "DOCUMENTACAO_PENDENTE"
CONCLUIDA = "CONCLUIDA"
CLIENTE_FALTOU = "CLIENTE_FALTOU"
CANCELADA = "CANCELADA"

ESTADOS = (
    AGENDADA, CLIENTE_AGUARDANDO, EM_ATENDIMENTO, ENTREVISTA_FINALIZADA,
    ANALISE_JURIDICA, AGUARDANDO_CONFIRMACAO_ACOES, QUALIFICACAO,
    AVALIACAO_ESCRITORIO, DOCUMENTACAO_PENDENTE, CONCLUIDA, CLIENTE_FALTOU, CANCELADA,
)

#: Para onde cada estado pode ir. Fora desta tabela, a transição é recusada.
TRANSICOES: dict[str, frozenset[str]] = {
    AGENDADA: frozenset({CLIENTE_AGUARDANDO, EM_ATENDIMENTO, CLIENTE_FALTOU, CANCELADA}),
    CLIENTE_AGUARDANDO: frozenset({EM_ATENDIMENTO, AGENDADA, CANCELADA}),
    CLIENTE_FALTOU: frozenset({AGENDADA, CLIENTE_AGUARDANDO, EM_ATENDIMENTO, CANCELADA}),
    EM_ATENDIMENTO: frozenset({ENTREVISTA_FINALIZADA, CANCELADA}),
    ENTREVISTA_FINALIZADA: frozenset({ANALISE_JURIDICA}),
    ANALISE_JURIDICA: frozenset({AGUARDANDO_CONFIRMACAO_ACOES}),
    AGUARDANDO_CONFIRMACAO_ACOES: frozenset({QUALIFICACAO, ANALISE_JURIDICA}),
    QUALIFICACAO: frozenset({AVALIACAO_ESCRITORIO}),
    AVALIACAO_ESCRITORIO: frozenset({DOCUMENTACAO_PENDENTE}),
    DOCUMENTACAO_PENDENTE: frozenset({CONCLUIDA}),
    CONCLUIDA: frozenset(),
    CANCELADA: frozenset(),
}

#: Estados em que ainda não houve entrevista: só eles aceitam edição da agenda.
ANTES_DA_ENTREVISTA = frozenset({AGENDADA, CLIENTE_AGUARDANDO, CLIENTE_FALTOU})
#: Estados que encerram o atendimento: a sala deixa de valer para presença.
TERMINAIS = frozenset({CONCLUIDA, CANCELADA})

#: Sem batida por este tempo, a pessoa saiu da sala (aba fechada, rede caiu).
PRESENCA_VALIDA_S = int(os.getenv("ATENDIMENTO_PRESENCA_VALIDA_S", "90"))

CONFIG_PADRAO: dict[str, Any] = {
    # Minutos de cliente sozinho na sala antes de avisar o resto da equipe.
    "escalonar_apos_min": 3,
    # Depois do horário marcado, quanto esperar antes de registrar a falta.
    "tolerancia_falta_min": 30,
    # Lembretes: a cada N dias antes da data, e minutos antes no próprio dia.
    "lembretes": {"ativo": True, "intervalo_dias": 1, "minutos_antes_no_dia": [120, 30]},
    "enviar_falta_automatico": False,
}

TABELAS = (
    Tabela(
        TABELA,
        (
            Coluna("id", "id", nula=False),
            Coluna("cliente", "curto", nula=False, padrao=""),
            Coluna("telefone", "varchar(30)", nula=False, padrao=""),
            Coluna("data_hora", "data"),
            Coluna("duracao_min", "inteiro", nula=False, padrao=60),
            Coluna("sala", "varchar(120)"),
            Coluna("link_cliente", "texto"),
            Coluna("responsavel_id", "id"),
            Coluna("responsavel_nome", "curto"),
            Coluna("atendente_id", "id"),
            Coluna("atendente_nome", "curto"),
            Coluna("entrevista_id", "id"),
            Coluna("casos_json", "longo"),
            Coluna("acoes_json", "longo"),
            Coluna("documentos_json", "longo"),
            Coluna("estado", "codigo", nula=False, padrao=AGENDADA),
            Coluna("origem", "codigo", nula=False, padrao="agenda"),
            Coluna("revisada", "inteiro", nula=False, padrao=0),
            Coluna("config_lembretes_json", "longo"),
            Coluna("observacao", "texto"),
            Coluna("cliente_entrou_em", "data"),
            Coluna("cliente_batida_em", "data"),
            Coluna("cliente_saiu_em", "data"),
            Coluna("escritorio_batida_em", "data"),
            Coluna("versao", "inteiro", nula=False, padrao=1),
            Coluna("criado_em", "data", nula=False),
            Coluna("criado_por", "curto"),
            Coluna("atualizado_em", "data", nula=False),
            Coluna("finalizado_em", "data"),
        ),
        ("id",),
        indices=(
            ("ix_acervo_atendimentos_sala", ("sala",)),
            ("ix_acervo_atendimentos_estado", ("estado", "data_hora")),
            ("ix_acervo_atendimentos_entrevista", ("entrevista_id",)),
        ),
    ),
    Tabela(
        TABELA_EVENTOS,
        (
            Coluna("id", "id", nula=False),
            Coluna("atendimento_id", "id", nula=False),
            Coluna("tipo", "codigo", nula=False),
            Coluna("de_estado", "codigo"),
            Coluna("para_estado", "codigo"),
            Coluna("usuario_id", "id"),
            Coluna("usuario_nome", "curto"),
            Coluna("detalhes", "texto"),
            Coluna("criado_em", "data", nula=False),
        ),
        ("id",),
        indices=(("ix_acervo_atend_eventos_atend", ("atendimento_id", "criado_em")),),
    ),
    Tabela(
        TABELA_CONFIG,
        (
            Coluna("chave", "codigo", nula=False),
            Coluna("valor_json", "longo", nula=False),
            Coluna("atualizado_em", "data", nula=False),
            Coluna("atualizado_por", "curto"),
        ),
        ("chave",),
    ),
)


class ErroAtendimento(ValueError):
    status = 400


class AtendimentoNaoEncontrado(ErroAtendimento):
    status = 404


class TransicaoInvalida(ErroAtendimento):
    status = 409


def inicializar() -> None:
    with banco.conectar() as con:
        criar_tabelas(con, TABELAS)


def _agora_dt() -> datetime:
    return datetime.now(timezone.utc)


def agora() -> str:
    return _agora_dt().isoformat(timespec="seconds")


def ler_data(valor: Any) -> datetime | None:
    if not valor:
        return None
    try:
        data = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except ValueError:
        return None
    return data if data.tzinfo else data.replace(tzinfo=timezone.utc)


def data_utc(valor: Any) -> str | None:
    """ISO em UTC: as datas são comparadas como texto no banco, então o fuso é um só."""
    data = ler_data(valor)
    return data.astimezone(timezone.utc).isoformat(timespec="seconds") if data else None


def _json(valor: Any, padrao: Any) -> Any:
    if not valor:
        return padrao
    try:
        return json.loads(valor)
    except (TypeError, ValueError):
        return padrao


def url_cliente(sala: str) -> str:
    base = os.getenv("URL_PORTAL", "http://localhost:3000").rstrip("/")
    return f"{base}/chamada/{sala}"


# ------------------------------------------------------------------ config


def obter_config() -> dict[str, Any]:
    with banco.conectar() as con:
        linha = con.execute(
            f"SELECT valor_json FROM {TABELA_CONFIG} WHERE chave = 'atendimento'"
        ).fetchone()
    salvo = _json(linha["valor_json"] if linha else None, {})
    config = {**CONFIG_PADRAO, **{k: v for k, v in salvo.items() if k in CONFIG_PADRAO}}
    config["lembretes"] = normalizar_lembretes(
        {**CONFIG_PADRAO["lembretes"], **(salvo.get("lembretes") or {})}
    )
    return config


def normalizar_lembretes(bruto: dict[str, Any] | None) -> dict[str, Any]:
    bruto = bruto or {}
    try:
        intervalo = int(bruto.get("intervalo_dias") or 0)
    except (TypeError, ValueError):
        intervalo = 0
    minutos: list[int] = []
    for valor in bruto.get("minutos_antes_no_dia") or []:
        try:
            m = int(valor)
        except (TypeError, ValueError):
            continue
        if 5 <= m <= 12 * 60 and m not in minutos:
            minutos.append(m)
    return {
        "ativo": bool(bruto.get("ativo", True)),
        "intervalo_dias": max(0, min(intervalo, 30)),
        "minutos_antes_no_dia": sorted(minutos, reverse=True)[:6],
    }


def salvar_config(valores: dict[str, Any], usuario: str) -> dict[str, Any]:
    atual = obter_config()
    novo = dict(atual)
    for chave in ("escalonar_apos_min", "tolerancia_falta_min"):
        if chave in valores:
            novo[chave] = max(1, min(int(valores[chave]), 240))
    if "enviar_falta_automatico" in valores:
        novo["enviar_falta_automatico"] = bool(valores["enviar_falta_automatico"])
    if "lembretes" in valores:
        novo["lembretes"] = normalizar_lembretes(valores["lembretes"])
    instante = agora()
    texto = json.dumps(novo, ensure_ascii=False)
    with banco.conectar() as con:
        alteradas = con.execute(
            f"UPDATE {TABELA_CONFIG} SET valor_json = ?, atualizado_em = ?, atualizado_por = ? "
            "WHERE chave = 'atendimento'",
            (texto, instante, usuario),
        ).rowcount
        if not alteradas:
            con.execute(
                f"INSERT INTO {TABELA_CONFIG} (chave, valor_json, atualizado_em, atualizado_por) "
                "VALUES ('atendimento', ?, ?, ?)",
                (texto, instante, usuario),
            )
    return novo


# ----------------------------------------------------------------- leitura

_CAMPOS = tuple(c.nome for c in TABELAS[0].colunas)


def _registro(linha: Any) -> dict[str, Any]:
    r = {campo: linha[campo] for campo in _CAMPOS if campo in linha}
    r["casos"] = _json(r.pop("casos_json", None), [])
    r["acoes"] = _json(r.pop("acoes_json", None), [])
    r["documentos"] = _json(r.pop("documentos_json", None), None)
    r["config_lembretes"] = _json(r.pop("config_lembretes_json", None), None)
    r["revisada"] = bool(r.get("revisada"))
    r["cliente_na_sala"] = presente(r.get("cliente_batida_em"))
    r["escritorio_na_sala"] = presente(r.get("escritorio_batida_em"))
    return r


def presente(batida: Any, instante: datetime | None = None) -> bool:
    data = ler_data(batida)
    if data is None:
        return False
    return ((instante or _agora_dt()) - data).total_seconds() <= PRESENCA_VALIDA_S


def obter(atendimento_id: str) -> dict[str, Any] | None:
    with banco.conectar() as con:
        linha = con.execute(f"SELECT * FROM {TABELA} WHERE id = ?", (atendimento_id,)).fetchone()
    return _registro(linha) if linha else None


def exigir(atendimento_id: str) -> dict[str, Any]:
    registro = obter(atendimento_id)
    if registro is None:
        raise AtendimentoNaoEncontrado("Atendimento não encontrado.")
    return registro


def por_sala(sala: str) -> dict[str, Any] | None:
    """O atendimento vivo desta sala. Sala de atendimento encerrado não conta."""
    if not sala:
        return None
    marcadores = ",".join("?" for _ in TERMINAIS)
    with banco.conectar() as con:
        linhas = con.execute(
            f"SELECT * FROM {TABELA} WHERE sala = ? AND estado NOT IN ({marcadores}) "
            "ORDER BY criado_em DESC",
            (sala, *sorted(TERMINAIS)),
        ).fetchall()
    return _registro(linhas[0]) if linhas else None


def por_entrevista(entrevista_id: str) -> dict[str, Any] | None:
    if not entrevista_id:
        return None
    with banco.conectar() as con:
        linhas = con.execute(
            f"SELECT * FROM {TABELA} WHERE entrevista_id = ? ORDER BY criado_em DESC",
            (entrevista_id,),
        ).fetchall()
    return _registro(linhas[0]) if linhas else None


def listar(
    *, de: str | None = None, ate: str | None = None, estados: list[str] | None = None
) -> list[dict[str, Any]]:
    filtros, params = [], []
    de = data_utc(de) if de else None
    ate = data_utc(ate) if ate else None
    if de:
        filtros.append("(data_hora >= ? OR (data_hora IS NULL AND criado_em >= ?))")
        params += [de, de]
    if ate:
        filtros.append("(data_hora < ? OR (data_hora IS NULL AND criado_em < ?))")
        params += [ate, ate]
    if estados:
        filtros.append(f"estado IN ({','.join('?' for _ in estados)})")
        params += estados
    onde = f" WHERE {' AND '.join(filtros)}" if filtros else ""
    with banco.conectar() as con:
        linhas = con.execute(
            f"SELECT * FROM {TABELA}{onde} ORDER BY data_hora, criado_em", tuple(params)
        ).fetchall()
    return [_registro(linha) for linha in linhas]


def eventos(atendimento_id: str) -> list[dict[str, Any]]:
    with banco.conectar() as con:
        linhas = con.execute(
            f"SELECT * FROM {TABELA_EVENTOS} WHERE atendimento_id = ? ORDER BY criado_em, id",
            (atendimento_id,),
        ).fetchall()
    return [dict(zip(linha.keys(), linha)) for linha in linhas]


# ------------------------------------------------------------------ escrita


def _evento(
    con: Any, atendimento_id: str, tipo: str, *, de: str | None = None, para: str | None = None,
    usuario_id: str | None = None, usuario_nome: str | None = None, detalhes: str | None = None,
) -> None:
    con.execute(
        f"""INSERT INTO {TABELA_EVENTOS}
            (id, atendimento_id, tipo, de_estado, para_estado, usuario_id, usuario_nome,
             detalhes, criado_em)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            uuid.uuid4().hex, atendimento_id, tipo, de, para, usuario_id,
            (usuario_nome or "")[:200] or None, (detalhes or "")[:1000] or None, agora(),
        ),
    )


def _sincronizar_alertas(registro: dict[str, Any] | None) -> None:
    if registro is None:
        return
    from . import alertas

    try:
        alertas.sincronizar(registro)
    except Exception:  # noqa: BLE001 - alerta é derivado; o estado já está gravado
        log.warning("Alertas do atendimento %s não sincronizaram.", registro.get("id"), exc_info=True)


def criar(
    *,
    cliente: str,
    telefone: str = "",
    data_hora: str | None = None,
    responsavel_id: str | None = None,
    responsavel_nome: str | None = None,
    origem: str = "agenda",
    sala: str | None = None,
    observacao: str = "",
    config_lembretes: dict[str, Any] | None = None,
    entrevista_id: str | None = None,
    estado: str = AGENDADA,
    usuario_nome: str = "",
    duracao_min: int = 60,
) -> dict[str, Any]:
    cliente = " ".join(str(cliente or "").split())[:200]
    if origem == "agenda" and not cliente:
        raise ErroAtendimento("Informe o nome do cliente.")
    if origem == "agenda" and ler_data(data_hora) is None:
        raise ErroAtendimento("Informe a data e a hora do atendimento.")
    if estado not in (AGENDADA, EM_ATENDIMENTO):
        raise ErroAtendimento("Atendimento novo começa agendado ou em atendimento.")
    sala = sala or chamada.gerar_sala()
    instante = agora()
    data_normalizada = data_utc(data_hora)
    novo_id = uuid.uuid4().hex
    with banco.conectar() as con:
        con.execute(
            f"""INSERT INTO {TABELA}
                (id, cliente, telefone, data_hora, duracao_min, sala, link_cliente,
                 responsavel_id, responsavel_nome, atendente_id, atendente_nome,
                 entrevista_id, estado, origem, config_lembretes_json, observacao,
                 versao, criado_em, criado_por, atualizado_em)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)""",
            (
                novo_id, cliente, str(telefone or "")[:30], data_normalizada,
                max(10, min(int(duracao_min or 60), 480)), sala, url_cliente(sala),
                responsavel_id, (responsavel_nome or "")[:200] or None,
                responsavel_id if estado == EM_ATENDIMENTO else None,
                ((responsavel_nome or "")[:200] or None) if estado == EM_ATENDIMENTO else None,
                entrevista_id, estado, origem,
                json.dumps(normalizar_lembretes(config_lembretes), ensure_ascii=False)
                if config_lembretes is not None else None,
                str(observacao or "")[:1000] or None, instante, usuario_nome[:200] or None, instante,
            ),
        )
        _evento(con, novo_id, "criado", para=estado, usuario_id=responsavel_id,
                usuario_nome=usuario_nome or responsavel_nome, detalhes=origem)
    return exigir(novo_id)


def atualizar_agenda(
    atendimento_id: str, campos: dict[str, Any], *, versao: int, usuario_nome: str
) -> dict[str, Any]:
    atual = exigir(atendimento_id)
    if atual["estado"] not in ANTES_DA_ENTREVISTA:
        raise TransicaoInvalida("A entrevista já começou: o agendamento não pode mais ser editado.")
    sets, params = [], []
    if "cliente" in campos:
        nome = " ".join(str(campos["cliente"] or "").split())[:200]
        if not nome:
            raise ErroAtendimento("Informe o nome do cliente.")
        sets.append("cliente = ?")
        params.append(nome)
    if "telefone" in campos:
        sets.append("telefone = ?")
        params.append(str(campos["telefone"] or "")[:30])
    if "data_hora" in campos:
        data = data_utc(campos["data_hora"])
        if data is None:
            raise ErroAtendimento("Data e hora inválidas.")
        sets.append("data_hora = ?")
        params.append(data)
    for campo in ("responsavel_id", "responsavel_nome", "observacao"):
        if campo in campos:
            sets.append(f"{campo} = ?")
            params.append(campos[campo] or None)
    if "config_lembretes" in campos:
        sets.append("config_lembretes_json = ?")
        params.append(
            json.dumps(normalizar_lembretes(campos["config_lembretes"]), ensure_ascii=False)
            if campos["config_lembretes"] is not None else None
        )
    if not sets:
        return atual
    with banco.conectar() as con:
        alteradas = con.execute(
            f"UPDATE {TABELA} SET {', '.join(sets)}, versao = versao + 1, atualizado_em = ? "
            "WHERE id = ? AND versao = ?",
            (*params, agora(), atendimento_id, int(versao)),
        ).rowcount
        if not alteradas:
            raise TransicaoInvalida("O agendamento foi alterado por outra pessoa. Recarregue.")
        _evento(con, atendimento_id, "agenda_editada", usuario_nome=usuario_nome,
                detalhes=", ".join(sorted(campos)))
    return exigir(atendimento_id)


def transicionar(
    atendimento_id: str,
    para: str,
    *,
    de: frozenset[str] | set[str] | None = None,
    usuario_id: str | None = None,
    usuario_nome: str | None = None,
    detalhes: str | None = None,
    extras: dict[str, Any] | None = None,
    tipo_evento: str = "transicao",
) -> dict[str, Any]:
    """Muda o estado se — e só se — o estado atual permitir. Atômico no banco.

    `de` restringe ainda mais as origens aceitas (ex.: só sair de AGENDADA).
    `extras` grava colunas junto da mudança, na mesma instrução.
    """
    if para not in ESTADOS:
        raise ErroAtendimento(f"Estado desconhecido: {para}.")
    origens = {e for e, destinos in TRANSICOES.items() if para in destinos}
    if de is not None:
        origens &= set(de)
    if not origens:
        raise TransicaoInvalida(f"Nenhum estado leva a {para}.")
    atual = exigir(atendimento_id)
    sets = ["estado = ?", "versao = versao + 1", "atualizado_em = ?"]
    params: list[Any] = [para, agora()]
    for coluna, valor in (extras or {}).items():
        if coluna not in _CAMPOS or coluna in {"id", "estado", "versao"}:
            raise ErroAtendimento(f"Coluna não editável: {coluna}.")
        sets.append(f"{coluna} = ?")
        params.append(valor)
    if para in TERMINAIS or para == DOCUMENTACAO_PENDENTE:
        sets.append("finalizado_em = COALESCE(finalizado_em, ?)")
        params.append(agora())
    marcadores = ",".join("?" for _ in origens)
    with banco.conectar() as con:
        alteradas = con.execute(
            f"UPDATE {TABELA} SET {', '.join(sets)} WHERE id = ? AND estado IN ({marcadores})",
            (*params, atendimento_id, *sorted(origens)),
        ).rowcount
        if not alteradas:
            raise TransicaoInvalida(
                f"O atendimento está em {atual['estado']} e não pode ir para {para}."
            )
        _evento(con, atendimento_id, tipo_evento, de=atual["estado"], para=para,
                usuario_id=usuario_id, usuario_nome=usuario_nome, detalhes=detalhes)
    registro = exigir(atendimento_id)
    _sincronizar_alertas(registro)
    return registro


def gravar(atendimento_id: str, campos: dict[str, Any], *, evento: str | None = None,
           usuario_nome: str | None = None) -> dict[str, Any]:
    """Grava colunas sem mudar o estado (ex.: casos criados, ações confirmadas)."""
    sets, params = [], []
    for coluna, valor in campos.items():
        if coluna not in _CAMPOS or coluna in {"id", "estado", "versao"}:
            raise ErroAtendimento(f"Coluna não editável: {coluna}.")
        sets.append(f"{coluna} = ?")
        params.append(valor)
    if not sets:
        return exigir(atendimento_id)
    with banco.conectar() as con:
        con.execute(
            f"UPDATE {TABELA} SET {', '.join(sets)}, versao = versao + 1, atualizado_em = ? WHERE id = ?",
            (*params, agora(), atendimento_id),
        )
        if evento:
            _evento(con, atendimento_id, evento, usuario_nome=usuario_nome)
    return exigir(atendimento_id)


def registrar_evento(atendimento_id: str, tipo: str, *, usuario_id: str | None = None,
                     usuario_nome: str | None = None, detalhes: str | None = None) -> None:
    with banco.conectar() as con:
        _evento(con, atendimento_id, tipo, usuario_id=usuario_id, usuario_nome=usuario_nome,
                detalhes=detalhes)


# ---------------------------------------------------------------- presença


def presenca_do_cliente(sala: str, evento: str) -> dict[str, Any] | None:
    """O navegador do cliente avisou que entrou, segue na sala ou saiu."""
    registro = por_sala(sala)
    if registro is None:
        return None
    instante = agora()
    if evento == "saiu":
        with banco.conectar() as con:
            con.execute(
                f"UPDATE {TABELA} SET cliente_batida_em = NULL, cliente_saiu_em = ?, "
                "atualizado_em = ? WHERE id = ?",
                (instante, instante, registro["id"]),
            )
            _evento(con, registro["id"], "cliente_saiu")
        registro = exigir(registro["id"])
        if registro["estado"] == CLIENTE_AGUARDANDO:
            try:
                return transicionar(registro["id"], AGENDADA, de={CLIENTE_AGUARDANDO},
                                    detalhes="cliente saiu da sala")
            except TransicaoInvalida:
                registro = exigir(registro["id"])
        _sincronizar_alertas(registro)
        return registro

    estava_presente = registro["cliente_na_sala"]
    with banco.conectar() as con:
        if estava_presente:
            con.execute(
                f"UPDATE {TABELA} SET cliente_batida_em = ?, atualizado_em = ? WHERE id = ?",
                (instante, instante, registro["id"]),
            )
        else:
            # Nova chegada: o relógio da espera recomeça daqui.
            con.execute(
                f"UPDATE {TABELA} SET cliente_batida_em = ?, cliente_entrou_em = ?, "
                "cliente_saiu_em = NULL, atualizado_em = ? WHERE id = ?",
                (instante, instante, instante, registro["id"]),
            )
            _evento(con, registro["id"], "cliente_entrou")
    registro = exigir(registro["id"])
    if registro["estado"] in (AGENDADA, CLIENTE_FALTOU) and not registro["escritorio_na_sala"]:
        try:
            return transicionar(registro["id"], CLIENTE_AGUARDANDO, de={AGENDADA, CLIENTE_FALTOU},
                                detalhes="cliente entrou na sala")
        except TransicaoInvalida:
            registro = exigir(registro["id"])
    _sincronizar_alertas(registro)
    return registro


def presenca_do_escritorio(
    sala: str, evento: str, usuario_id: str, usuario_nome: str
) -> dict[str, Any] | None:
    """Alguém do escritório entrou, segue ou saiu da sala deste atendimento.

    Entrar resolve a espera do cliente. Se quem entrou não é o responsável, ele
    passa a ser o atendente — e isso fica registrado como "assumiu".
    """
    registro = por_sala(sala)
    if registro is None:
        return None
    instante = agora()
    if evento == "saiu":
        with banco.conectar() as con:
            con.execute(
                f"UPDATE {TABELA} SET escritorio_batida_em = NULL, atualizado_em = ? WHERE id = ?",
                (instante, registro["id"]),
            )
        return exigir(registro["id"])
    with banco.conectar() as con:
        con.execute(
            f"UPDATE {TABELA} SET escritorio_batida_em = ?, atualizado_em = ? WHERE id = ?",
            (instante, instante, registro["id"]),
        )
    if registro["estado"] in ANTES_DA_ENTREVISTA:
        return iniciar_atendimento(registro["id"], usuario_id, usuario_nome, motivo="entrou na sala")
    return exigir(registro["id"])


def iniciar_atendimento(
    atendimento_id: str, usuario_id: str, usuario_nome: str, *, motivo: str = "assumiu"
) -> dict[str, Any]:
    """Leva a EM_ATENDIMENTO com quem atende. Recusa se outra pessoa já atende."""
    registro = exigir(atendimento_id)
    if registro["estado"] == EM_ATENDIMENTO:
        if registro.get("atendente_id") and registro["atendente_id"] != usuario_id:
            raise TransicaoInvalida(
                f"{registro.get('atendente_nome') or 'Outra pessoa'} já está atendendo este cliente."
            )
        return registro
    outro = bool(registro.get("responsavel_id")) and registro["responsavel_id"] != usuario_id
    return transicionar(
        atendimento_id,
        EM_ATENDIMENTO,
        de=ANTES_DA_ENTREVISTA,
        usuario_id=usuario_id,
        usuario_nome=usuario_nome,
        detalhes=motivo,
        tipo_evento="assumiu" if outro else "responsavel_entrou",
        extras={"atendente_id": usuario_id, "atendente_nome": (usuario_nome or "")[:200]},
    )


def garantir_para_entrevista(
    *, entrevista_id: str, cliente: str, sala: str | None, usuario_id: str, usuario_nome: str,
    atendimento_id: str | None = None,
) -> dict[str, Any]:
    """O atendimento da entrevista que está começando — o agendado ou um avulso novo.

    Entrevista sem agendamento também passa pela máquina de estados: é o que faz a
    análise, a criação dos casos e a documentação seguirem o mesmo caminho.
    """
    existente = exigir(atendimento_id) if atendimento_id else (
        por_entrevista(entrevista_id) or (por_sala(sala) if sala else None)
    )
    if existente is not None:
        if not existente.get("entrevista_id"):
            existente = gravar(existente["id"], {"entrevista_id": entrevista_id})
        if existente["estado"] in ANTES_DA_ENTREVISTA:
            existente = iniciar_atendimento(existente["id"], usuario_id, usuario_nome,
                                            motivo="iniciou a entrevista")
        return existente
    return criar(
        cliente=cliente, origem="avulso", sala=sala, entrevista_id=entrevista_id,
        responsavel_id=usuario_id, responsavel_nome=usuario_nome, estado=EM_ATENDIMENTO,
        usuario_nome=usuario_nome,
    )


def varrer_vencidos(instante: datetime | None = None) -> dict[str, int]:
    """Corrige o que o tempo mudou: cliente que fechou a aba e cliente que não veio."""
    instante = instante or _agora_dt()
    config = obter_config()
    tolerancia = timedelta(minutes=int(config["tolerancia_falta_min"]))
    saidas = faltas = 0
    for registro in listar(estados=[CLIENTE_AGUARDANDO]):
        if not presente(registro.get("cliente_batida_em"), instante):
            try:
                transicionar(registro["id"], AGENDADA, de={CLIENTE_AGUARDANDO},
                             detalhes="sem sinal do cliente na sala")
                saidas += 1
            except TransicaoInvalida:
                pass
    limite = (instante - tolerancia).isoformat(timespec="seconds")
    for registro in listar(estados=[AGENDADA], ate=limite):
        data = ler_data(registro.get("data_hora"))
        if data is None or data + tolerancia > instante:
            continue
        if registro.get("cliente_entrou_em") and ler_data(registro["cliente_entrou_em"]) >= data - timedelta(hours=2):
            continue
        try:
            transicionar(registro["id"], CLIENTE_FALTOU, de={AGENDADA},
                         detalhes="horário passou sem o cliente entrar")
            faltas += 1
        except TransicaoInvalida:
            pass
    return {"saidas": saidas, "faltas": faltas}
