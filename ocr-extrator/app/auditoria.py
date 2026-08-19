"""Confere se a entrevista seguiu o roteiro do escritório.

O QUE ISTO RESPONDE

O secretário abre a transcrição bruta de uma entrevista e precisa saber: o
advogado percorreu o script, ou ficou faltando coisa? Ler quarenta minutos de
texto para descobrir isso não acontece na prática — então ninguém descobria.

O QUE ELE NÃO FAZ, E POR QUÊ

Não dá nota, não compara pessoas e não conclui que alguém trabalhou mal. Uma
pergunta pode não ter sido feita porque não cabia: o cliente já tinha respondido
antes, ou o caso não pedia. O relatório aponta o que NÃO APARECE na transcrição e
deixa a leitura para quem conhece o atendimento — que é o secretário, não o
modelo.

A COBERTURA SAI DA TRANSCRIÇÃO, NÃO DO ROTEIRO PREENCHIDO

De propósito. O roteiro preenchido diz o que a escuta conseguiu extrair; a
transcrição diz o que foi realmente perguntado e respondido. Auditar o primeiro
mediria o acerto do reconhecimento de voz, não a condução da entrevista — e é a
condução que está em avaliação aqui.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import httpx

from . import roteiros

log = logging.getLogger("auditoria")

TEMPO_MODELO_S = 180.0

#: Teto do que vai ao modelo. Entrevista longa passa de 40 mil caracteres, e
#: mandar tudo custa tempo e dinheiro sem melhorar o veredito — o que importa
#: para saber se uma pergunta foi feita está espalhado, não concentrado no fim.
LIMITE_TRANSCRICAO = 24_000


class ErroAuditoria(RuntimeError):
    pass


INSTRUCAO = """Você confere se uma entrevista jurídica seguiu o roteiro do escritório.

Recebe o ROTEIRO e a TRANSCRIÇÃO bruta da conversa, que vem de reconhecimento de
voz e contém erros, repetições e trechos truncados.

O roteiro tem três partes, e todas contam:
1. ABERTURA — o que a atendente lê ao começar: cumprimento, apresentação do
   escritório, sigilo, aviso de gravação, pedido de sinceridade.
2. PERGUNTAS — cada uma com um id.
3. ENCERRAMENTO — o que ela lê ao terminar: agradecimento, próximos passos,
   prazos, contato, despedida.

Regras:
- Uma pergunta conta como COBERTA quando a transcrição mostra que o assunto dela
  foi tratado — não é preciso que as palavras batam. O cliente respondendo o tema
  vale, mesmo sem a pergunta aparecer.
- Marque como NÃO COBERTA só o que você não encontra na conversa. Na dúvida,
  classifique como INCERTA: a transcrição erra, e acusar falha que existiu só no
  reconhecimento é pior que não acusar.
- Abertura e encerramento não precisam ser lidos palavra por palavra. Avalie se
  os PONTOS deles foram ditos, e liste os que faltaram.
- Não avalie a pessoa, não dê nota e não suponha intenção. Descreva o que falta.
- Não invente pergunta que não está no roteiro.

Responda apenas JSON:
{"resumo":"2 a 3 frases sobre como a entrevista correu",
 "cobertas":["id"],"nao_cobertas":["id"],"incertas":["id"],
 "abertura":{"situacao":"feita|parcial|ausente|incerta","faltou":["..."]},
 "encerramento":{"situacao":"feita|parcial|ausente|incerta","faltou":["..."]},
 "observacoes":[{"item":"...","porque":"..."}],
 "pontos_fortes":["..."]}
