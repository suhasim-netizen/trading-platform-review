# PAPER TRADING MODE

from __future__ import annotations

import pytest

from brokers.models import InstrumentType, Order, OrderSide
from config import get_settings
from execution.account_router import AccountRouter


def _mk_order(it: InstrumentType) -> Order:
    return Order(symbol="SPY", instrument_type=it, side=OrderSide.BUY, quantity=1)


def test_equity_routes_to_equity_account(monkeypatch):
    monkeypatch.setenv("TS_EQUITY_ACCOUNT_ID", "EQ-1")
    get_settings.cache_clear()
    assert AccountRouter().resolve(_mk_order(InstrumentType.EQUITY), tenant_id="director") == "EQ-1"


def test_futures_routes_to_futures_account(monkeypatch):
    monkeypatch.setenv("TS_FUTURES_ACCOUNT_ID", "FUT-1")
    get_settings.cache_clear()
    assert AccountRouter().resolve(_mk_order(InstrumentType.FUTURES), tenant_id="director") == "FUT-1"


def test_options_routes_to_options_account(monkeypatch):
    monkeypatch.setenv("TS_OPTIONS_ACCOUNT_ID", "OPT-1")
    get_settings.cache_clear()
    assert AccountRouter().resolve(_mk_order(InstrumentType.OPTIONS), tenant_id="director") == "OPT-1"


def test_unknown_instrument_raises_error(monkeypatch):
    get_settings.cache_clear()
    o = _mk_order(InstrumentType.EQUITY)
    # Create an invalid value by bypassing pydantic validation.
    o.__dict__["instrument_type"] = "weird"  # type: ignore[assignment]
    with pytest.raises(ValueError):
        AccountRouter().resolve(o, tenant_id="director")


def test_wrong_account_never_used(monkeypatch):
    monkeypatch.setenv("TS_EQUITY_ACCOUNT_ID", "EQ-OK")
    monkeypatch.setenv("TS_FUTURES_ACCOUNT_ID", "FUT-NO")
    get_settings.cache_clear()
    acct = AccountRouter().resolve(_mk_order(InstrumentType.EQUITY), tenant_id="director")
    assert acct == "EQ-OK"
    assert acct != "FUT-NO"

