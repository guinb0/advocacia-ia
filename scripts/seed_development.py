"""Populate the local development database with synthetic demonstration data.

    .\.venv\Scripts\python.exe -m scripts.seed_development --confirm
    .\.venv\Scripts\python.exe -m scripts.seed_development --clean --confirm
"""

from __future__ import annotations

import argparse
import os
import shutil
from datetime import datetime, timedelta, timezone
from app import ambiente, armazenamento, banco, categorias, perfis, tipos_documento, usuarios

CASE_PREFIX = "dev-seed-"
USER_SUFFIX = ".dev@acervo.local"
PASSWORD = "Demo123!"


def _timestamp(days_before: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_before)).isoformat(
        timespec="seconds"
    )


def _require_local_environment() -> None:
    ambiente.carregar()
    host = os.getenv("SQLSERVER_HOST", "").strip().lower()
    port = os.getenv("SQLSERVER_PORT", "").strip()
    test_data = os.getenv("PERMITIR_DADOS_TESTE", "").strip().lower()
    if host not in {"localhost", "127.0.0.1"} or port != "14333":
        raise RuntimeError("O seeder só pode usar o SQL Server local em 127.0.0.1:14333.")
    if test_data != "true":
        raise RuntimeError("Defina PERMITIR_DADOS_TESTE=true no .env para usar o seeder.")


def _case_id(name: str) -> str:
    return f"{CASE_PREFIX}{name}"


def _write_file(case_id: str, name: str, content: bytes) -> Path:
    directory = armazenamento.DIR_ARQUIVOS / case_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(content)
    return path


def _set_case_dates(case_id: str, created_at: str, updated_at: str) -> None:
    with banco.conectar() as connection:
        connection.execute(
            "UPDATE casos SET criado_em = ?, atualizado_em = ? WHERE id = ?",
            (created_at, updated_at, case_id),
        )


def _seed_delivery(case_id: str, item: object, days_before: float, approved: bool) -> None:
    item_code = str(getattr(item, "codigo"))
    item_name = str(getattr(item, "nome"))
    document_type = getattr(item, "tipo_ocr")
    path = _write_file(
        case_id,
        f"{item_code}.pdf",
        b"%PDF-1.7\nSynthetic development document.\n",
    )
    extraction = {
        "tipo": {"codigo": document_type, "detectado": document_type, "descricao": item_name},
        "validacao": {
            "veredito": "APROVADO" if approved else "REPROVADO",
            "dados_utilizaveis": approved,
            "score_legibilidade": 96 if approved else 32,
        },
        "campos": [],
    }
    delivery = armazenamento.registrar_entrega(
        case_id,
        item_code,
        path.name,
        path,
        extraction,
        True if document_type else None,
    )
    with banco.conectar() as connection:
        connection.execute(
            "UPDATE entregas SET criado_em = ?, agente_envio_chave = ? WHERE id = ?",
            (
                _timestamp(days_before),
                f"{CASE_PREFIX}agent-{delivery['id']}",
                delivery["id"],
            ),
        )


def _seed_interview(
    case_id: str, interviewer: str, interviewer_id: str, days_before: float
) -> str:
    path = _write_file(
        case_id,
        "entrevista.txt",
        b"Synthetic development interview. No personal data is present.",
    )
    interview = armazenamento.registrar_entrevista(
        case_id,
        arquivo=path.name,
        caminho=path,
        texto=(
            "Relato sintético para demonstrar entrevista, coleta documental e acompanhamento do caso."
        ),
        realizada_em=_timestamp(days_before),
        entrevistador=interviewer,
        entrevistador_id=interviewer_id,
    )
    interview_id = str(interview["id"])
    with banco.conectar() as connection:
        connection.execute(
            "UPDATE entrevistas SET criado_em = ?, enviada_em = ?, fatos_gerados = 4 "
            "WHERE id = ?",
            (_timestamp(days_before), _timestamp(days_before - 0.1), interview_id),
        )
    armazenamento.salvar_auditoria_entrevista(
        interview_id,
        {"status": "concluida", "nota": 92, "origem": "dados_sinteticos"},
        "Seed development",
    )
    with banco.conectar() as connection:
        connection.execute(
            "UPDATE auditorias_entrevista SET auditado_em = ? WHERE entrevista_id = ?",
            (_timestamp(days_before - 0.2), interview_id),
        )
    return interview_id


def _seed_signature(case_id: str, client: str, days_before: float, signed: bool) -> None:
    signed_at = _timestamp(days_before - 1) if signed else None
    signature = armazenamento.registrar_assinatura(
        f"{CASE_PREFIX}contract-{case_id}",
        "Development Office",
        client,
        [
            {
                "nome": client,
                "estado": "assinou" if signed else "pendente",
                "assinou_em": signed_at,
            }
        ],
        cpf="000.000.000-00",
        estado="assinado" if signed else "pendente",
        caso_id=case_id,
    )
    with banco.conectar() as connection:
        connection.execute(
            "UPDATE assinaturas SET criado_em = ?, atualizado_em = ? WHERE id = ?",
            (
                _timestamp(days_before),
                signed_at or _timestamp(days_before),
                signature["id"],
            ),
        )


