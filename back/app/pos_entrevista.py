"""Do "ações confirmadas" à fila da documentação: casos, qualificação, avaliação.

Cada passo daqui é chamado pela tela do pós-entrevista e só anda se o atendimento
estiver no estado certo (`app/atendimentos.py`). Repetir um passo — clique duplo,
aba recarregada, rede que caiu no meio — devolve o que já foi feito em vez de
fazer de novo.

CASOS

Cada ação confirmada vira UM caso, com a ação como categoria (é o checklist dela
que o portal pede ao cliente). A ação nova aceita pelo advogado nasce antes como
tipo de caso "Gerado por IA — requer revisão" (`criterios_caso.criar_rascunho_ia`).
`casos_json` é gravado a cada caso criado: se a confirmação cair no meio, a
próxima tentativa só cria o que falta. Uma trava no banco (evento com id fixo)
impede duas confirmações simultâneas de criarem casos em dobro.

DOCUMENTOS CONSOLIDADOS

O que o escritório já tem e o que falta, somando todos os casos do atendimento:
os itens obrigatórios dos checklists, menos o que já chegou neste caso, o que
já foi validado em outro caso do mesmo CPF e o que o cliente disse ter na
entrevista. Dois casos que pedem RG pedem UM RG.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import unicodedata
from datetime import timedelta
from typing import Any, Iterable

import pyodbc

from . import atendimentos as at
from . import banco

log = logging.getLogger("pos_entrevista")

MAXIMO_ACOES = 6
#: Trava de confirmação mais velha que isto é de uma requisição que morreu.
TRAVA_VENCIDA = timedelta(minutes=3)
MAXIMO_OUTROS_CASOS = 5

_ERROS_DE_CHAVE = (pyodbc.IntegrityError, sqlite3.IntegrityError)


class ErroPosEntrevista(at.ErroAtendimento):
    status = 400


class ConfirmacaoEmAndamento(at.ErroAtendimento):
    status = 409


# ------------------------------------------------------------- documentos


def _normalizar(texto: Any) -> str:
    sem = "".join(
        c for c in unicodedata.normalize("NFD", str(texto or "")) if unicodedata.category(c) != "Mn"
    )
    return " ".join(sem.lower().split())


def chave_documento(item: dict[str, Any]) -> str:
    """O mesmo documento em dois checklists: pelo tipo de OCR, ou pelo nome."""
    tipo = str(item.get("tipo") or "").strip().lower()
    return f"tipo:{tipo}" if tipo else f"nome:{_normalizar(item.get('nome'))}"


def consolidar(
    casos: list[dict[str, Any]],
    declarados: Iterable[str] = (),
    validados_em_outros: Iterable[str] = (),
) -> dict[str, list[dict[str, Any]]]:
    """Função pura: DISPONÍVEIS e FALTANTES do atendimento inteiro.

    `casos`: [{"id", "acao", "itens": [{"codigo", "nome", "obrigatorio", "tipo", "status"}]}].
    `declarados`: nomes de documentos que o cliente disse ter (marcados na tela).
    `validados_em_outros`: chaves (`chave_documento`) já validadas em outro caso do CPF.
    """
    from .casos import PENDENTE

    declarados_norm = {_normalizar(d): str(d).strip() for d in declarados if _normalizar(d)}
    outros = set(validados_em_outros)
    disponiveis: dict[str, dict[str, Any]] = {}
    faltantes: dict[str, dict[str, Any]] = {}
    usados: set[str] = set()

    def anotar(destino: dict[str, dict[str, Any]], chave: str, item: dict[str, Any],
               origem: str, caso: dict[str, Any]) -> None:
        atual = destino.setdefault(chave, {
            "nome": item.get("nome") or "Documento", "tipo": item.get("tipo"),
            "origem": origem, "casos": [],
        })
        rotulo = caso.get("acao") or caso.get("id")
        if rotulo and rotulo not in atual["casos"]:
            atual["casos"].append(rotulo)

    for caso in casos:
        for item in caso.get("itens") or []:
            chave = chave_documento(item)
            nome_norm = _normalizar(item.get("nome"))
            status = str(item.get("status") or PENDENTE)
            if status != PENDENTE:
                anotar(disponiveis, chave, item, "caso", caso)
            elif chave in outros:
                anotar(disponiveis, chave, item, "outro_caso", caso)
            elif nome_norm in declarados_norm:
                usados.add(nome_norm)
                anotar(disponiveis, chave, item, "entrevista", caso)
            elif item.get("obrigatorio"):
                anotar(faltantes, chave, item, "checklist", caso)
    for nome_norm, nome in declarados_norm.items():
        chave = f"nome:{nome_norm}"
        if nome_norm not in usados and chave not in disponiveis:
            disponiveis[chave] = {"nome": nome, "tipo": None, "origem": "entrevista", "casos": []}
    for chave in list(faltantes):
        if chave in disponiveis:
            faltantes.pop(chave)
    return {"disponiveis": list(disponiveis.values()), "faltantes": list(faltantes.values())}


def _itens_do_caso(caso_id: str) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    from . import casos

    situacao = casos.montar_situacao(caso_id)
    if situacao is None:
        return [], None
    return list(situacao.get("itens") or []), situacao.get("caso")


def _validados_em_outros_casos(cpf: str, ignorar: set[str]) -> set[str]:
    from . import armazenamento, casos

    digitos = "".join(c for c in str(cpf or "") if c.isdigit())
    if len(digitos) != 11:
        return set()
    chaves: set[str] = set()
    outros = [
        c for c in armazenamento.listar_casos()
        if c.get("id") not in ignorar and "".join(ch for ch in str(c.get("cpf") or "") if ch.isdigit()) == digitos
    ][:MAXIMO_OUTROS_CASOS]
    for caso in outros:
        itens, _ = _itens_do_caso(caso["id"])
        chaves |= {chave_documento(i) for i in itens if i.get("status") == casos.ENTREGUE}
    return chaves


def _cpf_dos_casos(caso_ids: list[str]) -> str:
    from . import armazenamento

    for caso_id in caso_ids:
        qualificacao = armazenamento.obter_qualificacao(caso_id) or {}
        if qualificacao.get("cpf"):
            return str(qualificacao["cpf"])
    return ""


def documentos_consolidados(registro: dict[str, Any]) -> dict[str, Any]:
    casos_do_atendimento = []
    ids = [c["id"] for c in registro.get("casos") or [] if c.get("id")]
    for caso in registro.get("casos") or []:
        if not caso.get("id"):
            continue
        itens, _ = _itens_do_caso(caso["id"])
        casos_do_atendimento.append({"id": caso["id"], "acao": caso.get("acao"), "itens": itens})
    anteriores = registro.get("documentos") or {}
    declarados = anteriores.get("declarados") or []
    try:
        outros = _validados_em_outros_casos(_cpf_dos_casos(ids), set(ids))
    except Exception:  # noqa: BLE001 - sem o cruzamento por CPF, o resumo continua útil
        log.warning("Cruzamento de documentos por CPF falhou.", exc_info=True)
        outros = set()
    resumo = consolidar(casos_do_atendimento, declarados, outros)
    return {**resumo, "declarados": declarados, "atualizado_em": at.agora()}


def _recalcular_documentos(registro: dict[str, Any]) -> str | None:
    try:
        return json.dumps(documentos_consolidados(registro), ensure_ascii=False)
    except Exception:  # noqa: BLE001 - o passo não trava por causa do resumo
        log.warning("Documentos consolidados do atendimento %s falharam.", registro.get("id"),
                    exc_info=True)
        return None


# ------------------------------------------------------------- confirmação


def _id_trava(atendimento_id: str) -> str:
    return f"trava-confirmar:{atendimento_id}"[:64]


def _travar(atendimento_id: str) -> None:
    trava = _id_trava(atendimento_id)
    for _ in range(2):
        try:
            with banco.conectar() as con:
                con.execute(
                    f"""INSERT INTO {at.TABELA_EVENTOS}
                        (id, atendimento_id, tipo, criado_em) VALUES (?, ?, 'confirmando_acoes', ?)""",
                    (trava, atendimento_id, at.agora()),
                )
            return
        except _ERROS_DE_CHAVE:
            with banco.conectar() as con:
                linha = con.execute(
                    f"SELECT criado_em FROM {at.TABELA_EVENTOS} WHERE id = ?", (trava,)
                ).fetchone()
            criada = at.ler_data(linha["criado_em"]) if linha else None
            if criada is None or at._agora_dt() - criada > TRAVA_VENCIDA:
                _destravar(atendimento_id)
                continue
            raise ConfirmacaoEmAndamento(
                "Outra pessoa (ou outra aba) está confirmando estas ações agora."
            ) from None
    raise ConfirmacaoEmAndamento("Não foi possível reservar a confirmação. Tente de novo.")


def _destravar(atendimento_id: str) -> None:
    with banco.conectar() as con:
        con.execute(f"DELETE FROM {at.TABELA_EVENTOS} WHERE id = ?", (_id_trava(atendimento_id),))


def normalizar_acoes(acoes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Valida e deduplica o que o advogado confirmou. Função pura.

    Cada ação: `{"codigo": ...}` (do catálogo) ou `{"nome": ..., "nova": {...}}`
    (ação nova; vira tipo de caso rascunho). `origem`: ia | triagem | manual.
    """
    saida: list[dict[str, Any]] = []
    vistos: set[str] = set()
    for bruta in acoes or []:
        if not isinstance(bruta, dict):
            continue
        codigo = str(bruta.get("codigo") or "").strip()
        nome = " ".join(str(bruta.get("nome") or "").split())[:200]
        origem = str(bruta.get("origem") or "manual")
        if origem not in ("ia", "triagem", "manual"):
            origem = "manual"
        if codigo:
            marca = f"codigo:{codigo}"
            item = {"codigo": codigo, "nome": nome, "origem": origem, "nova": None}
        elif nome:
            marca = f"nome:{_normalizar(nome)}"
            nova = bruta.get("nova") if isinstance(bruta.get("nova"), dict) else {}
            item = {"codigo": "", "nome": nome, "origem": origem, "nova": nova}
        else:
            continue
        if marca in vistos:
            continue
        vistos.add(marca)
        saida.append(item)
    if not saida:
        raise ErroPosEntrevista("Confirme ao menos uma ação para criar o caso.")
    if len(saida) > MAXIMO_ACOES:
        raise ErroPosEntrevista(f"No máximo {MAXIMO_ACOES} ações por atendimento.")
    return saida


