"""Vocabulário de status do Acervo e a ponte para `juridico.autoridades.Autoridade`.

Status de SINCRONIZAÇÃO (a norma no painel) e status JURÍDICO (o dispositivo ou a súmula) são coisas
diferentes: uma norma pode estar ATUALIZADA (verificada hoje) e ter dispositivos revogados.
"""

from __future__ import annotations

import os
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

from ..juridico import autoridades as aut

# ------------------------------------------------------------------ sincronização (painel)
ATUALIZADO, PENDENTE, ERRO, EM_ANDAMENTO, REVOGADO = "ATUALIZADO", "PENDENTE", "ERRO", "EM_ANDAMENTO", "REVOGADO"
AGUARDANDO_VERIFICACAO = "AGUARDANDO_VERIFICACAO"

#: Cor e texto SEMPRE juntos na tela (nunca só cor): verde atualizado, amarelo pendente, vermelho erro,
#: cinza revogado, azul em andamento.
COR = {
    ATUALIZADO: ("verde", "Atualizado"),
    PENDENTE: ("amarelo", "Pendente"),
    AGUARDANDO_VERIFICACAO: ("amarelo", "Aguardando verificação"),
    ERRO: ("vermelho", "Erro"),
    REVOGADO: ("cinza", "Revogado"),
    EM_ANDAMENTO: ("azul", "Em andamento"),
}


def selo(status: str) -> dict[str, str]:
    cor, texto = COR.get(status or "", ("amarelo", status or "Pendente"))
    return {"status": status or PENDENTE, "cor": cor, "texto": texto}


# ------------------------------------------------------------------ jurídico (dispositivo/autoridade)
VIGENTE, ALTERADA, REVOGADA, SUPERADA, SUSPENSA = "VIGENTE", "ALTERADA", "REVOGADA", "SUPERADA", "SUSPENSA"

#: Status do Acervo → `Autoridade.status` (minúsculo, ver `aut.STATUS_INATIVOS`).
#: ALTERADA não vira status: a versão antiga é encerrada por data (`valid_until`) e a nova abre.
#: AGUARDANDO_VERIFICACAO vira "vigente" SEM datas, e `vigente_em` devolve None (o gate não aprova).
PARA_AUTORIDADE = {VIGENTE: "vigente", REVOGADA: "revogado", SUPERADA: "superado", SUSPENSA: "suspenso",
                   AGUARDANDO_VERIFICACAO: "vigente", ALTERADA: "vigente"}

#: A carga antiga gravou minúsculo ("vigente"); a sincronização grava o vocabulário do Acervo.
_LEGADO_PARA_ACERVO = {"vigente": VIGENTE, "revogado": REVOGADA, "revogada": REVOGADA, "vetado": REVOGADA, "superado": SUPERADA,
                       "superada": SUPERADA, "suspenso": SUSPENSA, "suspensa": SUSPENSA, "cancelado": REVOGADA, "alterada": ALTERADA,
                       "aguardando_verificacao": AGUARDANDO_VERIFICACAO}
INATIVOS_NO = {REVOGADA, SUPERADA, SUSPENSA}


def status_no(valor: Any) -> str:
    """Status de um nó no vocabulário do Acervo, aceitando o minúsculo da carga antiga."""
    s = str(valor or "").strip()
    return _LEGADO_PARA_ACERVO.get(s.lower(), s.upper() or VIGENTE)


def status_juridico(valor: Any) -> str:
    return PARA_AUTORIDADE.get(status_no(valor), "vigente")


def validade_dias() -> int:
    """Quantos dias a última verificação na fonte oficial sustenta "vigente hoje"."""
    try:
        return max(1, int(os.getenv("ACERVO_VALIDADE_DIAS", "30")))
    except ValueError:
        return 30


def _quando(valor: Any) -> datetime | None:
    if isinstance(valor, datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=UTC)
    if isinstance(valor, str) and valor:
        try:
            d = datetime.fromisoformat(valor.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=UTC)
        except ValueError:
            return None
    return None


def autoridade_de_versao(r: dict[str, Any], *, agora: datetime | None = None) -> aut.Autoridade:
    """Uma linha de `normative_device_versions` (+ colunas da norma) como `Autoridade` de artigo.

    - artigo vem da coluna `artigo` (sincronização nova) ou do identificador antigo `art-482-a-310`;
    - a versão aberta só sustenta vigência se a última verificação na fonte está dentro da validade;
      fora dela, as datas saem e o gate trata como "vigência não comprovada".
    """
    agora = agora or datetime.now(UTC)
    norma = str(r.get("chave_norma") or "") or aut.chave_da_norma(f"{r.get('document_name') or ''} {r.get('document_number') or ''}")
    artigo = str(r.get("artigo") or "") or artigo_do_identificador(str(r.get("identifier") or ""))
    hierarquia = r.get("hierarchy") or {}
    inicio, fim = r.get("valid_from"), r.get("valid_until")
    if status_no(r.get("status")) == AGUARDANDO_VERIFICACAO:
        inicio = None
    verificada = bool(inicio)
    verificacao = _quando(r.get("ultima_verificacao")) or _quando(r.get("retrieved_at"))
    if not fim and inicio and (verificacao is None or agora - verificacao > timedelta(days=validade_dias())):
        inicio, verificada = None, False
    return aut.Autoridade(
        id=f"ndv:{r['id']}", tipo="artigo", chave=f"art:{norma}:{artigo.lower()}",
        titulo=f"art. {artigo.upper()} ({r.get('nome_amigavel') or r.get('document_name') or norma})",
        texto=str(r.get("text") or ""), norma=norma, artigo=artigo,
        paragrafo=str(r.get("paragrafo") or hierarquia.get("paragrafo") or ""), inciso=str(r.get("inciso") or hierarquia.get("inciso") or ""),
        vigencia_inicio=str(inicio or ""), vigencia_fim=str(fim or ""), versao=str(r.get("version") or ""),
        status=status_juridico(r.get("status")), superado_por=str(r.get("superada_por") or ""),
        fonte_oficial=str(r.get("official_source") or ""), url=str(r.get("source_url") or ""),
        verificado_em=str(verificacao or ""), verificada=verificada, origem="normative_device_versions",
    )


def artigo_do_identificador(identificador: str) -> str:
    """"art-482-310" → "482"; "art-482-A-310" → "482-a"; "art-1º-1" → "1"; "art-482" / "adct.art-1" → id novo."""
    s = identificador.removeprefix("adct.")
    m = re.match(r"^art-(\d[\d.]*)\s*[ºo°]?(?:-([A-Za-z]{1,2}))?(?:-\d+)?(?:~\d+)?$", s.strip())
    if not m:
        return ""
    n = m[1].replace(".", "")
    return f"{n}-{m[2].lower()}" if m[2] else n


def hoje() -> date:
    return datetime.now(UTC).date()
