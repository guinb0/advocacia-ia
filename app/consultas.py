"""Consultas a bases públicas para adiantar o preenchimento da entrevista.

Hoje só CEP → endereço. É o único campo do roteiro que uma base pública e
gratuita resolve de verdade, e resolve bem: digitado o CEP, saem logradouro,
bairro, cidade e UF, e a atendente só confirma número e complemento com o
cliente. Em oito dígitos ela deixa de datilografar quatro campos.

O QUE NÃO DÁ PARA FAZER, e é bom estar escrito:

- **CPF não vira nome — de graça.** Não existe API pública e gratuita que devolva
  os dados de um CPF, e os sites que prometem isso vendem base vazada: usar uma
  delas põe o escritório do lado errado da LGPD. A consulta oficial é a da
  Receita pelo Conecta gov.br, e ela **está implementada aqui** (`buscar_cpf`) —
  exige credencial, que é assunto de convênio e não de código. Sem credencial o
  caminho fica inerte e o CPF continua servindo só para conferir o dígito
  verificador (ver `validators.validar_cpf`).
- **PIS/NIT não vira vínculo.** O CNIS é do INSS e pede procuração e login gov.br
  do próprio cliente — não é consulta de servidor.

Por que passa pelo nosso backend, e não direto do navegador:

1. O provedor pode cair. Com dois (BrasilAPI e ViaCEP), a queda de um não trava a
   entrevista — e a troca fica num lugar só.
2. Cache. O mesmo CEP é consultado várias vezes por dia num escritório; guardar
   evita bater na base pública a cada tecla.
3. O navegador do advogado não fala com terceiros. Sai daqui apenas o CEP —
   nenhum nome, CPF ou identificador do caso acompanha a consulta.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from typing import Any

import httpx

log = logging.getLogger("consultas")

TEMPO_LIMITE_S = 4.0
#: Cache simples de processo. CEP muda com obra na cidade, não durante o dia.
LIMITE_CACHE = 2_000

_cache: dict[str, dict[str, Any]] = {}
_trava = threading.Lock()


class ErroConsulta(Exception):
    """Falha que o usuário precisa ver — CEP inexistente ou base fora do ar."""


def normalizar_cep(cep: str) -> str:
    return re.sub(r"\D", "", cep or "")


def formatar_cep(cep: str) -> str:
    d = normalizar_cep(cep)
    return f"{d[:5]}-{d[5:]}" if len(d) == 8 else cep


def _montar_endereco(logradouro: str, bairro: str, cidade: str, uf: str, cep: str) -> str:
    """O texto que cai no campo de endereço do roteiro.

    O número fica marcado como pendente de propósito: o CEP não o entrega, e um
    endereço sem número não serve para citação nem para petição. Melhor um
    espaço visível para preencher do que um endereço que parece completo.
    """
    partes = [p for p in (logradouro, "nº ___") if p]
    resto = [p for p in (bairro, f"{cidade}/{uf}".strip("/"), f"CEP {formatar_cep(cep)}") if p]
    return ", ".join([", ".join(partes), *resto]) if partes else ", ".join(resto)


def _da_brasilapi(dados: dict[str, Any]) -> dict[str, Any]:
    return {
        "cep": formatar_cep(dados.get("cep", "")),
        "logradouro": (dados.get("street") or "").strip(),
        "bairro": (dados.get("neighborhood") or "").strip(),
        "cidade": (dados.get("city") or "").strip(),
        "uf": (dados.get("state") or "").strip(),
        "fonte": "BrasilAPI",
    }


def _do_viacep(dados: dict[str, Any]) -> dict[str, Any]:
    return {
        "cep": formatar_cep(dados.get("cep", "")),
        "logradouro": (dados.get("logradouro") or "").strip(),
        "bairro": (dados.get("bairro") or "").strip(),
        "cidade": (dados.get("localidade") or "").strip(),
        "uf": (dados.get("uf") or "").strip(),
        "fonte": "ViaCEP",
    }


def limpar_cache() -> None:
    with _trava:
        _cache.clear()


async def _tentar_provedores(
    http: httpx.AsyncClient, d: str
) -> tuple[dict[str, Any] | None, bool]:
    """Devolve (endereço, cep_inexistente). O segundo separa 'não existe' de
    'não respondeu' — a mensagem na tela é bem diferente nos dois casos."""
    inexistente = False
    for url, converter in (
        (f"https://brasilapi.com.br/api/cep/v2/{d}", _da_brasilapi),
        (f"https://viacep.com.br/ws/{d}/json/", _do_viacep),
    ):
        try:
            r = await http.get(url)
            if r.status_code == 404:
                inexistente = True
                continue
            r.raise_for_status()
            corpo = r.json()
            # O ViaCEP responde 200 com {"erro": true} para CEP inexistente.
            if isinstance(corpo, dict) and str(corpo.get("erro", "")).lower() in ("true", "1"):
                inexistente = True
                continue
            return converter(corpo), inexistente
        except Exception as exc:
            log.warning("Consulta de CEP falhou em %s: %s", url, str(exc)[:120])
    return None, inexistente


async def buscar_cep(cep: str, http: httpx.AsyncClient | None = None) -> dict[str, Any]:
    """Endereço do CEP, do primeiro provedor que responder.

    Levanta `ErroConsulta` quando o CEP não existe em nenhuma das bases ou
    quando as duas estão inacessíveis — a mensagem é para a tela.

    `http` existe para o teste injetar um transporte falso: bater na base
    pública de verdade faria a suíte depender de rede e do humor de terceiros.
    """
    d = normalizar_cep(cep)
    if len(d) != 8:
        raise ErroConsulta("CEP precisa ter 8 dígitos.")

    with _trava:
        if d in _cache:
            return _cache[d]

    if http is not None:
        achado, inexistente = await _tentar_provedores(http, d)
    else:
        async with httpx.AsyncClient(timeout=TEMPO_LIMITE_S) as cliente:
            achado, inexistente = await _tentar_provedores(cliente, d)

    if achado is None:
        if inexistente:
            raise ErroConsulta("CEP não encontrado. Confira o número com o cliente.")
        raise ErroConsulta("As bases de CEP não responderam. Preencha o endereço à mão.")

    achado["endereco_formatado"] = _montar_endereco(
        achado["logradouro"], achado["bairro"], achado["cidade"], achado["uf"], d
    )

    with _trava:
        if len(_cache) >= LIMITE_CACHE:
            _cache.clear()  # cache de escritório: esvaziar é mais barato que LRU
        _cache[d] = achado
    return achado


# ----------------------------------------------------- CPF → qualificação
#
# A CONSULTA OFICIAL DA RECEITA, PELO CONECTA GOV.BR
#
# `api-cpf-light/v2` do Serpro, sobre a base CPF/CBC da Receita. É o que fecha o
# buraco descrito no topo deste arquivo: com ela o CPF deixa de ser só um dígito
# verificador e passa a preencher nome, nome da mãe, nascimento, endereço e
# telefone — justamente os campos que o roteiro obriga a DIGITAR antes de abrir
# o microfone, porque "número, nome próprio e nome de cidade a transcrição erra".
#
# TRÊS DECISÕES QUE VALEM MAIS QUE O CÓDIGO
#
# 1. **Nada é sobrescrito.** A consulta preenche campo VAZIO e só. Quem digitou
#    tinha o cliente na linha, e a Receita pode estar desatualizada — o endereço
#    de dois anos atrás não vale mais que o que o cliente acabou de ditar.
# 2. **Não há cache.** O CEP é dado público e repetido; isto é dado pessoal de
#    cidadão identificado. Guardar em memória de processo o que a Receita
#    devolveu, para poupar uma chamada, aumenta a superfície de vazamento em
#    troca de milissegundos.
# 3. **Nada disso vai para o log.** Nem o CPF consultado, nem o que voltou. O
#    log diz se deu certo e qual foi o erro do gateway, mais nada.
#
# O QUE FALTA CONFIRMAR QUANDO A CREDENCIAL SAIR
#
# O contrato de entrada e saída abaixo é o publicado (v2.5.0). O que o manual do
# Conecta define caso a caso é a AUTENTICAÇÃO do gateway: há instalação com
# token estático e há instalação com OAuth2 `client_credentials`. As duas estão
# contempladas (`_token_conecta`), e qual vale se decide pelo `.env` — sem a
# credencial em mãos, escolher uma e apagar a outra seria adivinhação.

#: Ambiente do Conecta. Homologação é o padrão DE PROPÓSITO: subir isto apontado
#: para produção por esquecimento consultaria dado real de cidadão.
CONECTA_BASE = os.getenv(
    "CONECTA_CPF_URL",
    "https://h-apigateway.conectagov.np.estaleiro.serpro.gov.br/api-cpf-light/v2",
).rstrip("/")

#: Token pronto (Bearer), quando o órgão já o entrega assim.
CONECTA_TOKEN = os.getenv("CONECTA_CPF_TOKEN", "").strip()

#: OAuth2 `client_credentials`. Só usado quando não há token pronto.
CONECTA_TOKEN_URL = os.getenv("CONECTA_TOKEN_URL", "").strip()
CONECTA_CLIENT_ID = os.getenv("CONECTA_CLIENT_ID", "").strip()
CONECTA_CLIENT_SECRET = os.getenv("CONECTA_CLIENT_SECRET", "").strip()

#: O gateway exige identificar QUEM está consultando. Vai no `x-cpf-usuario` e é
#: o que sustenta a auditoria do Termo de Responsabilidade assinado.
CONECTA_CPF_USUARIO = re.sub(r"\D", "", os.getenv("CONECTA_CPF_USUARIO", ""))

TEMPO_LIMITE_CPF_S = 8.0

#: Situação cadastral: o que ela é, e o que dizer na tela quando não for regular.
#: Não bloqueia nada — quem decide se segue é quem está atendendo.
SITUACAO_CADASTRAL = {
    "0": ("regular", ""),
    "2": ("suspensa", "O CPF está SUSPENSO na Receita (inconsistência cadastral)."),
    "3": ("titular falecido", "A Receita registra ÓBITO para este CPF."),
    "4": ("pendente de regularização", "O CPF está pendente de regularização na Receita."),
    "5": ("cancelada por multiplicidade", "O CPF foi cancelado por multiplicidade de inscrição."),
    "8": ("nula", "A inscrição é NULA — a Receita constatou fraude."),
    "9": ("cancelada de ofício", "A inscrição foi cancelada de ofício."),
}


def cpf_configurado() -> bool:
    """Há credencial para consultar. Sem isto o caminho inteiro fica inerte."""
    return bool(CONECTA_TOKEN or (CONECTA_TOKEN_URL and CONECTA_CLIENT_ID))


def normalizar_cpf(cpf: str) -> str:
    return re.sub(r"\D", "", cpf or "")


def _data_br(aaaammdd: str) -> str:
    """O `AAAAMMDD` da Receita vira `dd/mm/aaaa`, que é como o roteiro escreve."""
    d = re.sub(r"\D", "", aaaammdd or "")
    return f"{d[6:8]}/{d[4:6]}/{d[:4]}" if len(d) == 8 else ""


def _endereco_da_receita(dados: dict[str, Any]) -> str:
    """O endereço num campo só, como o roteiro e o contrato o querem.

    Ao contrário do CEP, aqui o número VEM — então nada de "nº ___". O
    complemento entra quando existe; vazio é o caso comum e não merece vírgula.
    """
    via = " ".join(
        p
        for p in (
            (dados.get("tipoLogradouro") or "").strip(),
            (dados.get("logradouro") or "").strip(),
        )
        if p
    )
    numero = (dados.get("numeroLogradouro") or "").strip()
    inicio = ", ".join(p for p in (via, f"nº {numero}" if numero else "") if p)
    resto = [
        (dados.get("complemento") or "").strip(),
        (dados.get("bairro") or "").strip(),
        "/".join(
            p
            for p in (
                (dados.get("municipio") or "").strip(),
                (dados.get("uf") or "").strip(),
            )
            if p
        ),
        f"CEP {formatar_cep(dados.get('cep', ''))}" if dados.get("cep") else "",
    ]
    return ", ".join(p for p in (inicio, *resto) if p)


def _telefone_da_receita(dados: dict[str, Any]) -> str:
    ddd = re.sub(r"\D", "", str(dados.get("ddd") or ""))
    numero = re.sub(r"\D", "", str(dados.get("telefone") or ""))
    if not numero:
        return ""
    return f"({ddd}) {numero}" if ddd else numero


async def _token_conecta(http: httpx.AsyncClient) -> str:
    """O Bearer do gateway: pronto do ambiente, ou trocado por client_credentials."""
    if CONECTA_TOKEN:
        return CONECTA_TOKEN
    resposta = await http.post(
        CONECTA_TOKEN_URL,
        data={"grant_type": "client_credentials"},
        auth=(CONECTA_CLIENT_ID, CONECTA_CLIENT_SECRET),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    resposta.raise_for_status()
    token = str(resposta.json().get("access_token") or "").strip()
    if not token:
        raise ErroConsulta("O Conecta não devolveu token de acesso.")
    return token


def _qualificacao(dados: dict[str, Any]) -> dict[str, Any]:
    """O que a Receita devolveu, já nos ids das perguntas do roteiro.

    Só o que o roteiro pergunta. A **ocupação** fica de fora de propósito: a
    ocupação principal da Receita vem da declaração e envelhece — num caso
    trabalhista, preencher "profissão" com ela sugeriria função que o cliente
    talvez não exerça há anos, e é a função que sustenta o pedido.

    O `nomeSocial` vence o nome quando existe: a própria Receita diz que é por
    ele que a pessoa deve ser chamada. O nome de registro volta à parte, para o
    contrato, que é documento de qualificação civil.
    """
    social = (dados.get("nomeSocial") or "").strip()
    nome = (dados.get("nome") or "").strip()
    campos = {
        "nome": social or nome,
        "mae": (dados.get("nomeMae") or "").strip(),
        "nascimento": _data_br(str(dados.get("dataNascimento") or "")),
        "uf": (dados.get("uf") or "").strip(),
        "municipio": (dados.get("municipio") or "").strip(),
        "endereco": _endereco_da_receita(dados),
        "telefone": _telefone_da_receita(dados),
    }
    pais = (dados.get("nomePaisNacionalidade") or "").strip().upper()
    if pais in ("BRASIL", "BRASILEIRO", "BRASILEIRA"):
        campos["nacionalidade"] = "Brasileira"
    return {chave: valor for chave, valor in campos.items() if valor}


async def buscar_cpf(cpf: str, http: httpx.AsyncClient | None = None) -> dict[str, Any]:
    """Qualificação do cidadão a partir do CPF, pela Receita (Conecta gov.br).

    Devolve `campos` já nos ids das perguntas do roteiro, prontos para preencher
    o que estiver em branco — e só o que estiver em branco, decisão de quem
    chama —, mais a situação cadastral e o aviso correspondente.

    Levanta `ErroConsulta` com mensagem para a tela. Sem credencial, CPF
    inválido, CPF não encontrado e gateway fora do ar são coisas diferentes, e
    quem está atendendo precisa saber qual delas aconteceu.

    `http` existe para o teste injetar transporte falso: bater no gateway de
    verdade faria a suíte depender de credencial e de rede.
    """
    if not cpf_configurado():
        raise ErroConsulta(
            "A consulta à Receita não está configurada: falta a credencial do "
            "Conecta gov.br no .env (CONECTA_CPF_TOKEN ou CONECTA_CLIENT_ID)."
        )
    d = normalizar_cpf(cpf)
    if len(d) != 11:
        raise ErroConsulta("CPF precisa ter 11 dígitos.")

    proprio = http is None
    http = http or httpx.AsyncClient(timeout=TEMPO_LIMITE_CPF_S)
    try:
        token = await _token_conecta(http)
        resposta = await http.post(
            f"{CONECTA_BASE}/consulta/cpf",
            json={"listaCPF": [d]},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "x-cpf-usuario": CONECTA_CPF_USUARIO,
            },
        )
        if resposta.status_code in (401, 403):
            raise ErroConsulta(
                "A Receita recusou a credencial do Conecta — confira a chave e o "
                "Termo de Responsabilidade."
            )
        resposta.raise_for_status()
        corpo = resposta.json()
    except ErroConsulta:
        raise
    except Exception as exc:
        # Sem o CPF na mensagem: log de erro não é lugar de dado pessoal.
        log.warning("Consulta de CPF falhou: %s", str(exc)[:160])
        raise ErroConsulta(
            "A base da Receita não respondeu. A entrevista continua normalmente "
            "e os campos podem ser preenchidos à mão."
        ) from exc
    finally:
        if proprio:
            await http.aclose()

    # A rota é de LISTA: devolve um item por CPF pedido, e pedimos um.
    itens: Any = corpo
    if isinstance(corpo, dict):
        itens = corpo.get("listaCPF") or corpo.get("cpfs") or corpo.get("dados") or corpo
    if isinstance(itens, dict):
        itens = [itens]
    if not itens:
        raise ErroConsulta("A Receita não encontrou este CPF.")
    dados = itens[0]

    codigo = str(dados.get("situacaoCadastral") or "").strip()
    situacao, aviso = SITUACAO_CADASTRAL.get(
        codigo, ((dados.get("descSituacaoCadastral") or "desconhecida").strip(), "")
    )
    return {
        "campos": _qualificacao(dados),
        "situacao": situacao,
        "aviso": aviso,
        # À parte: o contrato é qualificação civil e usa o nome de registro
        # mesmo quando a pessoa é chamada pelo nome social.
        "nome_registro": (dados.get("nome") or "").strip(),
        "fonte": "Receita Federal (Conecta gov.br)",
    }