def _resolver_categoria(acao: dict[str, Any], usuario: str, atendimento_id: str) -> tuple[str, str, bool]:
    """(codigo, nome, rascunho_ia) da ação: do catálogo, ou criada como rascunho."""
    from . import categorias, criterios_caso, tipos_caso

    if acao["codigo"]:
        categoria = categorias.obter(acao["codigo"])
        if categoria is None:
            raise ErroPosEntrevista(f"A ação “{acao['nome'] or acao['codigo']}” não existe no catálogo.")
        return categoria.codigo, categoria.nome, False
    nova = acao.get("nova") or {}
    try:
        tipo = criterios_caso.criar_rascunho_ia(
            nome=acao["nome"],
            descricao=str(nova.get("descricao") or ""),
            criterios=[str(c) for c in nova.get("criterios") or [] if str(c).strip()],
            documentos=[d for d in nova.get("documentos") or [] if isinstance(d, dict)],
            informacoes_necessarias=[str(i) for i in nova.get("informacoes_necessarias") or []],
            fundamentos=[f for f in nova.get("fundamentos") or [] if isinstance(f, dict)],
            usuario=usuario,
            atendimento_id=atendimento_id,
        )
    except tipos_caso.ErroTipoCaso as exc:
        raise ErroPosEntrevista(f"A ação nova “{acao['nome']}” não pôde ser criada: {exc}") from exc
    try:
        rascunho = tipo["codigo"] in criterios_caso.metadados_ia()
    except Exception:  # noqa: BLE001 - só o selo da tela depende disto
        rascunho = False
    return tipo["codigo"], tipo["nome"], rascunho


