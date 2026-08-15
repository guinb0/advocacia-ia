"""Barreira HTTP: contrato nenhum sai sem nome completo e CPF válido.

Além do status devolvido ao frontend, estes testes conferem os efeitos que não podem
acontecer: abrir o modelo DOCX, enviar bytes à ZapSign ou registrar uma assinatura local.
Tudo externo é falso; nenhuma chamada de rede é feita.

Rodar: .venv\Scripts\python.exe -m tests.test_contrato_api
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app import armazenamento, assinatura, contrato, main
from app.agente import rotas as rotas_agente
from tests.test_contrato import texto_do_docx


def checar(condicao: bool, descricao: str) -> bool:
    print(f"  {'PASS' if condicao else 'FALHA'} {descricao}")
    return condicao


CPF_VALIDO = "111.444.777-35"

# O corpo externo aceita ``dict[str, Any]``. Por isso os tipos estruturados também entram
# na matriz: juntar uma lista ou converter um objeto para texto faria um dado malformado
# parecer válido depois da coerção.
INVALIDOS: tuple[tuple[str, dict[str, Any], str], ...] = (
    ("nome ausente", {"cpf": CPF_VALIDO}, "nome completo"),
    ("nome vazio", {"nome": "   ", "cpf": CPF_VALIDO}, "nome completo"),
    ("nome com uma parte", {"nome": "Maria", "cpf": CPF_VALIDO}, "nome completo"),
    ("nome apenas com iniciais", {"nome": "A B", "cpf": CPF_VALIDO}, "nome completo"),
    ("iniciais pontuadas", {"nome": "M. S.", "cpf": CPF_VALIDO}, "nome completo"),
    ("nome sem sobrenome", {"nome": "Maria de", "cpf": CPF_VALIDO}, "nome completo"),
    ("nome com dígitos", {"nome": "Maria 123A", "cpf": CPF_VALIDO}, "nome completo"),
    (
        "nome estruturado",
        {"nome": {"primeiro": "Maria", "ultimo": "Silva"}, "cpf": CPF_VALIDO},
        "nome completo",
    ),
    ("CPF ausente", {"nome": "Maria da Silva"}, "CPF válido"),
    (
        "CPF com dígitos repetidos",
        {"nome": "Maria da Silva", "cpf": "111.111.111-11"},
        "CPF válido",
    ),
    (
        "CPF com verificador incorreto",
        {"nome": "Maria da Silva", "cpf": "123.456.789-00"},
        "CPF válido",
    ),
    ("CPF com letras", {"nome": "Maria da Silva", "cpf": "111x444x777x35"}, "CPF válido"),
    (
        "CPF estruturado",
        {"nome": "Maria da Silva", "cpf": ["111.444", "777-35"]},
        "CPF válido",
    ),
)


@contextmanager
def cliente_api() -> Iterator[TestClient]:
    # O lifespan aquece o OCR em uma thread; contrato não usa OCR, então o teste o corta.
    # A autenticação também é ortogonal à validação do corpo.
    with (
        patch.object(main, "_tentar_aquecer"),
        patch.object(main.auth, "ATIVA", False),
        TestClient(main.app, raise_server_exceptions=False) as cliente,
    ):
        yield cliente


def testar_download_bloqueado() -> int:
    falhas = 0
    print("\nPOST /api/contrato")

    # Se a validação regredir ou for movida para depois do preenchimento, esta sentinela
    # transforma a abertura do modelo em falha observável.
    with patch.object(
        contrato,
        "caminho_modelo",
        side_effect=AssertionError("o modelo não pode ser aberto para dados inválidos"),
    ) as modelo:
        with cliente_api() as cliente:
            for descricao, respostas, mensagem in INVALIDOS:
                modelo.reset_mock()
                resposta = cliente.post("/api/contrato", json={"respostas": respostas})
                detalhe = str(resposta.json().get("detail", ""))

                falhas += not checar(
                    resposta.status_code == 422,
                    f"{descricao}: a API recusa com 422 ({resposta.status_code})",
                )
                falhas += not checar(
                    mensagem in detalhe,
                    f"{descricao}: a resposta nomeia o requisito ({detalhe!r})",
                )
                falhas += not checar(
                    not modelo.called,
                    f"{descricao}: nenhum DOCX começa a ser produzido",
                )

    return falhas


def testar_assinatura_bloqueada() -> int:
    falhas = 0
    print("\nPOST /api/contrato/assinatura")

    # Os retornos posteriores são válidos de propósito. Se a barreira deixar um CPF ou nome
    # ruim passar, o fluxo consegue avançar até os spies e o teste prova o vazamento.
    resumo = {
        "doc_token": "doc-nao-deveria-existir",
        "estado": "pendente",
        "signatarios": [],
        "total": 1,
    }
    with (
        patch.object(assinatura, "ativa", return_value=True),
        patch.object(
            contrato,
            "caminho_modelo",
            side_effect=AssertionError("o modelo não pode ser aberto para dados inválidos"),
        ) as modelo,
        patch.object(assinatura, "enviar", new_callable=AsyncMock) as enviar,
        patch.object(assinatura, "casar_com_enviados", return_value={}),
        patch.object(assinatura, "resumir", return_value=resumo),
        patch.object(
            armazenamento,
            "registrar_assinatura",
            return_value={"id": "registro-nao-deveria-existir"},
        ) as registrar,
    ):
        with cliente_api() as cliente:
            for descricao, respostas, mensagem in INVALIDOS:
                modelo.reset_mock()
                enviar.reset_mock()
                registrar.reset_mock()
                corpo = {
                    "respostas": {**respostas, "email": "maria@exemplo.com"},
                    "signatarios": [],
                }
                resposta = cliente.post("/api/contrato/assinatura", json=corpo)
                detalhe = str(resposta.json().get("detail", ""))

                falhas += not checar(
                    resposta.status_code == 422,
                    f"{descricao}: a assinatura é recusada com 422 ({resposta.status_code})",
                )
                falhas += not checar(
                    mensagem in detalhe,
                    f"{descricao}: a resposta nomeia o requisito ({detalhe!r})",
                )
                falhas += not checar(
                    not modelo.called,
                    f"{descricao}: nenhum DOCX começa a ser produzido",
                )
                falhas += not checar(
                    enviar.await_count == 0,
                    f"{descricao}: nenhum byte é enviado à ZapSign",
                )
                falhas += not checar(
                    registrar.call_count == 0,
                    f"{descricao}: nenhuma assinatura é registrada localmente",
                )

    return falhas


def testar_download_valido() -> int:
    """A barreira não pode bloquear a identificação válida na borda HTTP."""
    print("\nidentificação válida")
    with cliente_api() as cliente:
        resposta = cliente.post(
            "/api/contrato",
            json={
                "respostas": {
                    "nome": "  Maria   da Silva  ",
                    "cpf": "11144477735",
                }
            },
        )

    correto = (
        resposta.status_code == 200
        and resposta.content.startswith(b"PK")
        and resposta.headers.get("content-type", "").startswith(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
    )
    return 0 if checar(correto, "nome completo e CPF válido ainda geram o DOCX") else 1


def testar_assinatura_valida() -> int:
    """O caminho feliz usa a identificação normalizada e não expõe o token."""
    print("\nassinatura válida")
    resumo = {
        "doc_token": "doc-valido",
        "estado": "pendente",
        "signatarios": [],
        "total": 1,
    }
    registro = {
        "id": "assinatura-valida",
        "doc_token": "doc-valido",
        "nome": "Contrato de honorários — Maria da Silva",
        "cliente": "Maria da Silva",
        "cpf": "11144477735",
        "estado": "pendente",
        "signatarios": [],
    }
    with (
        patch.object(assinatura, "ativa", return_value=True),
        patch.object(assinatura, "enviar", new_callable=AsyncMock) as enviar,
        patch.object(assinatura, "casar_com_enviados", return_value={}),
        patch.object(assinatura, "resumir", return_value=resumo),
        patch.object(armazenamento, "registrar_assinatura", return_value=registro) as registrar,
        patch.object(
            main.dossie_agente,
            "montar",
            return_value=_dossie(
                "Maria da Silva",
                [
                    _campo("CPF", CPF_VALIDO),
                    _campo("Nome no documento", "MARIA DA SILVA"),
                ],
            ),
        ),
        cliente_api() as cliente,
    ):
        resposta = cliente.post(
            "/api/contrato/assinatura",
            json={
                "respostas": {
                    "nome": "  Maria   da Silva  ",
                    "cpf": "11144477735",
                    "email": "maria@exemplo.com",
                },
                "signatarios": [],
                "caso_id": "caso-1",
            },
        )

    falhas = 0
    falhas += not checar(resposta.status_code == 201, "pedido válido cria a assinatura")
    falhas += not checar(enviar.await_count == 1, "o DOCX válido é enviado uma única vez")
    docx_enviado = enviar.await_args.args[1]
    texto = texto_do_docx(docx_enviado)
    falhas += not checar(
        "Maria da Silva" in texto and "111.444.777-35" in texto,
        "nome e CPF normalizados entram no DOCX enviado",
    )
    falhas += not checar(
        registrar.call_args.kwargs["cliente"] == "Maria da Silva",
        "a chave local da assinatura usa o nome normalizado",
    )
    falhas += not checar(
        registrar.call_args.kwargs["caso_id"] == "caso-1",
        "a identidade correspondente pode ser vinculada ao caso",
    )
    falhas += not checar(
        not {"doc_token", "cpf"} & resposta.json().get("assinatura", {}).keys(),
        "token da ZapSign e CPF de correlação não vazam na resposta",
    )
    return falhas


def _campo(rotulo: str, valor: str, status_fato: str = "CONFIRMED") -> dict[str, Any]:
    return {
        "rotulo": rotulo,
        "valor": valor,
        "status": status_fato,
        "confianca": 1,
        "fontes": ["documento"],
    }


def _dossie(nome: str, campos: list[dict[str, Any]]) -> dict[str, Any]:
    return {"cliente": {"nome": nome, "campos": campos}}


def _sem_cpf_na_mensagem(detalhe: str) -> bool:
    digitos = "".join(c for c in detalhe if c.isdigit())
    return "11144477735" not in digitos and "52998224725" not in digitos


def testar_assinatura_com_caso_exige_identidade_atual() -> int:
    """Caso informado não pode receber contrato de homônimo ou de outro CPF."""
    print("\nassinatura vinculada ao caso")
    falhas = 0
    identidade_atual = _dossie(
        "Maria da Silva",
        [
            _campo("CPF", CPF_VALIDO),
            _campo("Nome no documento", "MARIA DA SILVA"),
        ],
    )
    cenarios = (
        (
            "CPF de outro cliente",
            {"nome": "Maria da Silva", "cpf": "529.982.247-25"},
            identidade_atual,
        ),
        (
            "nome de outro cliente",
            {"nome": "Joana da Silva", "cpf": CPF_VALIDO},
            identidade_atual,
        ),
        (
            "identidade atual ambígua",
            {"nome": "Maria da Silva", "cpf": CPF_VALIDO},
            _dossie(
                "Maria da Silva",
                [
                    _campo("CPF", CPF_VALIDO),
                    _campo("CPF", "529.982.247-25"),
                ],
            ),
        ),
    )

    with (
        patch.object(assinatura, "ativa", return_value=True),
        patch.object(
            contrato,
            "caminho_modelo",
            side_effect=AssertionError("identidade divergente não pode abrir o modelo"),
        ) as modelo,
        patch.object(assinatura, "enviar", new_callable=AsyncMock) as enviar,
        patch.object(armazenamento, "registrar_assinatura") as registrar,
        cliente_api() as cliente,
    ):
        for descricao, identificacao, montado in cenarios:
            modelo.reset_mock()
            enviar.reset_mock()
            registrar.reset_mock()
            with patch.object(main.dossie_agente, "montar", return_value=montado):
                resposta = cliente.post(
                    "/api/contrato/assinatura",
                    json={
                        "respostas": {
                            **identificacao,
                            "email": "cliente@exemplo.com",
                        },
                        "caso_id": "caso-1",
                    },
                )

            detalhe = str(resposta.json().get("detail", ""))
            falhas += not checar(
                resposta.status_code == 409,
                f"{descricao}: a assinatura é bloqueada ({resposta.status_code})",
            )
            falhas += not checar(
                _sem_cpf_na_mensagem(detalhe),
                f"{descricao}: a resposta não expõe CPF ({detalhe!r})",
            )
            falhas += not checar(
                not modelo.called and enviar.await_count == 0 and registrar.call_count == 0,
                f"{descricao}: não gera, envia nem persiste assinatura",
            )

    return falhas


def testar_vinculo_posterior_exige_identidade_atual() -> int:
    """O vínculo manual posterior aplica a mesma autoridade do Case State."""
    print("\nvínculo posterior da assinatura")
    falhas = 0
    identidade_atual = _dossie(
        "Maria da Silva",
        [
            _campo("CPF", CPF_VALIDO),
            _campo("Nome no documento", "MARIA DA SILVA"),
        ],
    )
    base = {
        "id": "assinatura-1",
        "cliente": "Maria da Silva",
        "cpf": "11144477735",
    }
    cenarios = (
        ("CPF de outro cliente", {**base, "cpf": "52998224725"}, identidade_atual),
        ("nome de outro cliente", {**base, "cliente": "Joana da Silva"}, identidade_atual),
        (
            "identidade atual ambígua",
            base,
            _dossie(
                "Maria da Silva",
                [
                    _campo("CPF", CPF_VALIDO),
                    _campo("CPF", "529.982.247-25"),
                ],
            ),
        ),
    )

    with (
        patch.object(armazenamento, "obter_assinatura") as obter,
        patch.object(armazenamento, "vincular_assinatura_ao_caso", return_value=True) as vincular,
        cliente_api() as cliente,
    ):
        for descricao, registro, montado in cenarios:
            obter.return_value = registro
            vincular.reset_mock()
            with patch.object(main.dossie_agente, "montar", return_value=montado):
                resposta = cliente.post(
                    "/api/assinaturas/assinatura-1/caso",
                    data={"caso_id": "caso-1"},
                )

            detalhe = str(resposta.json().get("detail", ""))
            falhas += not checar(
                resposta.status_code == 409,
                f"{descricao}: o vínculo é bloqueado ({resposta.status_code})",
            )
            falhas += not checar(
                _sem_cpf_na_mensagem(detalhe),
                f"{descricao}: a resposta não expõe CPF ({detalhe!r})",
            )
            falhas += not checar(
                vincular.call_count == 0,
                f"{descricao}: nada é gravado",
            )

        obter.return_value = base
        vincular.reset_mock()
        with patch.object(main.dossie_agente, "montar", return_value=identidade_atual):
            resposta = cliente.post(
                "/api/assinaturas/assinatura-1/caso",
                data={"caso_id": "caso-1"},
            )
        falhas += not checar(
            resposta.status_code == 200 and resposta.json() == {"vinculado": True},
            "identidade correspondente permite o vínculo",
        )
        falhas += not checar(
            vincular.call_count == 1,
            "o vínculo válido é persistido uma vez",
        )

    return falhas


def testar_contrato_case_aware() -> int:
    """A rota do dossiê relê fatos atuais e não confia em um corpo do navegador."""
    print("\ncontrato do caso")
    falhas = 0
    cenarios = (
        ("CPF ausente", _dossie("Maria da Silva", []), "CPF válido"),
        (
            "CPFs divergentes",
            _dossie(
                "Maria da Silva",
                [_campo("CPF", CPF_VALIDO), _campo("CPF", "529.982.247-25")],
            ),
            "CPFs divergentes",
        ),
        (
            "CPF válido ao lado de fato em formato inválido",
            _dossie(
                "Maria da Silva",
                [_campo("CPF", CPF_VALIDO), _campo("CPF", "111x444x777x35")],
            ),
            "formato inválido",
        ),
        (
            "CPF contestado",
            _dossie("Maria da Silva", [_campo("CPF", CPF_VALIDO, "CONTESTED")]),
            "CPF está contestado",
        ),
        (
            "nome divergente",
            _dossie(
                "Maria da Silva",
                [_campo("CPF", CPF_VALIDO), _campo("Nome no documento", "Joana da Silva")],
            ),
            "nome do cadastro diverge",
        ),
    )

    with patch.object(
        contrato,
        "caminho_modelo",
        side_effect=AssertionError("dados inconsistentes não podem abrir o modelo"),
    ) as modelo:
        with cliente_api() as cliente:
            for descricao, montado, mensagem in cenarios:
                modelo.reset_mock()
                with patch.object(rotas_agente.dossie, "montar", return_value=montado):
                    resposta = cliente.post(
                        "/api/agente/casos/caso-1/contrato",
                        # Mesmo um corpo válido não pode substituir o Case State.
                        json={"nome": "Pessoa Arbitrária", "cpf": CPF_VALIDO},
                    )
                detalhe = str(resposta.json().get("detail", ""))
                falhas += not checar(
                    resposta.status_code == 422,
                    f"{descricao}: o Case State bloqueia a geração ({resposta.status_code})",
                )
                falhas += not checar(
                    mensagem in detalhe,
                    f"{descricao}: o motivo é explícito ({detalhe!r})",
                )
                falhas += not checar(
                    not modelo.called,
                    f"{descricao}: o modelo não é aberto",
                )

    valido = _dossie(
        "Maria da Silva",
        [
            _campo("CPF", CPF_VALIDO),
            _campo("CPF", "11144477735"),
            _campo("CPF", "529.982.247-25", "REJECTED"),
            _campo("Nome no documento", "MARIA DA SILVA"),
        ],
    )
    with (
        patch.object(rotas_agente.dossie, "montar", return_value=valido),
        cliente_api() as cliente,
    ):
        resposta = cliente.post("/api/agente/casos/caso-1/contrato")
    falhas += not checar(
        resposta.status_code == 200 and resposta.content.startswith(b"PK"),
        "CPF repetido igual e fato rejeitado não bloqueiam o contrato do caso",
    )
    return falhas


def main_teste() -> int:
    falhas = testar_download_bloqueado()
    falhas += testar_assinatura_bloqueada()
    falhas += testar_download_valido()
    falhas += testar_assinatura_valida()
    falhas += testar_assinatura_com_caso_exige_identidade_atual()
    falhas += testar_vinculo_posterior_exige_identidade_atual()
    falhas += testar_contrato_case_aware()
    print(f"\n{'TODOS OS TESTES PASSARAM' if not falhas else f'{falhas} FALHA(S)'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
