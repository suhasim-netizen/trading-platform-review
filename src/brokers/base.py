"""Abstract broker adapter — all market and execution access goes through this contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from .models import (
    Account,
    AuthToken,
    Bar,
    BrokerCredentials,
    CancelReceipt,
    Order,
    OrderReceipt,
    OrderUpdate,
    Position,
    Quote,
)


class BrokerAdapter(ABC):
    """Broker-agnostic port. Concrete implementations live under ``brokers/<vendor>/`` only.

    Every method that touches accounts, orders, or market data accepts ``tenant_id`` so
    adapters can scope credentials, streams, and persistence correctly.
    """

    @abstractmethod
    async def authenticate(self, credentials: BrokerCredentials) -> AuthToken:
        """Perform initial auth (e.g. exchange authorization code for tokens)."""

    @abstractmethod
    async def refresh_token(self, token: AuthToken) -> AuthToken:
        """Refresh an access token; must return a new ``AuthToken`` with updated expiry."""

    @abstractmethod
    async def get_quote(self, symbol: str, tenant_id: str) -> Quote:
        """Latest quote for ``symbol`` in the context of ``tenant_id``."""

    @abstractmethod
    async def get_account(self, account_id: str, tenant_id: str) -> Account:
        """Account snapshot for the given broker account id."""

    @abstractmethod
    async def place_order(self, order: Order, *, tenant_id: str, account_id: str) -> OrderReceipt:
        """Submit ``order`` for the given broker ``account_id`` within ``tenant_id`` scope."""

    @abstractmethod
    async def cancel_order(self, order_id: str, tenant_id: str) -> CancelReceipt:
        """Request cancellation of an open order."""

    @abstractmethod
    async def get_positions(self, account_id: str, tenant_id: str) -> list[Position]:
        """Open positions for the account."""

    @abstractmethod
    def stream_quotes(self, symbols: list[str], tenant_id: str) -> AsyncIterator[Quote]:
        """Async iterator of quote updates for ``symbols`` (websocket, SSE, or polled bridge)."""

    @abstractmethod
    def stream_bars(self, symbol: str, interval: str, tenant_id: str) -> AsyncIterator[Bar]:
        """Async iterator of OHLCV bars for ``symbol`` at normalized ``interval`` (e.g. ``1m``)."""

    @abstractmethod
    def stream_order_updates(
        self, account_id: str, tenant_id: str
    ) -> AsyncIterator[OrderUpdate]:
        """Async iterator of order lifecycle events for the given account."""
