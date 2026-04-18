# PAPER TRADING MODE

"""Multi-symbol bar scanner — one ``BrokerAdapter.stream_bars`` task per symbol (ADR 0004)."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable, Mapping
from typing import Any

from brokers.base import BrokerAdapter
from brokers.models import Bar


def _normalize_symbol(sym: str) -> str:
    return sym.strip()


def _normalize_interval(interval: str) -> str:
    """Map common forms (``5min``, ``5 m``) to adapter form (``5m``)."""
    s = interval.strip().lower().replace(" ", "")
    if s.endswith("min") and s[:-3].isdigit():
        return f"{int(s[:-3])}m"
    return interval.strip()


async def _call_handler(handler: Callable[[Bar], Any], bar: Bar) -> None:
    out = handler(bar)
    if inspect.isawaitable(out):
        await out


class MultiSymbolScanner:
    """Consumes per-symbol bar streams and dispatches to registered handlers (tenant-scoped)."""

    def __init__(self, tenant_id: str, adapter: BrokerAdapter) -> None:
        self._tenant_id = tenant_id
        self._adapter = adapter
        self._symbols: list[str] = []
        self._interval: str = "5m"

    @property
    def symbols(self) -> tuple[str, ...]:
        """Symbols from the last successful ``subscribe()`` call."""
        return tuple(self._symbols)

    @property
    def interval(self) -> str:
        """Normalized bar interval (e.g. ``5m``) from the last ``subscribe()``."""
        return self._interval

    async def subscribe(self, symbols: list[str], interval: str = "5min") -> None:
        """Validate symbols and store subscription; uses ``asyncio.gather`` for concurrent setup."""

        async def _check(sym: str) -> str:
            s = _normalize_symbol(sym)
            if not s:
                raise ValueError("symbol must be non-empty")
            return s

        self._symbols = list(await asyncio.gather(*[_check(s) for s in symbols]))
        self._interval = _normalize_interval(interval)

    async def run(
        self,
        signal_handlers: Mapping[str, Callable[[Bar], Any]],
        max_bars: int | None = None,
    ) -> None:
        """Run one async consumer per symbol; invokes ``handler(bar)`` as bars arrive."""
        if not self._symbols:
            raise RuntimeError("subscribe() must be called before run()")

        done = asyncio.Event()
        total = 0
        lock = asyncio.Lock()

        async def _consume(sym: str) -> None:
            nonlocal total
            handler = signal_handlers.get(sym) or signal_handlers.get(sym.upper())
            if handler is None:
                return
            stream = self._adapter.stream_bars(sym, self._interval, self._tenant_id)
            async for bar in stream:
                if done.is_set():
                    break
                if bar.tenant_id != self._tenant_id:
                    continue
                await _call_handler(handler, bar)
                if max_bars is None:
                    continue
                async with lock:
                    total += 1
                    if total >= max_bars:
                        done.set()
                        break

        await asyncio.gather(*[_consume(s) for s in self._symbols])
