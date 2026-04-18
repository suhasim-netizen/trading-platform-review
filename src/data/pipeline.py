"""Real-time market data pipeline: broker adapter → normalised bars → Redis (+ optional DB)."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from brokers.base import BrokerAdapter
from brokers.models import Bar

from db.session import get_session_factory

from tenancy.redis_keys import bars_channel

from .store import HistoricalDataStore


@runtime_checkable
class _AsyncRedisPublish(Protocol):
    async def publish(self, channel: str, message: str) -> Any: ...


def _interval_seconds(interval: str) -> float:
    s = interval.strip().lower()
    if len(s) < 2:
        raise ValueError("invalid interval")
    n = int(s[:-1])
    suf = s[-1]
    mult = {"s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}.get(suf)
    if mult is None or n <= 0:
        raise ValueError("invalid interval")
    return float(n) * mult


class MarketDataPipeline:
    """Consumes ``BrokerAdapter.stream_bars``, applies DQ checks, publishes tenant-scoped Redis messages."""

    def __init__(
        self,
        adapter: BrokerAdapter,
        *,
        redis: _AsyncRedisPublish,
        tenant_id: str,
        symbol: str,
        interval: str,
        trading_mode: str = "paper",
        store: HistoricalDataStore | None = None,
        logger: logging.Logger | None = None,
        outlier_move_ratio: Decimal = Decimal("0.5"),
    ) -> None:
        self._adapter = adapter
        self._redis = redis
        self._tenant_id = tenant_id
        self._symbol = symbol.strip()
        self._interval = interval.strip()
        self._trading_mode = trading_mode
        self._store = store
        self._log = logger or logging.getLogger(__name__)
        self._outlier_ratio = outlier_move_ratio
        self._last_bar_start: datetime | None = None
        self._prev_close: Decimal | None = None

    def _channel(self) -> str:
        return bars_channel(self._tenant_id, self._symbol, self._interval)

    def _normalize_bar(self, item: Bar) -> Bar:
        """Ensure platform ``Bar`` shape; adapter is responsible for broker mapping."""
        if item.tenant_id != self._tenant_id:
            self._log.warning(
                "dropped bar with tenant mismatch",
                extra={
                    "tenant_id": self._tenant_id,
                    "issue": "tenant_mismatch",
                    "symbol": self._symbol,
                    "bar_tenant_id": item.tenant_id,
                },
            )
            raise ValueError("tenant mismatch on bar")
        if item.symbol.strip().upper() != self._symbol.upper():
            self._log.warning(
                "bar symbol differs from subscription",
                extra={
                    "tenant_id": self._tenant_id,
                    "issue": "symbol_mismatch",
                    "expected": self._symbol,
                    "got": item.symbol,
                },
            )
            raise ValueError("symbol mismatch on bar")
        return item

    def _dq_checks(self, bar: Bar) -> bool:
        """Log data-quality signals; return False if the bar must not be published or persisted."""
        extra_base: dict[str, Any] = {"tenant_id": self._tenant_id, "symbol": self._symbol, "interval": self._interval}
        if bar.high < bar.low:
            self._log.warning("invalid ohlc range (high < low)", extra={**extra_base, "issue": "invalid_ohlc"})
            return False
        for label, v in (("open", bar.open), ("high", bar.high), ("low", bar.low), ("close", bar.close)):
            if v < 0:
                self._log.warning(
                    "negative price in bar", extra={**extra_base, "issue": "negative_price", "field": label}
                )
                return False
        if self._prev_close is not None and self._prev_close > 0:
            move = abs(bar.close - self._prev_close) / self._prev_close
            if move > self._outlier_ratio:
                self._log.warning(
                    "large bar-to-bar move vs prior close",
                    extra={**extra_base, "issue": "outlier_move", "ratio": float(move)},
                )
        try:
            step = _interval_seconds(self._interval)
        except ValueError:
            step = 0.0
        if self._last_bar_start is not None and step > 0:
            gap = (bar.bar_start - self._last_bar_start).total_seconds()
            if gap > step * 1.5:
                self._log.warning(
                    "possible missing bars (gap vs interval)",
                    extra={**extra_base, "issue": "gap", "gap_seconds": gap, "expected_seconds": step},
                )
        return True

    async def run(self, *, max_bars: int | None = None) -> None:
        """Read from ``stream_bars`` until stream ends or ``max_bars`` is reached (tests)."""
        stream = self._adapter.stream_bars(self._symbol, self._interval, self._tenant_id)
        n = 0
        async for item in stream:
            try:
                bar = self._normalize_bar(item)
            except ValueError:
                continue
            print(f"[PIPELINE] Bar received: {bar}")
            if not self._dq_checks(bar):
                continue
            self._last_bar_start = bar.bar_start
            self._prev_close = bar.close

            if self._store is not None:
                factory = get_session_factory()
                with factory() as session:
                    with session.begin():
                        self._store.upsert_bar(
                            session,
                            tenant_id=self._tenant_id,
                            trading_mode=self._trading_mode,
                            bar=bar,
                        )

            payload = bar.model_dump(mode="json")
            await self._redis.publish(self._channel(), json.dumps(payload, separators=(",", ":")))
            n += 1
            if max_bars is not None and n >= max_bars:
                break


