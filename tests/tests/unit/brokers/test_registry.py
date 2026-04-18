"""Registry wiring — no concrete broker package required."""

import pytest

from brokers.base import BrokerAdapter
from brokers.registry import create_adapter, register_adapter, registered_brokers, resolve_adapter_class


class _StubAdapter(BrokerAdapter):
    def __init__(self, tenant_id: str) -> None:
        self.tenant_id = tenant_id

    async def authenticate(self, credentials):
        raise NotImplementedError

    async def refresh_token(self, token):
        raise NotImplementedError

    async def get_quote(self, symbol, tenant_id):
        raise NotImplementedError

    async def get_account(self, account_id, tenant_id):
        raise NotImplementedError

    async def place_order(self, order, *, tenant_id: str, account_id: str):
        raise NotImplementedError

    async def cancel_order(self, order_id, tenant_id):
        raise NotImplementedError

    async def get_positions(self, account_id, tenant_id):
        raise NotImplementedError

    def stream_quotes(self, symbols, tenant_id):
        raise NotImplementedError

    def stream_bars(self, symbol, interval, tenant_id):
        raise NotImplementedError

    def stream_order_updates(self, account_id, tenant_id):
        raise NotImplementedError


@pytest.fixture(autouse=True)
def _register_stub():
    register_adapter("stub", _StubAdapter)
    yield


def test_resolve_and_create():
    assert resolve_adapter_class("STUB") is _StubAdapter
    a = create_adapter("stub", tenant_id="t1")
    assert isinstance(a, _StubAdapter)
    assert a.tenant_id == "t1"


def test_unknown_broker():
    with pytest.raises(KeyError):
        resolve_adapter_class("nope")


def test_registered_brokers_contains_stub():
    assert "stub" in registered_brokers()