def _seed_case(
    name: str,
    client: str,
    category_code: str,
    opened_days_before: float,
    interviewer: str,
    interviewer_id: str,
    documents: str,
    signed: bool = False,
) -> str:
    category = categorias.obter(category_code)
    if category is None:
        raise RuntimeError(f"Categoria de demonstração ausente: {category_code}.")
    case_id = _case_id(name)
    case = armazenamento.criar_caso(
        client,
        category_code,
        "Registro sintético criado pelo seeder de desenvolvimento.",
        "91999990000",
    )
    if case["id"] != case_id:
        with banco.conectar() as connection:
            connection.execute("UPDATE casos SET id = ? WHERE id = ?", (case_id, case["id"]))
        directory = armazenamento.DIR_ARQUIVOS / str(case["id"])
        if directory.exists():
            directory.rename(armazenamento.DIR_ARQUIVOS / case_id)
    armazenamento.salvar_qualificacao(
        case_id,
        {
            "cpf": "000.000.000-00",
            "nascimento": "1990-01-01",
            "nome_mae": "Pessoa Sintética",
            "cep": "00000-000",
            "endereco": "Endereço exclusivo de demonstração",
            "email": f"{name}{USER_SUFFIX}",
        },
    )
    _set_case_dates(case_id, _timestamp(opened_days_before), _timestamp(opened_days_before))
    if documents == "none":
        return case_id

    _seed_interview(case_id, interviewer, interviewer_id, opened_days_before - 1)
    required_items = [item for item in category.itens if item.obrigatorio]
    if documents == "partial":
        for item in required_items[:2]:
            _seed_delivery(case_id, item, opened_days_before - 2, True)
    else:
        for index, item in enumerate(required_items):
            _seed_delivery(
                case_id,
                item,
                opened_days_before - 2 - index * 0.1,
                documents != "review" or index != len(required_items) - 1,
            )
        _seed_signature(case_id, client, opened_days_before - 4, signed)
    armazenamento.registrar_ligacao(case_id, interviewer)
    call = armazenamento.register_call(case_id, interviewer_id, interviewer)
    with banco.conectar() as connection:
        connection.execute(
            "UPDATE ligacoes_followup SET criado_em = ? WHERE caso_id = ?",
            (_timestamp(opened_days_before - 1.5), case_id),
        )
        connection.execute(
            "UPDATE ligacoes SET realizada_em = ?, criado_em = ? WHERE id = ?",
            (
                _timestamp(opened_days_before - 1.4),
                _timestamp(opened_days_before - 1.4),
                call["id"],
            ),
        )
        connection.execute(
            "INSERT INTO cobrancas_documentos "
            "(caso_id, ativa, telefone, intervalo_dias, incluir_opcionais, criado_em, atualizado_em) "
            "VALUES (?, 1, ?, 3, 0, ?, ?)",
            (
                case_id,
                "91999990000",
                _timestamp(opened_days_before - 1),
                _timestamp(opened_days_before - 1),
            ),
        )
    _set_case_dates(
        case_id,
        _timestamp(opened_days_before),
        _timestamp(opened_days_before - 0.5),
    )
    return case_id


def _seed_conversation(case_id: str, user: str) -> None:
    conversation = armazenamento.criar_conversa(
        "Dúvida sintética sobre documentos",
        usuario=user,
        caso_id=case_id,
        resumo="Conversa criada exclusivamente para demonstração local.",
    )
    first = armazenamento.registrar_mensagem(
        conversation["id"],
        papel="usuario",
        conteudo="Quais documentos ainda preciso solicitar?",
        natureza="CASO",
    )
    second = armazenamento.registrar_mensagem(
        conversation["id"],
        papel="assistente",
        conteudo="A demonstração mostra os itens pendentes no checklist do caso.",
        natureza="CASO",
        payload={"origem": "dados_sinteticos"},
    )
    with banco.conectar() as connection:
        connection.execute(
            "UPDATE conversas SET criado_em = ?, atualizado_em = ? WHERE id = ?",
            (_timestamp(5), _timestamp(4), conversation["id"]),
        )
        connection.execute(
            "UPDATE conversa_mensagens SET criado_em = ? WHERE id = ?",
            (_timestamp(5), first["id"]),
        )
        connection.execute(
            "UPDATE conversa_mensagens SET criado_em = ? WHERE id = ?",
            (_timestamp(4), second["id"]),
        )


