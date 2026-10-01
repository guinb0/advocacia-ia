"""Interface da busca de autoridades: o orquestrador, o gate e os auditores só conhecem `ProvedorDeAutoridades`.

Hoje a implementação é `autoridades.Registro` (BM25 + fusão com ranking vetorial, em memória, sobre o que foi
carregado para a geração). Um provedor em Postgres (pgvector + FTS + reranker) implementa os mesmos métodos e
entra no lugar sem mudar o resto do sistema.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any, Iterable, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .autoridades import Autoridade, Citacao


@dataclass(frozen=True)
class Filtros:
    data_referencia: date | None = None
    tipos: tuple[str, ...] = ()
    incluir_inativas: bool = False
    trt_competente: str = ""


@runtime_checkable
class ProvedorDeAutoridades(Protocol):
    alertas: list[str]

    def consultar(self, consulta: str, filtros: Filtros, top_k: int) -> list[tuple[Autoridade, float]]:
        """Autoridades mais pertinentes à consulta, já filtradas e na ordem da hierarquia (pontuação decrescente)."""

    def resolver(self, citacao: Citacao, data_referencia: date | None) -> dict[str, Any]:
        """Status de UMA citação (VALIDADA, REQUIRES_LEGAL_RESEARCH, SUPERADA…) e o authority_id correspondente."""

    def por_referencia(self, referencia: str) -> Autoridade | None:
        """Autoridade por id ou chave canônica (usado para achar a substituta de uma superada)."""

    def inativas_com_marcadores(self, data_referencia: date | None) -> Iterable[Autoridade]:
        """Autoridades fora de vigência que declaram marcadores de critério (para achar critério superado sem número)."""

    def adicionar(self, autoridade: Autoridade) -> None:
        """Acrescenta autoridade só para esta geração (trechos recuperados, dispositivos citados)."""

    def __len__(self) -> int: ...
