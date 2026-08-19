"""Criação de usuários e perfis do escritório.

POR QUE NO KEYCLOAK, E NÃO NUMA TABELA DAQUI

A identidade já mora lá: é o Keycloak que emite o token que este backend valida
(`app/auth.py`), e desde que ele passou a gravar no SQL Server do escritório a
conta criada numa máquina vale em todas. Uma tabela `usuarios` local seria uma
segunda verdade sobre quem existe — e as duas divergem no primeiro cadastro
feito pelo console.

POR QUE TÃO POUCOS CAMPOS

Conta se cria no meio do atendimento, com o cliente esperando. Nome, e-mail,
perfil e senha bastam para entrar; o resto (CPF, endereço, telefone) o cadastro
do CASO já coleta, e pedir duas vezes é a forma mais rápida de ninguém preencher
nenhuma das duas.

O e-mail é o nome de usuário. Ter os dois separados obrigaria a inventar um
apelido na hora, que é justamente a decisão que trava quem está cadastrando.

OS DOIS PERFIS

`advogado` conduz entrevista, gera documento e cadastra gente. `cliente` só
acompanha o próprio caso e envia documento. Quem cadastra precisa ser advogado —
um cliente que pudesse criar contas criaria acesso ao acervo do escritório.
"""

from __future__ import annotations

import logging
import os
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .auth import exigir_papel

log = logging.getLogger("usuarios")

roteador = APIRouter(prefix="/api/usuarios", tags=["usuarios"])

TIMEOUT = 20.0

#: Os perfis que o escritório usa. É lista fechada de propósito: papel novo no
#: Keycloak sem código que o entenda vira acesso que ninguém sabe explicar.
PERFIS: tuple[dict[str, str], ...] = (
    {
        "codigo": "advogado",
        "rotulo": "Advogado",
        "descricao": "Conduz entrevistas, gera documentos e cadastra usuários.",
    },
    {
        "codigo": "cliente",
        "rotulo": "Cliente",
        "descricao": "Acompanha o próprio caso e envia documentos.",
    },
)
CODIGOS = tuple(p["codigo"] for p in PERFIS)

SoAdvogado = Depends(exigir_papel("advogado"))


def _env(nome: str, padrao: str = "") -> str:
    return (os.getenv(nome, padrao) or "").strip()


def _base() -> str:
    url = _env("KEYCLOAK_URL")
    if not url:
        raise HTTPException(
            503,
            "Cadastro de usuários indisponível: a autenticação está desligada "
            "(KEYCLOAK_URL vazia). Suba o Keycloak e rode sem -SemAuth.",
        )
    return url.rstrip("/")


def _realm() -> str:
    return _env("KEYCLOAK_REALM", "advocacia")


async def _token_admin(http: httpx.AsyncClient) -> str:
    """Credencial de administração do Keycloak, vinda do `.env`.

    Fica separada da senha de qualquer pessoa: quem administra o realm não é um
    usuário do escritório, é o serviço. Sem ela configurada a rota falha dizendo
    o que falta, em vez de devolver o 401 do Keycloak e mandar procurar no lugar
    errado.
    """
    usuario = _env("KEYCLOAK_ADMIN_USER", "admin")
    senha = _env("KEYCLOAK_ADMIN_PASSWORD")
    if not senha:
        raise HTTPException(
            503,
            "Falta KEYCLOAK_ADMIN_PASSWORD no .env — sem ela o servidor não pode "
            "criar usuários no Keycloak.",
        )
    resposta = await http.post(
        f"{_base()}/realms/master/protocol/openid-connect/token",
        data={
            "client_id": "admin-cli",
            "username": usuario,
            "password": senha,
            "grant_type": "password",
        },
    )
    if resposta.status_code != 200:
        raise HTTPException(502, "O Keycloak recusou a credencial de administração.")
    return str(resposta.json()["access_token"])