def confirmar_acoes(
    atendimento_id: str,
    *,
    acoes: list[dict[str, Any]],
    documentos_declarados: list[str] | None = None,
    cliente: str = "",
    telefone: str = "",
    usuario_id: str | None = None,
    usuario_nome: str = "",
) -> dict[str, Any]:
    """Cria um caso por ação confirmada e leva o atendimento à QUALIFICAÇÃO.

    Devolve `{"atendimento", "casos": [{..., "portal": {url, senha, aviso}}]}`. A
    senha do portal só aparece na resposta que criou o caso.
    """
    from . import armazenamento
    from .rotas.comum import _criar_portal

    registro = at.exigir(atendimento_id)
    if registro["estado"] != at.AGUARDANDO_CONFIRMACAO_ACOES:
        if registro["casos"]:
            return {"atendimento": registro, "casos": registro["casos"], "repetido": True}
        raise at.TransicaoInvalida(
            f"O atendimento está em {registro['estado']}: não há ações para confirmar."
        )
    lista = normalizar_acoes(acoes)
    nome_cliente = " ".join(str(cliente or registro.get("cliente") or "").split())[:200]
    if not nome_cliente:
        raise ErroPosEntrevista("Informe o nome do cliente antes de criar o caso.")
    fone = str(telefone or registro.get("telefone") or "")[:30]

    _travar(atendimento_id)
    try:
        registro = at.exigir(atendimento_id)
        if registro["estado"] != at.AGUARDANDO_CONFIRMACAO_ACOES:
            return {"atendimento": registro, "casos": registro["casos"], "repetido": True}
        casos_feitos: list[dict[str, Any]] = list(registro["casos"])
        criados_agora: list[dict[str, Any]] = []
        acoes_gravadas: list[dict[str, Any]] = []
        for acao in lista:
            codigo, nome, rascunho = _resolver_categoria(acao, usuario_nome, atendimento_id)
            existente = next((c for c in casos_feitos if c.get("categoria") == codigo), None)
            if existente is None:
                caso = armazenamento.criar_caso(
                    nome_cliente, codigo,
                    f"Atendimento de {registro.get('data_hora') or registro.get('criado_em') or ''}: {nome}".strip(),
                    fone, nome,
                )
                portal = _criar_portal(caso["id"])
                existente = {
                    "id": caso["id"], "categoria": codigo, "acao": nome, "origem": acao["origem"],
                    "rascunho_ia": rascunho, "portal_url": portal["url"],
                }
                casos_feitos.append(existente)
                criados_agora.append({**existente, "portal": portal})
                at.gravar(atendimento_id, {"casos_json": json.dumps(casos_feitos, ensure_ascii=False)},
                          evento="caso_criado", usuario_nome=usuario_nome)
            acoes_gravadas.append({
                "codigo": codigo, "nome": nome, "origem": acao["origem"],
                "nova": not acao["codigo"], "caso_id": existente["id"],
            })
        try:
            from .rotas.casos import listar_casos

            listar_casos.limpar_cache()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - cache da carteira, não o caso
            pass
        declarados = [" ".join(str(d).split())[:200] for d in documentos_declarados or [] if str(d).strip()][:60]
        provisorio = {**registro, "casos": casos_feitos,
                      "documentos": {**(registro.get("documentos") or {}), "declarados": declarados}}
        documentos_json = _recalcular_documentos(provisorio) or json.dumps(
            {"disponiveis": [], "faltantes": [], "declarados": declarados}, ensure_ascii=False
        )
        try:
            registro = at.transicionar(
                atendimento_id, at.QUALIFICACAO, de={at.AGUARDANDO_CONFIRMACAO_ACOES},
                usuario_id=usuario_id, usuario_nome=usuario_nome,
                detalhes=", ".join(a["nome"] for a in acoes_gravadas)[:1000],
                extras={
                    "casos_json": json.dumps(casos_feitos, ensure_ascii=False),
                    "acoes_json": json.dumps(acoes_gravadas, ensure_ascii=False),
                    "documentos_json": documentos_json,
                    "cliente": nome_cliente,
                    "telefone": fone,
                },
            )
        except at.TransicaoInvalida:
            registro = at.exigir(atendimento_id)
    finally:
        _destravar(atendimento_id)
    portais = {c["id"]: c.get("portal") for c in criados_agora}
    return {
        "atendimento": registro,
        "casos": [{**c, "portal": portais.get(c["id"])} for c in registro["casos"]],
        "repetido": not criados_agora,
    }


