"""Descobre o vínculo de uma pessoa com o cliente cruzando documento e entrevista.

O pipeline documental (`app/documentos_juridicos.py`) só afirma um vínculo quando o
PRÓPRIO arquivo o declara — é a regra de citação literal que impede o sistema de
inventar parentesco. Mas o vínculo quase nunca está no papel: um resumo de alta diz
"Paciente: Artur Nunes" e para por aí. Quem sabe que Artur é filho do cliente é a
entrevista, onde ele contou isso ao advogado.

Este módulo faz essa ponte e só ela. Recebe os nomes que o documento trouxe SEM
vínculo declarado, lê as entrevistas do caso e devolve o vínculo que o cliente
declarou — cada um preso a uma citação literal da entrevista, conferida aqui antes
de sair. Vínculo cuja citação não existe no texto é descartado, exatamente como o
pipeline descarta campo sem citação no OCR.

A origem viaja junto (`relacao_origem`): "documento" quando o arquivo afirmou,
"entrevista" quando veio daqui. A tela precisa dessa diferença — "filho, segundo a
entrevista" é uma afirmação mais fraca que "filho, escrito na certidão", e o
advogado tem que conseguir distinguir as duas sem abrir o arquivo.

Custo: uma chamada por documento que tenha nome sem vínculo E entrevista gravada.
Documento sem nome pendente, ou caso sem entrevista, não gasta chamada nenhuma —
a função devolve vazio antes de tocar a rede.
"""

from __future__ import annotations

import logging
import threading
import time
import unicodedata
from typing import Any

from . import armazenamento, llm

log = logging.getLogger("vinculos")

#: Cache por caso, em memória do worker. Uma pasta com vinte documentos do mesmo
#: caso perguntaria vinte vezes o mesmo vínculo, sobre a mesma entrevista — vinte
#: chamadas pagas para uma resposta só. A fila `documents` é servida por um worker
#: solo, então o processo é o mesmo para o lote inteiro e o cache pega quase tudo.
#: TTL curto porque a entrevista pode ser gravada DEPOIS dos documentos: expirando
#: rápido, o próximo documento do lote já enxerga a entrevista nova.
#: `{caso_id: (instante, nomes_ja_perguntados, vinculos_encontrados)}`. Guardar o
#: conjunto perguntado separado do encontrado importa: nome perguntado e NÃO achado
#: também é resposta ("a entrevista não diz"), e sem registrá-lo o cache voltaria a
#: perguntar por ele em todo documento seguinte do lote.
_CACHE: dict[str, tuple[float, set[str], dict[str, dict[str, str]]]] = {}
_CACHE_TRAVA = threading.Lock()
CACHE_TTL_S = 300.0


def limpar_cache() -> None:
    """Esvazia o cache de vínculos — usado pelos testes e por quem regrava entrevista."""
    with _CACHE_TRAVA:
        _CACHE.clear()

#: Teto de texto de entrevista mandado ao modelo. Entrevista longa é comum (o
#: roteiro inteiro transcrito passa de 30 mil caracteres) e o vínculo costuma
#: aparecer na qualificação, no começo — mas não sempre, então o corte é generoso.
LIMITE_ENTREVISTA = 12000

INSTRUCAO = """Você lê a transcrição de uma entrevista entre um advogado e seu cliente e
descobre o vínculo de outras pessoas com esse cliente.

Recebe: o nome do CLIENTE, a lista de NOMES encontrados em documentos do caso cujo
vínculo com o cliente ainda é desconhecido, e a ENTREVISTA.

Para cada nome da lista, responda o vínculo com o cliente APENAS se a entrevista o
disser. Copie a passagem literal e contínua da entrevista que sustenta o vínculo —
sem ela a resposta é descartada.

REGRAS
- `relacao` é o vínculo com o CLIENTE, em uma ou duas palavras: filho, filha, esposa,
  marido, pai, mãe, irmão, irmã, sobrinho, chefe, colega, vizinho, agressor, patrão.
  Diga o vínculo do ponto de vista do cliente: se o cliente diz "meu filho Artur",
  a relação de Artur é "filho".
- `citacao` tem que ser um trecho COPIADO da entrevista, palavra por palavra. Não
  reescreva, não resuma, não corrija. Se não achar uma passagem que diga o vínculo,
  NÃO inclua o nome na resposta.
- Não deduza parentesco por sobrenome igual. Sobrenome coincidente não é prova de
  filiação; muita gente do mesmo caso divide sobrenome sem ser parente.
- Nome que a entrevista não menciona simplesmente fica fora da resposta.

Responda apenas JSON:
{"vinculos":[{"nome":"...","relacao":"...","citacao":"..."}]}"""


def _dobrar(texto: str) -> str:
    """Normaliza para comparar nome e citação sem tropeçar em acento ou caixa."""
    base = "".join(
        c for c in unicodedata.normalize("NFKD", str(texto or ""))
        if not unicodedata.combining(c)
    )
    return " ".join(base.casefold().split())


def texto_das_entrevistas(caso_id: str) -> str:
    """Junta as entrevistas do caso num texto só, a mais recente primeiro."""
    partes = []
    for entrevista in armazenamento.listar_entrevistas(caso_id):
        texto = str(entrevista.get("texto") or "").strip()
        if texto:
            partes.append(texto)
    return "\n\n".join(partes)