class NovoUsuario(BaseModel):
    """O mínimo para alguém entrar. Ver o cabeçalho para o porquê de ser tão pouco."""

    model_config = ConfigDict(extra="forbid")

    nome: Annotated[str, Field(min_length=3, max_length=120)]
    #: Padrão simples de propósito, em vez do `EmailStr` do pydantic: ele exige o
    #: pacote `email-validator`, e uma dependência nova no requirements obrigaria
    #: todo mundo do time a reinstalar o ambiente por causa de um campo. Aqui o
    #: e-mail serve de nome de usuário — o que importa é ter formato de e-mail e
    #: ser único, não passar pelo RFC inteiro.
    email: Annotated[
        str, Field(min_length=5, max_length=160, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
    ]
    perfil: Annotated[str, Field(pattern="^(advogado|cliente)$")]
    #: 8 é o mínimo que não é teatro. Trocar depois é pelo próprio Keycloak.
    senha: Annotated[str, Field(min_length=8, max_length=128)]


@roteador.get("/perfis")
def listar_perfis() -> dict[str, Any]:
    """Os perfis que a tela oferece. Sem token: é vocabulário, não dado de ninguém."""
    return {"perfis": list(PERFIS)}


@roteador.get("", dependencies=[SoAdvogado])
async def listar_usuarios() -> dict[str, Any]:
    """Quem já existe, com o perfil de cada um."""
    async with httpx.AsyncClient(timeout=TIMEOUT) as http:
        cabecalho = {"Authorization": f"Bearer {await _token_admin(http)}"}
        pessoas = (
            await http.get(
                f"{_base()}/admin/realms/{_realm()}/users",
                headers=cabecalho,
                params={"max": 500, "briefRepresentation": False},
            )
        ).json()

        itens = []
        for pessoa in pessoas:
            papeis = (
                await http.get(
                    f"{_base()}/admin/realms/{_realm()}/users/{pessoa['id']}"
                    "/role-mappings/realm",
                    headers=cabecalho,
                )
            ).json()
            nome = " ".join(
                x for x in (pessoa.get("firstName"), pessoa.get("lastName")) if x
            )
            itens.append(
                {
                    "id": pessoa["id"],
                    "usuario": pessoa.get("username"),
                    "nome": nome or pessoa.get("username"),
                    "email": pessoa.get("email"),
                    "ativo": bool(pessoa.get("enabled")),
                    "perfis": [p["name"] for p in papeis if p["name"] in CODIGOS],
                }
            )
    itens.sort(key=lambda i: (i["nome"] or "").casefold())
    return {"itens": itens, "total": len(itens)}


@roteador.post("", status_code=201, dependencies=[SoAdvogado])
async def criar_usuario(pedido: NovoUsuario) -> dict[str, Any]:
    """Cria a conta e já deixa entrar — sem etapa de ativação.

    A senha vai como DEFINITIVA, e não temporária, porque a tela do Acervo não
    conduz o fluxo de "troque a senha no primeiro acesso" do Keycloak: marcada
    como temporária, o login não completa, e o sintoma é uma conta nova que não
    entra sem dizer por quê.
    """
    partes = pedido.nome.strip().split()
    primeiro, ultimo = partes[0], " ".join(partes[1:])
    email = str(pedido.email).lower()

    async with httpx.AsyncClient(timeout=TIMEOUT) as http:
        cabecalho = {
            "Authorization": f"Bearer {await _token_admin(http)}",
            "Content-Type": "application/json",
        }
        criacao = await http.post(
            f"{_base()}/admin/realms/{_realm()}/users",
            headers=cabecalho,
            json={
                "username": email,
                "email": email,
                "firstName": primeiro,
                "lastName": ultimo,
                "enabled": True,
                # Sem servidor de e-mail configurado, exigir verificação deixaria
                # toda conta nova barrada num e-mail que nunca chega.
                "emailVerified": True,
            },
        )
        if criacao.status_code == 409:
            raise HTTPException(409, f"Já existe usuário com o e-mail {email}.")
        if criacao.status_code != 201:
            log.error(
                "Keycloak recusou a criação: %s %s",
                criacao.status_code,
                criacao.text[:300],
            )
            raise HTTPException(502, "O Keycloak recusou a criação do usuário.")

        uid = criacao.headers["Location"].rsplit("/", 1)[1]

        senha = await http.put(
            f"{_base()}/admin/realms/{_realm()}/users/{uid}/reset-password",
            headers=cabecalho,
            json={"type": "password", "value": pedido.senha, "temporary": False},
        )
        papel = await http.get(
            f"{_base()}/admin/realms/{_realm()}/roles/{pedido.perfil}",
            headers=cabecalho,
        )
        vinculo = await http.post(
            f"{_base()}/admin/realms/{_realm()}/users/{uid}/role-mappings/realm",
            headers=cabecalho,
            json=[{"id": papel.json()["id"], "name": pedido.perfil}],
        )

        # Conta sem senha ou sem perfil é pior que conta nenhuma: aparece na
        # lista, parece pronta e não entra. Desfaz em vez de deixar pela metade.
        if senha.status_code >= 300 or vinculo.status_code >= 300:
            await http.delete(
                f"{_base()}/admin/realms/{_realm()}/users/{uid}", headers=cabecalho
            )
            raise HTTPException(
                502,
                "Usuário criado sem senha ou sem perfil; foi desfeito. Tente de novo.",
            )

    log.info("usuario criado: %s (%s)", email, pedido.perfil)
    return {
        "id": uid,
        "usuario": email,
        "nome": pedido.nome.strip(),
        "perfil": pedido.perfil,
        "ativo": True,
    }