def _clean() -> None:
    with banco.conectar() as connection:
        connection.execute(
            "DELETE FROM assinaturas WHERE doc_token LIKE ?", (f"{CASE_PREFIX}%",)
        )
        connection.execute(
            "DELETE FROM automacoes_whatsapp WHERE chave LIKE ?", (f"{CASE_PREFIX}%",)
        )
        connection.execute("DELETE FROM conversas WHERE usuario LIKE ?", (f"%{USER_SUFFIX}",))
        connection.execute("DELETE FROM casos WHERE id LIKE ?", (f"{CASE_PREFIX}%",))
        connection.execute(
            "DELETE FROM dbo.acervo_usuarios WHERE email LIKE ?",
            (f"%{USER_SUFFIX}",),
        )
    for directory in armazenamento.DIR_ARQUIVOS.glob(f"{CASE_PREFIX}*"):
        if directory.is_dir():
            shutil.rmtree(directory)


def _seed_users() -> dict[str, str]:
    users_to_seed = (
        ("Ana Demonstração", f"ana{USER_SUFFIX}", "advogado"),
        ("Bruno Demonstração", f"bruno{USER_SUFFIX}", "secretario"),
        ("Carla Demonstração", f"carla{USER_SUFFIX}", "documentacao"),
    )
    seeded: dict[str, str] = {}
    for name, email, profile in users_to_seed:
        user = usuarios.criar_usuario(
            usuarios.NovoUsuario(nome=name, email=email, perfil=profile, senha=PASSWORD)
        )
        seeded[email] = str(user["id"])
    return seeded


def seed() -> None:
    _require_local_environment()
    banco.inicializar_schema()
    perfis.inicializar()
    usuarios.inicializar()
    tipos_documento.inicializar()
    _clean()
    seeded_users = _seed_users()
    ana_email = f"ana{USER_SUFFIX}"
    bruno_email = f"bruno{USER_SUFFIX}"
    cases = {
        "interview": _seed_case(
            "interview",
            "Cliente Entrevista",
            "doenca_ocupacional",
            2,
            "Ana Demonstração",
            seeded_users[ana_email],
            "none",
        ),
        "collection": _seed_case(
            "collection",
            "Cliente Coleta",
            "doenca_ocupacional",
            7,
            "Carla Demonstração",
            seeded_users[f"carla{USER_SUFFIX}"],
            "partial",
        ),
        "review": _seed_case(
            "review",
            "Cliente Conferência",
            "doenca_ocupacional",
            14,
            "Bruno Demonstração",
            seeded_users[bruno_email],
            "review",
        ),
        "contract": _seed_case(
            "contract",
            "Cliente Contrato",
            "doenca_ocupacional",
            21,
            "Ana Demonstração",
            seeded_users[ana_email],
            "complete",
        ),
        "complete-one": _seed_case(
            "complete-one",
            "Cliente Instruído Um",
            "doenca_ocupacional",
            34,
            "Ana Demonstração",
            seeded_users[ana_email],
            "complete",
            signed=True,
        ),
        "complete-two": _seed_case(
            "complete-two",
            "Cliente Instruído Dois",
            "doenca_ocupacional",
            48,
            "Bruno Demonstração",
            seeded_users[bruno_email],
            "complete",
            signed=True,
        ),
        "complete-three": _seed_case(
            "complete-three",
            "Cliente Instruído Três",
            "doenca_ocupacional",
            65,
            "Carla Demonstração",
            seeded_users[f"carla{USER_SUFFIX}"],
            "complete",
            signed=True,
        ),
    }
    request_id = armazenamento.registrar_solicitacao_peticao(
        cases["complete-one"], seeded_users[ana_email], "Ana Demonstração", "seed_development"
    )
    armazenamento.concluir_solicitacao_peticao(request_id)
    with banco.conectar() as connection:
        connection.execute(
            "UPDATE solicitacoes_peticao SET solicitada_em = ?, concluida_em = ? WHERE id = ?",
            (_timestamp(8), _timestamp(7.5), request_id),
        )
        connection.execute(
            "INSERT INTO automacoes_whatsapp "
            "(chave, tipo, caso_id, destino, status, tentativas, enviado_em, criado_em, atualizado_em) "
            "VALUES (?, 'cobranca_documentos', ?, ?, 'enviado', 1, ?, ?, ?)",
            (
                f"{CASE_PREFIX}automation-collection",
                cases["collection"],
                "91999990000",
                _timestamp(2),
                _timestamp(2),
                _timestamp(2),
            ),
        )
    _seed_conversation(cases["collection"], ana_email)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Popula o SQL Server local com dados sintéticos."
    )
    parser.add_argument(
        "--clean", action="store_true", help="Remove somente os dados criados pelo seeder."
    )
    parser.add_argument(
        "--confirm", action="store_true", help="Confirma a alteração do banco local."
    )
    arguments = parser.parse_args()
    if not arguments.confirm:
        parser.error("Use --confirm para alterar o banco local.")
    try:
        _require_local_environment()
        if arguments.clean:
            _clean()
            print("Dados sintéticos removidos do banco local.")
        else:
            seed()
            print("Dados sintéticos criados no banco local.")
            print(
                f"Contas de demonstração: ana{USER_SUFFIX}, bruno{USER_SUFFIX}, "
                f"carla{USER_SUFFIX}"
            )
            print(f"Senha de demonstração: {PASSWORD}")
    except RuntimeError as error:
        print(f"Seeder não executado: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