# ------------------------------------------------------------- qualificação


def concluir_qualificacao(
    atendimento_id: str, *, dados: dict[str, Any] | None = None,
    usuario_id: str | None = None, usuario_nome: str = "",
) -> dict[str, Any]:
    """Grava a qualificação em todos os casos do atendimento e segue para a avaliação."""
    from . import armazenamento

    registro = at.exigir(atendimento_id)
    if registro["estado"] in (at.AVALIACAO_ESCRITORIO, at.DOCUMENTACAO_PENDENTE, at.CONCLUIDA):
        return registro
    if registro["estado"] != at.QUALIFICACAO:
        raise at.TransicaoInvalida(f"O atendimento está em {registro['estado']}, não na qualificação.")
    if dados:
        for caso in registro["casos"]:
            if caso.get("id"):
                armazenamento.salvar_qualificacao(caso["id"], dados)
    extras: dict[str, Any] = {}
    documentos = _recalcular_documentos(registro)
    if documentos:
        extras["documentos_json"] = documentos
    try:
        return at.transicionar(
            atendimento_id, at.AVALIACAO_ESCRITORIO, de={at.QUALIFICACAO},
            usuario_id=usuario_id, usuario_nome=usuario_nome, extras=extras,
        )
    except at.TransicaoInvalida:
        return at.exigir(atendimento_id)


