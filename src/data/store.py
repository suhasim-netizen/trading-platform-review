"""Tenant-scoped persistence for normalised market bars (Timescale / Postgres)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from brokers.models import Bar
from db.models import MarketBar


class HistoricalDataStore:
    """Write and read ``market_bars`` rows — every path requires ``tenant_id``."""

    def upsert_bar(self, session: Session, *, tenant_id: str, trading_mode: str, bar: Bar) -> None:
        if bar.tenant_id != tenant_id:
            raise ValueError("bar.tenant_id must match tenant_id for HistoricalDataStore.upsert_bar")
        vol = _volume_to_decimal(bar.volume)
        stmt: Select[tuple[MarketBar]] = select(MarketBar).where(
            MarketBar.tenant_id == tenant_id,
            MarketBar.trading_mode == trading_mode,
            MarketBar.symbol == bar.symbol,
            MarketBar.bar_interval == bar.interval,
            MarketBar.bar_start == bar.bar_start,
        )
        row = session.execute(stmt).scalar_one_or_none()
        raw = dict(bar.raw) if bar.raw else None
        if row is None:
            session.add(
                MarketBar(
                    tenant_id=tenant_id,
                    trading_mode=trading_mode,
                    symbol=bar.symbol,
                    bar_interval=bar.interval,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=vol,
                    bar_start=bar.bar_start,
                    bar_end=bar.bar_end,
                    raw=raw,
                )
            )
            return
        row.open = bar.open
        row.high = bar.high
        row.low = bar.low
        row.close = bar.close
        row.volume = vol
        row.bar_end = bar.bar_end
        row.raw = raw

    def fetch_bars(
        self,
        session: Session,
        *,
        tenant_id: str,
        trading_mode: str,
        symbol: str,
        bar_interval: str,
        start: datetime,
        end: datetime,
    ) -> list[MarketBar]:
        """Return bars strictly within ``[start, end)`` for one tenant namespace."""
        if not tenant_id:
            raise ValueError("tenant_id is required")
        stmt = (
            select(MarketBar)
            .where(
                MarketBar.tenant_id == tenant_id,
                MarketBar.trading_mode == trading_mode,
                MarketBar.symbol == symbol,
                MarketBar.bar_interval == bar_interval,
                MarketBar.bar_start >= start,
                MarketBar.bar_start < end,
            )
            .order_by(MarketBar.bar_start.asc())
        )
        return list(session.execute(stmt).scalars().all())


def _volume_to_decimal(v: Decimal | int | None) -> Decimal | None:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