"""


def _chamar_modelo(mensagem: str) -> dict[str, Any]:
    chave = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not chave:
        raise ErroAuditoria(
            "Auditoria desligada: falta DEEPSEEK_API_KEY no .env. A transcrição "
            "continua disponível para leitura."
        )
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    try:
        resposta = httpx.post(
            base_url + "/chat/completions",
            headers={"Authorization": f"Bearer {chave}"},
            json={
                "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "max_tokens": 1600,
                "messages": [
                    {"role": "system", "content": INSTRUCAO},
                    {"role": "user", "content": mensagem},
                ],
            },
            timeout=TEMPO_MODELO_S,
        )
        resposta.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("Auditoria falhou: %s", str(exc)[:160])
        raise ErroAuditoria("O modelo não respondeu a tempo. Tente de novo.") from exc

    try:
        return json.loads(resposta.json()["choices"][0]["message"]["content"])
    except Exception as exc:
        raise ErroAuditoria("Resposta ilegível do modelo.") from exc


def _perguntas_do_roteiro(codigo: str) -> list[dict[str, Any]]:
    """As perguntas do script, achatadas, com bloco e obrigatoriedade."""
    roteiro = roteiros.obter(codigo)
    if roteiro is None:
        return []
    itens: list[dict[str, Any]] = []
    for bloco in roteiro.blocos:
        for pergunta in bloco.perguntas:
            itens.append(
                {
                    "id": pergunta.id,
                    "texto": pergunta.texto,
                    "bloco": bloco.titulo,
                    "obrigatoria": bool(pergunta.obrigatoria),
                }
            )
    return itens


def _so_conhecidos(bruto: Any, validos: set[str]) -> list[str]:
    """Descarta id que o modelo inventou.

    Sem isto uma pergunta imaginária apareceria como "não coberta" e mandaria o
    secretário cobrar algo que o roteiro nunca pediu.
    """
    if not isinstance(bruto, list):
        return []
    vistos: list[str] = []
    for item in bruto:
        chave = str(item or "").strip()
        if chave in validos and chave not in vistos:
            vistos.append(chave)
    return vistos


#: Teto de cada parágrafo de abertura/encerramento mandado ao modelo.
LIMITE_PARAGRAFO = 220


def _pontos(paragrafos: list[str]) -> str:
    """Os parágrafos como lista de pontos, encurtados.

    O roteiro traz a abertura e o encerramento como texto corrido para a
    atendente LER. Para conferir, o que interessa é se os pontos foram ditos —
    ninguém recita dezenove parágrafos palavra por palavra, e cobrar isso
    apontaria falha em toda entrevista.
    """
    itens = [re.sub(r"\s+", " ", str(p or "")).strip() for p in paragrafos]
    return "\n".join(f"- {i[:LIMITE_PARAGRAFO]}" for i in itens if i) or "(sem texto)"


def _parte_lida(bruto: Any) -> dict[str, Any]:
    """Normaliza `abertura`/`encerramento` do modelo.

    `incerta` é o padrão quando ele devolve algo fora do combinado: afirmar que
    a abertura não foi feita, por causa de um campo malformado, acusaria a
    pessoa por defeito nosso.
    """
    validas = {"feita", "parcial", "ausente", "incerta"}
    if not isinstance(bruto, dict):
        return {"situacao": "incerta", "faltou": []}
    situacao = str(bruto.get("situacao") or "").strip().casefold()
    faltou = bruto.get("faltou")
    return {
        "situacao": situacao if situacao in validas else "incerta",
        "faltou": [
            re.sub(r"\s+", " ", str(f)).strip()[:200]
            for f in (faltou or [])[:8]
            if str(f or "").strip()
        ]
        if isinstance(faltou, list)
        else [],
    }


def auditar(texto: str, codigo_roteiro: str = "") -> dict[str, Any]:
    """Compara a transcrição com o roteiro e devolve o relatório."""
    limpo = re.sub(r"\s+", " ", str(texto or "")).strip()
    if len(limpo) < 200:
        raise ErroAuditoria(
            "Transcrição curta demais para auditar — não há conversa suficiente "
            "para dizer o que foi ou não perguntado."
        )

    codigo = codigo_roteiro or next(iter(roteiros.ROTEIROS), "")
    perguntas = _perguntas_do_roteiro(codigo)
    if not perguntas:
        raise ErroAuditoria(f"Roteiro {codigo!r} não encontrado.")

    catalogo = "\n".join(
        f"- {p['id']} [{p['bloco']}]{' (obrigatória)' if p['obrigatoria'] else ''}: {p['texto']}"
        for p in perguntas
    )
    roteiro = roteiros.obter(codigo)
    # Abertura e encerramento vão RESUMIDOS em pontos, não palavra por palavra:
    # são 10 e 19 parágrafos, e mandá-los inteiros gastaria metade do contexto
    # para conferir texto que ninguém recita literalmente.
    abertura = _pontos(roteiro.saudacao if roteiro else [])
    encerramento = _pontos(roteiro.encerramento if roteiro else [])
    mensagem = (
        f"ABERTURA que deveria ser lida:\n{abertura}\n\n"
        f"PERGUNTAS ({len(perguntas)}):\n{catalogo}\n\n"
        f"ENCERRAMENTO que deveria ser lido:\n{encerramento}\n\n"
        f"TRANSCRIÇÃO:\n{limpo[:LIMITE_TRANSCRICAO]}"
    )
    bruto = _chamar_modelo(mensagem)

    validos = {p["id"] for p in perguntas}
    cobertas = _so_conhecidos(bruto.get("cobertas"), validos)
    nao_cobertas = _so_conhecidos(bruto.get("nao_cobertas"), validos - set(cobertas))
    incertas = _so_conhecidos(
        bruto.get("incertas"), validos - set(cobertas) - set(nao_cobertas)
    )

    por_id = {p["id"]: p for p in perguntas}
    def detalhar(ids: list[str]) -> list[dict[str, Any]]:
        return [por_id[i] for i in ids if i in por_id]

    faltando_obrigatorias = [p for p in detalhar(nao_cobertas) if p["obrigatoria"]]
    total_obrigatorias = sum(1 for p in perguntas if p["obrigatoria"])

    return {
        "roteiro": codigo,
        "total_perguntas": len(perguntas),
        "resumo": re.sub(r"\s+", " ", str(bruto.get("resumo") or "")).strip()[:600],
        "cobertas": detalhar(cobertas),
        "nao_cobertas": detalhar(nao_cobertas),
        "incertas": detalhar(incertas),
        "abertura": _parte_lida(bruto.get("abertura")),
        "encerramento": _parte_lida(bruto.get("encerramento")),
        "faltando_obrigatorias": faltando_obrigatorias,
        "total_obrigatorias": total_obrigatorias,
        "observacoes": [
            {
                "item": re.sub(r"\s+", " ", str(o.get("item") or "")).strip()[:200],
                "porque": re.sub(r"\s+", " ", str(o.get("porque") or "")).strip()[:400],
            }
            for o in (bruto.get("observacoes") or [])[:8]
            if isinstance(o, dict) and str(o.get("item") or "").strip()
        ],
        "pontos_fortes": [
            re.sub(r"\s+", " ", str(p)).strip()[:200]
            for p in (bruto.get("pontos_fortes") or [])[:5]
            if str(p or "").strip()
        ],
        "transcricao_truncada": len(limpo) > LIMITE_TRANSCRICAO,
        "aviso": (
            "Conferência assistiva sobre a transcrição, que vem de reconhecimento "
            "de voz e erra. Pergunta pode não ter sido feita por bom motivo — a "
            "leitura é de quem conhece o atendimento."
        ),
    }
