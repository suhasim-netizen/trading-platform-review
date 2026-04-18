"""Broker adapter factory (Task 6).

Core application code must depend only on BrokerAdapter + this factory/registry.
Concrete adapters are selected by Settings (e.g. BROKER_IMPL=tradestation).
"""

from __future__ import annotations

from brokers.base import BrokerAdapter
from brokers.registry import create_adapter

from config import Settings

import brokers  # noqa: F401 — composition-side effect: registers concrete adapters inside brokers/


def build_broker_adapter(settings: Settings) -> BrokerAdapter:
    """Build the concrete adapter selected by Settings.

    The key must match a class registered in `brokers.registry` (e.g. `tradestation`).
    """

    key = settings.broker_impl.strip().lower()
    if not key:
        raise ValueError("BROKER_IMPL must be non-empty")

    # Adapter constructors may accept configuration kwargs; stubs accept **kwargs.
    return create_adapter(
        key,
        auth_base_url=settings.broker_auth_base_url,
        api_base_url=settings.broker_api_base_url,
        market_data_base_url=settings.market_data_base_url,
        ws_base_url=settings.broker_ws_base_url,
        client_id=settings.ts_client_id or settings.broker_client_id,
        client_secret=settings.ts_client_secret or settings.broker_client_secret,
        redirect_uri=settings.ts_redirect_uri or settings.broker_redirect_uri,
        paper_trading_mode=settings.paper_trading_mode,
    )


