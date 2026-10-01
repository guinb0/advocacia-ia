"""A base de contexto do caso: o que o chat já levantou, guardado junto da petição.

POR QUE ISTO EXISTE

O chat lia os documentos e pesquisava na web de novo a cada pergunta. Medido nas
conversas gravadas: 24 das 39 pesquisas e 19 das 27 buscas em documentos eram a mesma
ferramenta repetida na mesma resposta. O advogado espera, o modelo gasta rodada e o
resultado é o que já se sabia. O que se levantou uma vez vale para o caso todo — e não
para a conversa de UMA pessoa: outro advogado que abre a mesma petição não precisa
pagar de novo a pesquisa que o colega fez.

O QUE FICA AQUI

- `documentos`: para cada anexo, o tipo, os campos que o OCR extraiu e o início do texto.
  É um RESUMO, montado sem IA: para o texto completo o modelo continua chamando
  `ler_documentos`. Refeito sozinho quando os anexos mudam (ver `assinatura`).
- `buscas`: o que já foi procurado nos documentos e o que se achou, com os trechos.
  Só o que ACHOU fica; «não achei» pode deixar de valer quando entra um anexo novo, então
  cai junto com a assinatura.
- `pesquisas`: as pesquisas na web do caso, com as fontes. Não dependem dos anexos e
  valem por `VALIDADE_PESQUISA_DIAS`: súmula e tese mudam.

A análise entrevista × documentos NÃO é copiada para cá: ela já mora dentro da própria
petição (`analise`) e entra no contexto direto de lá.

A BASE É UMA OTIMIZAÇÃO, NUNCA UM REQUISITO

Qualquer falha de leitura ou de gravação vira aviso no log e o chat segue como se a base
estivesse vazia. Um banco lento não pode tirar o advogado da conversa.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any

from ..banco import PREFIXO, SCHEMA, conectar

log = logging.getLogger("agente")

TABELA = f"{SCHEMA}.{PREFIXO}caso_contexto"
_ESQUEMA = (
    f"IF OBJECT_ID('{TABELA}') IS NULL CREATE TABLE {TABELA} ("
    " caso_id varchar(160) NOT NULL PRIMARY KEY,"
    " dados nvarchar(max) NOT NULL,"
    " atualizado_em varchar(40) NOT NULL)"
)

#: Pesquisa mais velha que isto é pesquisada de novo.
VALIDADE_PESQUISA_DIAS = 30
MAX_PESQUISAS = 12
MAX_BUSCAS = 15

#: Quanto de cada coisa vai ao prompt. O bloco inteiro tem teto: acima de ~9 mil
#: caracteres o modelo passa a ignorar o meio do contexto, e o que ele ignora ninguém vê.
LIMITE_DO_BLOCO = 9000
LIMITE_DOS_DOCUMENTOS = 5500
LIMITE_DAS_BUSCAS = 2500
INICIO_DO_DOCUMENTO = 400
TRECHO_DA_BUSCA = 300

_trava = threading.Lock()
_tabela_pronta = False


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _chave(texto: Any) -> str:
    """Sem acento, sem caixa e com o espaço colapsado: duas grafias do mesmo termo se acham."""
    sem_acento = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return " ".join(sem_acento.lower().split())


def _compacto(texto: Any, limite: int) -> str:
    return " ".join(str(texto or "").split())[:limite]


# ----------------------------------------------------------------- armazenamento


def _garantir_tabela() -> None:
    global _tabela_pronta
    if _tabela_pronta:
        return
    with conectar() as c:
        c.execute(_ESQUEMA)
        c.commit()
    _tabela_pronta = True


def _ler(caso_id: str) -> dict[str, Any]:
    _garantir_tabela()
    with conectar() as c:
        linha = c.execute(f"SELECT dados FROM {TABELA} WHERE caso_id=?", (caso_id,)).fetchone()
    if not linha:
        return {}
    try:
        dados = json.loads(linha["dados"] or "{}")
    except ValueError:
        return {}
    return dados if isinstance(dados, dict) else {}


def _gravar(caso_id: str, dados: dict[str, Any]) -> None:
    _garantir_tabela()
    corpo = json.dumps(dados, ensure_ascii=False, default=str)
    with conectar() as c:
        atualizada = c.execute(
            f"UPDATE {TABELA} SET dados=?, atualizado_em=? WHERE caso_id=?",
            (corpo, _agora(), caso_id),
        )
        if not atualizada.rowcount:
            c.execute(
                f"INSERT INTO {TABELA}(caso_id, dados, atualizado_em) VALUES(?,?,?)",
                (caso_id, corpo, _agora()),
            )
        c.commit()


# ------------------------------------------------------------------- documentos


def assinatura(anexos: list[dict[str, Any]]) -> str:
    """Muda quando um anexo entra, é lido, é reclassificado ou tem o texto alterado.

    É ela que decide se o resumo dos documentos ainda vale. Não usa o texto inteiro (que
    pode ter megabytes): o tamanho dele já denuncia a leitura que terminou.
    """
    partes = sorted(
        (
            str(a.get("id") or ""),
            str(a.get("situacao") or ""),
            str(a.get("tipo") or ""),
            len(str(a.get("texto") or "")),
        )
        for a in anexos
    )
    return hashlib.sha1(json.dumps(partes, ensure_ascii=False).encode("utf-8")).hexdigest()


def _digerir(anexos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    resumo = []
    for a in anexos:
        lido = a.get("situacao") == "lido"
        resumo.append(
            {
                "id": str(a.get("id") or ""),
                "arquivo": str(a.get("arquivo") or ""),
                "tipo": str(a.get("tipo") or ""),
                "situacao": str(a.get("situacao") or ""),
                "campos": [
                    {"rotulo": _compacto(c.get("rotulo"), 40), "valor": _compacto(c.get("valor"), 80)}
                    for c in (a.get("campos") or [])[:8]
                    if isinstance(c, dict)
                ],
                "inicio": _compacto(a.get("texto"), INICIO_DO_DOCUMENTO) if lido else "",
            }
        )
    return resumo


def _refeita(dados: dict[str, Any], anexos: list[dict[str, Any]]) -> dict[str, Any]:
    """Os documentos resumidos de novo; as buscas caem, as pesquisas ficam."""
    return {
        **dados,
        "assinatura": assinatura(anexos),
        "documentos": _digerir(anexos),
        "buscas": [],
        "atualizado_em": _agora(),
    }


def obter(caso_id: str, anexos: list[dict[str, Any]]) -> dict[str, Any]:
    """A base do caso, com o resumo dos documentos em dia com os anexos de agora."""
    try:
        dados = _ler(caso_id)
        if dados.get("assinatura") != assinatura(anexos):
            dados = _refeita(dados, anexos)
            _gravar(caso_id, dados)
        return dados
    except Exception as erro:  # noqa: BLE001 — a base é otimização, nunca requisito
        log.warning("base de contexto do caso %s indisponível: %s", caso_id, str(erro)[:200])
        return {"documentos": _digerir(anexos), "pesquisas": [], "buscas": [], "indisponivel": True}


def lida(caso_id: str) -> dict[str, Any]:
    """O que está guardado, sem refazer nada. Vazio se não houver ou se falhar."""
    try:
        return _ler(caso_id)
    except Exception as erro:  # noqa: BLE001
        log.warning("base de contexto do caso %s ilegível: %s", caso_id, str(erro)[:200])
        return {}


def refazer(caso_id: str, anexos: list[dict[str, Any]]) -> dict[str, Any]:
    """Levantamento novo dos documentos, a pedido: descarta o resumo e as buscas."""
    try:
        dados = _refeita(_ler(caso_id), anexos)
        _gravar(caso_id, dados)
        return dados
    except Exception as erro:  # noqa: BLE001
        log.warning("não foi possível refazer a base do caso %s: %s", caso_id, str(erro)[:200])
        return {"documentos": _digerir(anexos), "pesquisas": [], "buscas": [], "indisponivel": True}


# ------------------------------------------------- análise entrevista × documentos


def analise_guardada(caso_id: str, assinatura_dos_textos: str) -> dict[str, Any] | None:
    """A análise já feita para ESTES textos lidos, ou None. Falha de leitura vale como ausência."""
    try:
        guardada = _ler(caso_id).get("analise_documentos")
    except Exception as erro:  # noqa: BLE001
        log.warning("análise guardada do caso %s ilegível: %s", caso_id, str(erro)[:200])
        return None
    if isinstance(guardada, dict) and guardada.get("assinatura") == assinatura_dos_textos:
        resultado = guardada.get("resultado")
        return resultado if isinstance(resultado, dict) else None
    return None


def guardar_analise(caso_id: str, assinatura_dos_textos: str, resultado: dict[str, Any]) -> None:
    try:
        with _trava:
            dados = _ler(caso_id)
            dados["analise_documentos"] = {"assinatura": assinatura_dos_textos, "resultado": resultado, "em": _agora()}
            _gravar(caso_id, dados)
    except Exception as erro:  # noqa: BLE001 — otimização, nunca requisito
        log.warning("não foi possível guardar a análise do caso %s: %s", caso_id, str(erro)[:200])


# ---------------------------------------------------------------------- pesquisas


def _instante(valor: Any) -> datetime | None:
    try:
        instante = datetime.fromisoformat(str(valor or ""))
    except ValueError:
        return None
    return instante if instante.tzinfo else instante.replace(tzinfo=timezone.utc)


def pesquisas_validas(dados: dict[str, Any]) -> list[dict[str, Any]]:
    limite = datetime.now(timezone.utc) - timedelta(days=VALIDADE_PESQUISA_DIAS)
    validas = []
    for pesquisa in dados.get("pesquisas") or []:
        quando = _instante(pesquisa.get("em"))
        if quando is not None and quando < limite:
            continue
        if pesquisa.get("pergunta") and pesquisa.get("fontes"):
            validas.append(pesquisa)
    return validas


def registrar_pesquisa(caso_id: str, pesquisa: dict[str, Any]) -> None:
    """Guarda uma pesquisa na web feita agora, para o caso inteiro."""
    pergunta = str(pesquisa.get("pergunta") or "").strip()
    if not pergunta or not pesquisa.get("fontes"):
        return
    novo = {
        "pergunta": pergunta,
        "resposta": str(pesquisa.get("resposta") or "")[:3000],
        "fontes": [
            {
                "url": f.get("url"),
                "titulo": f.get("titulo"),
                "confianca": f.get("confianca"),
            }
            for f in (pesquisa.get("fontes") or [])[:8]
            if isinstance(f, dict)
        ],
        "fontes_oficiais": pesquisa.get("fontes_oficiais"),
        "tem_fonte_oficial": pesquisa.get("tem_fonte_oficial"),
        "aviso": pesquisa.get("aviso"),
        "em": _agora(),
    }
    try:
        with _trava:
            dados = _ler(caso_id)
            restantes = [p for p in dados.get("pesquisas") or [] if _chave(p.get("pergunta")) != _chave(pergunta)]
            dados["pesquisas"] = [*restantes, novo][-MAX_PESQUISAS:]
            _gravar(caso_id, dados)
    except Exception as erro:  # noqa: BLE001
        log.warning("não foi possível guardar a pesquisa do caso %s: %s", caso_id, str(erro)[:200])


# ------------------------------------------------------------------------ buscas


def registrar_busca(caso_id: str, termo: str, resultado: dict[str, Any]) -> None:
    """Guarda o que uma busca nos documentos ACHOU. Busca sem resultado não fica."""
    if not resultado.get("encontrado") or resultado.get("reaproveitada"):
        return
    achados = [
        {
            "arquivo": str(r.get("arquivo") or ""),
            "tipo": str(r.get("tipo") or ""),
            "trechos": [_compacto(t, 500) for t in (r.get("trechos") or [])[:2]],
            "campos": [
                {"rotulo": _compacto(c.get("rotulo"), 40), "valor": _compacto(c.get("valor"), 80)}
                for c in (r.get("campos_extraidos") or [])[:6]
                if isinstance(c, dict)
            ],
        }
        for r in (resultado.get("resultados") or [])[:3]
    ]
    termo = " ".join(str(termo or "").split())
    if not termo or not achados:
        return
    try:
        with _trava:
            dados = _ler(caso_id)
            restantes = [b for b in dados.get("buscas") or [] if _chave(b.get("termo")) != _chave(termo)]
            dados["buscas"] = [*restantes, {"termo": termo, "achados": achados, "em": _agora()}][-MAX_BUSCAS:]
            _gravar(caso_id, dados)
    except Exception as erro:  # noqa: BLE001
        log.warning("não foi possível guardar a busca do caso %s: %s", caso_id, str(erro)[:200])


def busca_lembrada(dados: dict[str, Any], termo: str) -> dict[str, Any] | None:
    """A busca já feita com este mesmo termo, no formato que a ferramenta devolve."""
    procurado = _chave(termo)
    for busca in dados.get("buscas") or []:
        if procurado and _chave(busca.get("termo")) == procurado:
            return {
                "termo": busca.get("termo"),
                "encontrado": True,
                "reaproveitada": True,
                "resultados": [
                    {
                        "arquivo": a.get("arquivo"),
                        "tipo": a.get("tipo"),
                        "trechos": a.get("trechos") or [],
                        "campos_extraidos": a.get("campos") or [],
                    }
                    for a in busca.get("achados") or []
                ],
                "orientacao": (
                    "Esta busca já foi feita antes neste caso e o resultado é este. Se precisar"
                    " de OUTRO trecho ou de outro dado, procure com um termo mais específico."
                ),
            }
    return None


# ------------------------------------------------------------------ para o modelo


def _linha_do_documento(doc: dict[str, Any], limite_do_inicio: int) -> str:
    partes = [f"- {doc.get('arquivo')} — {doc.get('tipo') or 'sem tipo identificado'}"]
    if doc.get("situacao") != "lido":
        partes.append("(SEM texto lido ainda: não dá para citar o conteúdo)")
        return " ".join(partes)
    campos = "; ".join(f"{c['rotulo']}: {c['valor']}" for c in doc.get("campos") or [] if c.get("valor"))
    if campos:
        partes.append(f"— campos: {campos}")
    inicio = str(doc.get("inicio") or "")[:max(0, limite_do_inicio)]
    if inicio:
        partes.append(f"— início do texto: «{inicio}»")
    return " ".join(partes)


def bloco_para_o_modelo(dados: dict[str, Any]) -> str:
    """O que já foi levantado, escrito para o modelo usar antes de consultar de novo."""
    documentos = dados.get("documentos") or []
    buscas = dados.get("buscas") or []
    if not documentos and not buscas:
        return ""

    saida = [
        "=== BASE DE CONTEXTO DO CASO (já levantada — USE-A ANTES DE CONSULTAR DE NOVO) ===",
        "Resumo do que já foi lido e procurado neste caso. Ele NÃO substitui o documento:"
        " serve para você não repetir consulta. Para o texto completo de um documento, ou"
        " para um dado que não esteja abaixo, consulte de forma ESPECÍFICA.",
    ]
    if documentos:
        cabecalho = "Documentos:"
        por_documento = max(0, LIMITE_DOS_DOCUMENTOS // max(1, len(documentos)) - 140)
        linhas = [_linha_do_documento(d, min(INICIO_DO_DOCUMENTO, por_documento)) for d in documentos]
        corpo = "\n".join(linhas)
        if len(corpo) > LIMITE_DOS_DOCUMENTOS:
            corpo = corpo[:LIMITE_DOS_DOCUMENTOS] + " […]"
        saida.append(cabecalho + "\n" + corpo)
    if buscas:
        linhas = []
        for busca in buscas:
            for achado in (busca.get("achados") or [])[:2]:
                trecho = (achado.get("trechos") or [""])[0][:TRECHO_DA_BUSCA]
                campos = "; ".join(f"{c['rotulo']}: {c['valor']}" for c in achado.get("campos") or [] if c.get("valor"))
                detalhe = " — ".join(x for x in (campos, f"«{trecho}»" if trecho else "") if x)
                linhas.append(
                    f"- «{busca.get('termo')}» → {achado.get('arquivo')}"
                    + (f" ({achado.get('tipo')})" if achado.get("tipo") else "")
                    + (f": {detalhe}" if detalhe else "")
                )
        corpo = "\n".join(linhas)
        if len(corpo) > LIMITE_DAS_BUSCAS:
            corpo = corpo[:LIMITE_DAS_BUSCAS] + " […]"
        saida.append("Buscas nos documentos já feitas (o que se achou):\n" + corpo)
    texto = "\n".join(saida)
    return texto[:LIMITE_DO_BLOCO] + (" […]" if len(texto) > LIMITE_DO_BLOCO else "")


def resumo(dados: dict[str, Any]) -> dict[str, Any]:
    """Os números que a tela mostra: o que a base já tem, sem o conteúdo."""
    documentos = dados.get("documentos") or []
    lidos = [d for d in documentos if d.get("situacao") == "lido"]
    return {
        "documentos_lidos": len(lidos),
        "documentos_sem_leitura": len(documentos) - len(lidos),
        "pesquisas": len(pesquisas_validas(dados)),
        "buscas": len(dados.get("buscas") or []),
        "atualizado_em": str(dados.get("atualizado_em") or ""),
        "indisponivel": bool(dados.get("indisponivel")),
    }