# ---------------------------------------------------------------- avaliação


def enviar_avaliacao(atendimento_id: str, *, telefone: str = "", forcar: bool = False,
                     usuario_nome: str = "") -> dict[str, Any]:
    from . import whatsapp_modelos

    registro = at.exigir(atendimento_id)
    if registro["estado"] not in (at.AVALIACAO_ESCRITORIO, at.DOCUMENTACAO_PENDENTE, at.CONCLUIDA):
        raise at.TransicaoInvalida("A avaliação do escritório vem depois da qualificação.")
    numero = str(telefone or registro.get("telefone") or "")
    if not numero:
        raise ErroPosEntrevista("Informe o WhatsApp do cliente para enviar o link de avaliação.")
    resultado = whatsapp_modelos.enviar_avaliacao(registro, numero, forcar=forcar)
    at.registrar_evento(atendimento_id, "avaliacao_" + str(resultado.get("status") or "falhou"),
                        usuario_nome=usuario_nome, detalhes=str(resultado.get("motivo") or "")[:500] or None)
    return resultado


def estado_avaliacao(atendimento_id: str) -> dict[str, Any]:
    from . import whatsapp_modelos

    at.exigir(atendimento_id)
    return whatsapp_modelos.estado_avaliacao(atendimento_id)


# ---------------------------------------------------------------- finalizar


def finalizar(
    atendimento_id: str, *, usuario_id: str, usuario_nome: str, pular_avaliacao: bool = False,
) -> dict[str, Any]:
    """Fecha o atendimento do lado do advogado e chama a equipe de documentação."""
    from . import documentacao

    registro = at.exigir(atendimento_id)
    if registro["estado"] in (at.DOCUMENTACAO_PENDENTE, at.CONCLUIDA):
        return registro
    if registro["estado"] != at.AVALIACAO_ESCRITORIO:
        raise at.TransicaoInvalida(f"O atendimento está em {registro['estado']}: ainda não pode finalizar.")
    if not registro["casos"]:
        raise ErroPosEntrevista("Nenhum caso foi criado neste atendimento.")
    if not pular_avaliacao:
        avaliacao = estado_avaliacao(atendimento_id)
        if avaliacao["status"] == "pendente":
            raise ErroPosEntrevista(
                "Envie o link de avaliação ao cliente ou marque que vai pular este passo."
            )
    extras: dict[str, Any] = {}
    documentos = _recalcular_documentos(registro)
    if documentos:
        extras["documentos_json"] = documentos
    try:
        registro = at.transicionar(
            atendimento_id, at.DOCUMENTACAO_PENDENTE, de={at.AVALIACAO_ESCRITORIO},
            usuario_id=usuario_id, usuario_nome=usuario_nome,
            detalhes="avaliação pulada" if pular_avaliacao else None, extras=extras,
        )
    except at.TransicaoInvalida:
        return at.exigir(atendimento_id)
    try:
        documentacao.enfileirar_para_documentacao(
            entrevista_id=registro.get("entrevista_id") or registro["id"],
            caso_id=registro["casos"][0]["id"],
            cliente=registro.get("cliente") or "",
            entrevistador_id=usuario_id or "",
            entrevistador_nome=usuario_nome or "",
        )
    except Exception:  # noqa: BLE001 - o alerta do atendimento já chama a documentação
        log.warning("Fila da documentação não recebeu o atendimento %s.", atendimento_id, exc_info=True)
    return registro
