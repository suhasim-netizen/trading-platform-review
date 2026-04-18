"""Strategy registry (Phase 1).

Client strategy IP is private; no cross-tenant reads.

Phase 1: in-memory registry is acceptable. Ownership model is implemented now:
- platform-owned strategies are visible to all tenants
- tenant-owned strategies are visible only to the owning tenant_id
"""

from __future__ import annotations

from dataclasses import replace
from threading import RLock

from .base import StrategyMeta, StrategyOwnerKind

class StrategyAccessDenied(PermissionError):
    """Raised when a tenant attempts to access a strategy it does not own."""

class StrategyNotFound(KeyError):
    pass


_LOCK = RLock()
_REGISTRY: dict[str, StrategyMeta] = {}


def register(meta: StrategyMeta) -> None:
    """Register a strategy metadata record."""
    if not meta.strategy_id.strip():
        raise ValueError("strategy_id must be non-empty")
    if meta.owner_kind == StrategyOwnerKind.TENANT and not meta.tenant_id:
        raise ValueError("tenant-owned strategies require tenant_id")
    if meta.owner_kind == StrategyOwnerKind.PLATFORM:
        # Normalize: platform strategies must not be tenant-scoped.
        meta = replace(meta, tenant_id=None)
    with _LOCK:
        _REGISTRY[meta.strategy_id] = meta


def list_strategies(*, owner_kind: StrategyOwnerKind | None = None, tenant_id: str | None = None) -> list[StrategyMeta]:
    """List visible strategies for a caller.

    - If `tenant_id` is provided, tenant-owned strategies will be filtered to that tenant.
    - Platform strategies are always visible.
    """
    with _LOCK:
        values = list(_REGISTRY.values())

    out: list[StrategyMeta] = []
    for m in values:
        if owner_kind is not None and m.owner_kind != owner_kind:
            continue
        if m.owner_kind == StrategyOwnerKind.TENANT and tenant_id is not None and m.tenant_id != tenant_id:
            continue
        if m.owner_kind == StrategyOwnerKind.TENANT and tenant_id is None:
            # Caller didn't specify a tenant_id; do not leak tenant-owned entries.
            continue
        out.append(m)
    return out


def get_strategy(strategy_id: str, *, caller_tenant_id: str | None = None) -> StrategyMeta:
    """Get a single strategy with tenant guard enforced."""
    with _LOCK:
        meta = _REGISTRY.get(strategy_id)
    if meta is None:
        raise StrategyNotFound(strategy_id)
    if meta.owner_kind == StrategyOwnerKind.TENANT:
        if caller_tenant_id is None or caller_tenant_id != meta.tenant_id:
            raise StrategyAccessDenied("strategy is owned by another tenant")
    return meta


# Backwards-compatible name used by existing imports.
def load_strategy_for_tenant(*, strategy_id: str, requester_tenant_id: str) -> StrategyMeta:
    return get_strategy(strategy_id, caller_tenant_id=requester_tenant_id)


