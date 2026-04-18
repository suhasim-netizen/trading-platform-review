# DRAFT — Pending Security Architect sign-off (P1-03)

"""Audit logging (draft).

Requirement: audit events MUST include tenant_id (hard fail if missing).
This module intentionally does not log secrets or token values.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class AuditLogger:
    def write(self, *, tenant_id: str, event_type: str, metadata: dict[str, Any] | None = None) -> None:
        raise NotImplementedError


@dataclass
class InMemoryAuditLogger(AuditLogger):
    events: list[dict[str, Any]] = field(default_factory=list)

    def write(self, *, tenant_id: str, event_type: str, metadata: dict[str, Any] | None = None) -> None:
        if not tenant_id:
            raise ValueError("tenant_id is required for audit events")
        self.events.append({"tenant_id": tenant_id, "event_type": event_type, "metadata": metadata or {}})

