"""Configuration-driven resolution of broker implementation by logical name (e.g. ``tradestation``).

Platform and strategy code must depend only on ``BrokerAdapter``; this module wires tenant
``broker`` fields to concrete classes at startup or request time.
"""

from __future__ import annotations

from threading import RLock
from typing import Any

from .base import BrokerAdapter

_REGISTRY: dict[str, type[BrokerAdapter]] = {}
_LOCK = RLock()


def register_adapter(name: str, cls: type[BrokerAdapter]) -> type[BrokerAdapter]:
    key = name.strip().lower()
    if not key:
        raise ValueError("broker name must be non-empty")
    with _LOCK:
        _REGISTRY[key] = cls
    return cls


def resolve_adapter_class(broker: str) -> type[BrokerAdapter]:
    key = broker.strip().lower()
    with _LOCK:
        if key not in _REGISTRY:
            raise KeyError(
                f"unknown broker adapter: {broker!r}; registered: {sorted(_REGISTRY)}"
            )
        return _REGISTRY[key]


def create_adapter(broker: str, **kwargs: Any) -> BrokerAdapter:
    """Instantiate the adapter for ``broker``; kwargs are passed to the concrete ``__init__``."""
    cls = resolve_adapter_class(broker)
    return cls(**kwargs)


def registered_brokers() -> frozenset[str]:
    with _LOCK:
        return frozenset(_REGISTRY.keys())


def _clear_registry_for_tests() -> None:
    """Test-only hook to reset global registry state."""
    with _LOCK:
        _REGISTRY.clear()
