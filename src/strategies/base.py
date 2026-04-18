# DRAFT — Pending Security Architect sign-off (P1-03)

"""Strategy base interfaces.

Client strategy IP is private; no cross-tenant reads.

Phase 1: the Director/platform owns all strategies; tenants can only allocate capital.
Phase 2+: tenants may register private strategies (owner_kind='tenant') which must never
be readable by other tenants.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any


class StrategyOwnerKind(str, Enum):
    PLATFORM = "platform"
    TENANT = "tenant"


@dataclass(frozen=True, slots=True)
class StrategyMeta:
    """Registry metadata (no executable code)."""

    strategy_id: str
    name: str
    owner_kind: StrategyOwnerKind = StrategyOwnerKind.PLATFORM
    owner_id: str = "director"
    # For tenant-owned strategies, this must equal the owning tenant_id. For platform, it is None.
    tenant_id: str | None = None
    # Phase 2 will define code packaging; keep as opaque reference for now.
    code_ref: str | None = None
    # Parameters may exist but must never be returned across tenants.
    params: dict[str, Any] | None = None


class Strategy(ABC):
    """Minimal strategy interface for Phase 2 to extend."""

    meta: StrategyMeta

    @abstractmethod
    def describe(self) -> dict[str, Any]:
        """Return a serializable description for dashboards (never includes secrets)."""