def resolver_por_entrevista(
    caso_id: str,
    cliente: str,
    nomes: list[str],
    *,
    timeout: float = 60,
) -> dict[str, dict[str, str]]:
    """Devolve `{nome_normalizado: {relacao, citacao, relacao_origem}}` para os nomes achados.

    Nunca levanta: vínculo é enriquecimento, não requisito. Se o modelo estiver
    desligado, a entrevista não existir ou a resposta vier torta, o documento segue
    como está — sem vínculo, que é o estado honesto — e o parecer do caso ainda
    tem uma segunda chance de estabelecê-lo, com todos os documentos à vista.
    """
    nomes_limpos = [n.strip() for n in nomes if n and n.strip()]
    if not nomes_limpos or not cliente.strip():
        return {}

    # Cache do caso: se TODOS os nomes deste documento já foram perguntados antes,
    # a resposta guardada serve e o documento não custa chamada nenhuma.
    pedidos = {_dobrar(nome) for nome in nomes_limpos}
    agora = time.monotonic()
    with _CACHE_TRAVA:
        gravado = _CACHE.get(caso_id)
        if gravado and agora - gravado[0] < CACHE_TTL_S and pedidos <= gravado[1]:
            return {chave: gravado[2][chave] for chave in pedidos if chave in gravado[2]}

    entrevista = texto_das_entrevistas(caso_id)
    if not entrevista.strip():
        return {}

    mensagem = (
        f"CLIENTE: {cliente.strip()}\n\n"
        f"NOMES SEM VÍNCULO CONHECIDO:\n"
        + "\n".join(f"- {nome}" for nome in nomes_limpos)
        + f"\n\nENTREVISTA:\n{entrevista[:LIMITE_ENTREVISTA]}"
    )

    try:
        resposta = llm.chamar(INSTRUCAO, mensagem, temperatura=0, timeout=timeout)
    except llm.ErroLLM as exc:
        log.warning("vínculo pela entrevista indisponível: %s", str(exc)[:160])
        return {}
    except Exception as exc:  # noqa: BLE001 - fronteira com serviço externo
        log.warning("vínculo pela entrevista falhou: %s", str(exc)[:160])
        return {}

    entrevista_dobrada = _dobrar(entrevista)
    achados: dict[str, dict[str, str]] = {}

    for item in resposta.get("vinculos") or []:
        if not isinstance(item, dict):
            continue
        nome = str(item.get("nome") or "").strip()
        relacao = str(item.get("relacao") or "").strip()
        citacao = str(item.get("citacao") or "").strip()
        chave = _dobrar(nome)
        # Só vale nome que ESTE documento perguntou: o modelo não pode contrabandear
        # gente que ninguém pediu para resolver.
        if not relacao or not citacao or chave not in pedidos:
            continue
        # A citação tem que existir na entrevista, palavra por palavra. É a mesma
        # trava do OCR: sem lastro verificável, o vínculo não sai daqui.
        if _dobrar(citacao) not in entrevista_dobrada:
            log.info("vínculo descartado (citação ausente da entrevista): %s", nome[:60])
            continue
        achados[chave] = {
            "relacao": relacao[:80],
            "citacao": citacao[:500],
            "relacao_origem": "entrevista",
        }

    # Guarda inclusive os nomes que a entrevista NÃO explicou: "não diz" é uma
    # resposta, e sem registrá-la o próximo documento do lote perguntaria de novo.
    with _CACHE_TRAVA:
        anterior = _CACHE.get(caso_id)
        recente = anterior and time.monotonic() - anterior[0] < CACHE_TTL_S
        perguntados = (anterior[1] | pedidos) if recente else set(pedidos)
        acumulados = {**anterior[2], **achados} if recente else dict(achados)
        _CACHE[caso_id] = (time.monotonic(), perguntados, acumulados)

    return achados


def aplicar(validacao: dict[str, Any], achados: dict[str, dict[str, str]]) -> dict[str, Any]:
    """Preenche o vínculo em `partes` e `pessoa_principal`, sem sobrescrever o documento.

    O que o arquivo declarou vence o que a entrevista disse: documento é prova, fala
    é memória. Por isso só entra onde `relacao_com_cliente` está vazia.
    """
    for parte in validacao.get("partes") or []:
        if parte.get("relacao_com_cliente"):
            parte.setdefault("relacao_origem", "documento")
            continue
        achado = achados.get(_dobrar(str(parte.get("nome") or "")))
        if achado:
            parte["relacao_com_cliente"] = achado["relacao"]
            parte["relacao_citacao"] = achado["citacao"]
            parte["relacao_origem"] = "entrevista"

    principal = validacao.get("pessoa_principal")
    if isinstance(principal, dict):
        if principal.get("relacao_com_cliente"):
            principal.setdefault("relacao_origem", "documento")
        else:
            achado = achados.get(_dobrar(str(principal.get("nome") or "")))
            if achado:
                principal["relacao_com_cliente"] = achado["relacao"]
                principal["relacao_citacao"] = achado["citacao"]
                principal["relacao_origem"] = "entrevista"
    return validacao
