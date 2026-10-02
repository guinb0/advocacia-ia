"""Schemas e imutabilidade da única fonte de verdade da Pipeline V2."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


FROZEN_FIELDS = ("facts", "issues", "authorities", "requests", "calculations", "tables", "metadata")


def _normal(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _normal(v) for k, v in sorted(value.items()) if not str(k).startswith("_")}
    if isinstance(value, (list, tuple)):
        return [_normal(v) for v in value]
    return value


def _fingerprint(value: Any) -> str:
    raw = json.dumps(_normal(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


@dataclass
class CaseStateV2:
    facts: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    issues: list[dict[str, Any]] = field(default_factory=list)
    authorities: list[dict[str, Any]] = field(default_factory=list)
    requests: list[dict[str, Any]] = field(default_factory=list)
    calculations: list[dict[str, Any]] = field(default_factory=list)
    tables: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    internal_trace: dict[str, Any] = field(default_factory=dict)
    prose_sections: list[dict[str, Any]] = field(default_factory=list)
    _frozen_hash: str | None = None

    def frozen_projection(self) -> dict[str, Any]:
        return {name: copy.deepcopy(getattr(self, name)) for name in FROZEN_FIELDS}

    def finalize(self) -> None:
        self._frozen_hash = _fingerprint(self.frozen_projection())

    def verify_immutable(self) -> list[str]:
        if not self._frozen_hash:
            return ["PETITION_PLAN_NOT_FINALIZED"]
        return [] if _fingerprint(self.frozen_projection()) == self._frozen_hash else ["PETITION_PLAN_MUTATED"]

    def as_dict(self) -> dict[str, Any]:
        return {
            "facts": self.facts, "events": self.events, "issues": self.issues,
            "authorities": self.authorities, "requests": self.requests,
            "calculations": self.calculations, "tables": self.tables,
            "metadata": self.metadata, "internal_trace": self.internal_trace,
            "prose_sections": self.prose_sections, "plan_hash": self._frozen_hash,
        }


def finalizar_plano(state: CaseStateV2) -> CaseStateV2:
    """Valida invariantes estruturais e congela o plano sem bloquear rascunho."""
    semantic_keys: set[str] = set()
    findings: list[dict[str, str]] = []
    calculations = {str(c.get("calculation_id") or ""): c for c in state.calculations}
    for request in state.requests:
        key = str(request.get("semantic_key") or "").strip().casefold()
        if key and key in semantic_keys:
            findings.append({"kind": "CRITICAL", "code": "DUPLICATE_REQUEST", "request_id": str(request.get("request_id") or "")})
        semantic_keys.add(key)
        if request.get("type") == "MONETARY" and not request.get("calculation_id"):
            findings.append({"kind": "NEEDS_REVIEW", "code": "MISSING_CALCULATION", "request_id": str(request.get("request_id") or "")})
        calc_id = str(request.get("calculation_id") or "")
        if calc_id and calc_id not in calculations:
            findings.append({"kind": "NEEDS_REVIEW", "code": "UNKNOWN_CALCULATION", "request_id": str(request.get("request_id") or "")})
    state.internal_trace["plan_findings"] = findings
    state.finalize()
    return state
