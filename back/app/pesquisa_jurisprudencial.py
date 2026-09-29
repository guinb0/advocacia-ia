"""Núcleo seguro da pesquisa jurisprudencial externa.

Este módulo não conhece jurisprudência material e não transforma resposta de
buscador em precedente. Providers só devolvem candidatos; a entrada na peça é
permitida exclusivamente depois de a fonte original ser aberta e marcada como
``VERIFIED``.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from enum import StrEnum
import re
from typing import Any, Protocol

from . import tribunais


class StatusVerificacao(StrEnum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    REVOKED = "REVOKED"


class DisponibilidadeProvider(StrEnum):
    MANUAL_ONLY = "MANUAL_ONLY"
    UNAVAILABLE = "UNAVAILABLE"
    AUTOMATED = "AUTOMATED"


@dataclass(frozen=True)
class CapacidadeProvider:
    tribunal: str
    fonte_oficial: str
    disponibilidade: DisponibilidadeProvider
    mecanismo: str
    parametros: tuple[str, ...] = ()
    limitacoes: str = ""
    ultima_consulta: datetime | None = None
    ultimo_erro: str = ""


@dataclass(frozen=True)
class ConsultaJurisprudencial:
    questao: str
    texto: str
    tribunal: str
    filtros: dict[str, Any] = field(default_factory=dict)
    camada: str = "TRIBUNAL_COMPETENTE"


@dataclass
class PlanoPesquisaJurisprudencial:
    tribunal_principal: str
    consultas: list[ConsultaJurisprudencial]
    ordem_camadas: tuple[str, ...] = ("BASE_VERIFICADA", "TRIBUNAL_COMPETENTE", "TST", "AMPLIACAO")

    def como_dict(self) -> dict[str, Any]:
        return {"tribunal_principal": self.tribunal_principal,
                "ordem_camadas": list(self.ordem_camadas),
                "consultas": [asdict(c) for c in self.consultas]}


@dataclass
class PrecedenteEstruturado:
    tribunal: str | None = None
    numero_processo: str | None = None
    orgao_julgador: str | None = None
    relator: str | None = None
    julgado_em: date | None = None
    publicado_em: date | None = None
    ementa: str | None = None
    tema: str | None = None
    subtema: str | None = None
    contexto_fatico: str | None = None
    fundamentos: str | None = None
    resultado: str | None = None
    valor_pedido: float | None = None
    valor_deferido: float | None = None
    classificacao: str = "INDETERMINADO"
    fonte_url: str | None = None
    consultado_em: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status_verificacao: StatusVerificacao = StatusVerificacao.UNVERIFIED

    def apto_para_citacao(self) -> bool:
        """Não há exceção para snippet, URL presumida ou metadado incompleto."""
        return bool(self.fonte_url and self.tribunal and self.numero_processo and self.ementa
                    and self.status_verificacao is StatusVerificacao.VERIFIED)


class JurisprudenceProvider(Protocol):
    def capacidade(self) -> CapacidadeProvider: ...
    def pesquisar(self, consulta: ConsultaJurisprudencial) -> list[PrecedenteEstruturado]: ...


class ProviderManual:
    """Representa fonte oficial cujo uso automatizado ainda não foi validado.

    Falhar explicitamente é deliberado: impede que uma mudança de HTML, CAPTCHA
    ou página protegida vire coleta silenciosa de precedentes falsos.
    """
    def __init__(self, capacidade: CapacidadeProvider):
        self._capacidade = capacidade

    def capacidade(self) -> CapacidadeProvider:
        return self._capacidade

    def pesquisar(self, consulta: ConsultaJurisprudencial) -> list[PrecedenteEstruturado]:
        return []


def _capacidade_padrao(sigla: str) -> CapacidadeProvider:
    if sigla == "TST":
        url = "https://jurisprudencia.tst.jus.br/"
    elif sigla in {"STF", "STJ"}:
        url = f"https://jurisprudencia.{sigla.lower()}.jus.br/"
    else:
        numero = int(sigla.removeprefix("TRT"))
        url = f"https://www.trt{numero}.jus.br/"
    return CapacidadeProvider(sigla, url, DisponibilidadeProvider.MANUAL_ONLY,
        "portal oficial (automação ainda não homologada)",
        ("termos", "periodo", "processo", "relator", "orgao_julgador"),
        "Não executa scraping, CAPTCHA, autenticação ou endpoint não documentado.")


def providers_padrao() -> dict[str, JurisprudenceProvider]:
    siglas = [f"TRT{i}" for i in range(1, 25)] + ["TST", "STF", "STJ"]
    return {sigla: ProviderManual(_capacidade_padrao(sigla)) for sigla in siglas}


def _limpar(texto: object, limite: int = 160) -> str:
    return " ".join(str(texto or "").split())[:limite]


def _tokens(texto: str, limite: int = 8) -> str:
    palavras = re.findall(r"[\wÀ-ÿ-]{4,}", texto, flags=re.I)
    vistos: list[str] = []
    for palavra in palavras:
        chave = palavra.casefold()
        if chave not in {x.casefold() for x in vistos}:
            vistos.append(palavra)
    return " ".join(vistos[:limite])


def tribunal_do_caso(uf: object = "", contexto: str = "") -> str:
    """Usa dado estruturado antes do OCR; SP segue exigindo vara/comarca para desambiguar."""
    sigla = tribunais.normalizar_uf(uf)
    encontrados = tribunais.UF_PARA_TRT.get(sigla, [])
    if len(encontrados) == 1:
        return encontrados[0]
    # Para SP a inferência sem comarca seria uma escolha jurídica inventada.
    return ""


def planejar(plano: dict[str, Any] | None, contexto: str, *, uf: object = "") -> PlanoPesquisaJurisprudencial:
    """Gera consultas factuais e jurídicas a partir do plano, nunca de teses hard-coded."""
    plano = plano or {}
    tribunal = tribunal_do_caso(uf, contexto)
    fatos = [_limpar(x.get("fato"), 180) for x in plano.get("cronologia", []) if isinstance(x, dict)]
    ancora = _tokens(" ".join(fatos) or contexto, 10)
    consultas: list[ConsultaJurisprudencial] = []
    for tese in plano.get("teses", []):
        if not isinstance(tese, dict) or not tese.get("tese"):
            continue
        juridico = _limpar(tese.get("tese"), 180)
        sustentacao = _tokens(" ".join(map(str, tese.get("fatos_que_sustentam") or [])), 8)
        texto = " ".join(x for x in (juridico, ancora, sustentacao) if x)
        consultas.append(ConsultaJurisprudencial(juridico, texto[:700], tribunal, camada="TRIBUNAL_COMPETENTE"))
    if not consultas:
        consultas.append(ConsultaJurisprudencial("visão geral", _tokens(contexto, 18), tribunal,
                                                 camada="TRIBUNAL_COMPETENTE"))
    return PlanoPesquisaJurisprudencial(tribunal, consultas)


def classificar_freshness(precedente: PrecedenteEstruturado, *, max_dias: int = 365) -> bool:
    base = precedente.consultado_em
    return (datetime.now(timezone.utc) - base).days <= max_dias


def pontuar(precedente: PrecedenteEstruturado, *, tribunal_preferido: str,
            similaridade_juridica: float, similaridade_fatica: float) -> dict[str, float]:
    """Score explicável; entrada não verificada recebe zero e nunca pode subir ao texto."""
    verificado = 1.0 if precedente.apto_para_citacao() else 0.0
    componentes = {
        "verificacao": verificado * .30,
        "tribunal_competente": (.18 if precedente.tribunal == tribunal_preferido else .0),
        "similaridade_juridica": max(0., min(1., similaridade_juridica)) * .20,
        "similaridade_fatica": max(0., min(1., similaridade_fatica)) * .20,
        "fonte_completa": (.07 if precedente.fonte_url and precedente.ementa else .0),
        "atualidade": (.05 if classificar_freshness(precedente) else .0),
    }
    componentes["total"] = round(sum(componentes.values()), 4)
    return componentes
