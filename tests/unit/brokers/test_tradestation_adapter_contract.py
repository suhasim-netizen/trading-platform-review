"""tradestation adapter must satisfy BrokerAdapter before registry use (no live API calls)."""

from __future__ import annotations

import inspect

import brokers.tradestation  # noqa: F401 — register_adapter side effect
from brokers.base import BrokerAdapter
from brokers.registry import registered_brokers, resolve_adapter_class


def test_tradestation_adapter_is_concrete_subclass():
    cls = resolve_adapter_class("tradestation")
    assert issubclass(cls, BrokerAdapter)
    assert not inspect.isabstract(cls)


def test_tradestation_is_registered():
    assert "tradestation" in registered_brokers()
    assert isinstance(resolve_adapter_class("tradestation"), type)
