# PAPER TRADING MODE

"""Strategy runner (bar -> signal) (tenant-scoped).

ADR 0002: StrategyRunner subscribes to tenant-scoped bar events (from MarketDataPipeline via Redis),
loads strategy params from strategy registry, generates signals, then passes signals to OrderRouter.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Match pytest.ini ``pythonpath = src`` so ``python -m src.execution.runner`` from repo root resolves
# top-level packages (``brokers``, ``tenancy``, ``config``, …) under ``src/``.
_SRC_ROOT = Path(__file__).resolve().parent.parent
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

import argparse
import asyncio
import importlib
import json
import os
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol

import brokers  # noqa: F401 — ensure adapter registration side effects
from brokers.registry import create_adapter
from brokers.models import AuthToken, Bar
from brokers.exceptions import BrokerAuthError, BrokerError
from config import get_settings
from db.models import Strategy as DbStrategy
from db.models import Tenant
from db.session import get_session_factory, init_db
from services.audit_log import InMemoryAuditLogger
from services.broker_credentials_store import BrokerCredentialsStore
from data.pipeline import MarketDataPipeline
from execution.scanner import MultiSymbolScanner
from strategies.base import StrategyMeta, StrategyOwnerKind
from strategies.registry import StrategyAccessDenied, StrategyNotFound, load_strategy_for_tenant, register
from tenancy.redis_keys import bars_channel

from .models import Signal, SignalType
from .logger import ExecutionLogger
from .router import OrderRouter
from .tracker import PositionTracker


class BarSubscriber(Protocol):
    async def subscribe(self, channel: str) -> AsyncIterator[str]: ...


SignalFn = Callable[[Bar, StrategyMeta], list[Signal]]


def _default_signal_fn(bar: Bar, meta: StrategyMeta) -> list[Signal]:
    # Phase 2 scaffolding: no alpha logic here; tests inject their own.
    return []


def _normalize_code_ref(code_ref: str) -> str:
    s = code_ref.strip()
    if s.startswith("src."):
        return s[4:]
    return s


def _strategy_meta_from_row(row: DbStrategy) -> StrategyMeta:
    if row.owner_kind == "platform":
        return StrategyMeta(
            strategy_id=row.id,
            name=row.name,
            owner_kind=StrategyOwnerKind.PLATFORM,
            owner_id=row.owner_tenant_id or "director",
            tenant_id=None,
            code_ref=row.code_ref,
            params={},
        )
    return StrategyMeta(
        strategy_id=row.id,
        name=row.name,
        owner_kind=StrategyOwnerKind.TENANT,
        owner_id=row.owner_tenant_id or "director",
        tenant_id=row.owner_tenant_id,
        code_ref=row.code_ref,
        params={},
    )


def _bar_to_dict(bar: Bar) -> dict[str, Any]:
    return {
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
        "timestamp": bar.bar_start.isoformat(),
    }


def _dict_to_signals(
    raw: dict[str, Any] | None,
    *,
    tenant_id: str,
    trading_mode: str,
    strategy_id: str,
) -> list[Signal]:
    if not raw:
        return []
    action = (raw.get("action") or "").lower()
    sym = str(raw.get("symbol", "")).strip()
    sid_raw = raw.get("strategy_id")
    use_sid = str(sid_raw).strip() if sid_raw else strategy_id
    qty = raw.get("quantity", Decimal("1"))
    try:
        qd = qty if isinstance(qty, Decimal) else Decimal(str(qty))
    except Exception:
        qd = Decimal("1")
    inst = (raw.get("instrument_type") or "equity").lower()
    params: dict[str, Any] = {"instrument_type": inst}
    if raw.get("order_side"):
        params["order_side"] = str(raw["order_side"])

    if action == "buy":
        return [
            Signal(
                tenant_id=tenant_id,
                trading_mode=trading_mode,
                strategy_id=use_sid,
                symbol=sym,
                signal_type=SignalType.ENTER,
                signal_strength=qd,
                params=params,
            )
        ]
    if action == "sell":
        if inst == "futures" and params.get("order_side") == "sell":
            return [
                Signal(
                    tenant_id=tenant_id,
                    trading_mode=trading_mode,
                    strategy_id=use_sid,
                    symbol=sym,
                    signal_type=SignalType.ENTER,
                    signal_strength=qd,
                    params=params,
                )
            ]
        return [
            Signal(
                tenant_id=tenant_id,
                trading_mode=trading_mode,
                strategy_id=use_sid,
                symbol=sym,
                signal_type=SignalType.EXIT,
                signal_strength=qd,
                params=params,
            )
        ]
    return []


def _make_signal_fn(handler: Any, tenant_id: str, trading_mode: str, strategy_id: str) -> SignalFn:
    symbols_filter = getattr(handler, "symbols", None)

    def _fn(bar: Bar, meta: StrategyMeta) -> list[Signal]:
        if symbols_filter is not None:
            sym_u = bar.symbol.strip().upper()
            allowed = {s.strip().upper() for s in symbols_filter}
            if sym_u not in allowed:
                return []
        raw = handler.on_bar(bar.symbol, _bar_to_dict(bar))
        return _dict_to_signals(
            raw,
            tenant_id=tenant_id,
            trading_mode=trading_mode,
            strategy_id=strategy_id,
        )

    return _fn


def _ensure_strategy_ready(strategy_id: str, tenant_id: str, trading_mode: str) -> SignalFn:
    """Load strategy module from DB ``code_ref``, register ``StrategyMeta``, return bar handler."""
    factory = get_session_factory()
    with factory() as s:
        row = s.get(DbStrategy, strategy_id)
    if row is None:
        raise SystemExit(
            f"Strategy '{strategy_id}' not found in strategies table. Run: python scripts/seed_strategies.py"
        )

    code_ref = (row.code_ref or "").strip()
    if not code_ref:
        raise SystemExit(f"Strategy '{strategy_id}' has empty code_ref in database")

    mod_name = _normalize_code_ref(code_ref)
    try:
        mod = importlib.import_module(mod_name)
    except ModuleNotFoundError:
        stem = mod_name.split(".")[-1]
        raise SystemExit(
            f"Strategy module not found: {code_ref}. Create src/strategies/{stem}.py"
        ) from None

    try:
        load_strategy_for_tenant(strategy_id=strategy_id, requester_tenant_id=tenant_id)
    except StrategyNotFound:
        register(_strategy_meta_from_row(row))

    try:
        load_strategy_for_tenant(strategy_id=strategy_id, requester_tenant_id=tenant_id)
    except StrategyNotFound:
        raise SystemExit(f"unknown strategy_id: {strategy_id}")
    except StrategyAccessDenied:
        raise SystemExit(f"access denied for strategy_id: {strategy_id} (tenant mismatch)")

    cls = getattr(mod, "HANDLER_CLASS", None)
    if cls is None:
        return _default_signal_fn
    return _make_signal_fn(cls(), tenant_id, trading_mode, strategy_id)


class StrategyRunner:
    def __init__(
        self,
        *,
        tenant_id: str,
        trading_mode: str,
        strategy_id: str,
        symbol: str,
        interval: str,
        subscriber: BarSubscriber,
        router: OrderRouter,
        signal_fn: SignalFn | None = None,
        account_id: str | None = None,
    ) -> None:
        if not tenant_id or not trading_mode or not strategy_id:
            raise ValueError("tenant_id, trading_mode, and strategy_id are required")
        self._tenant_id = tenant_id
        self._trading_mode = trading_mode
        self._strategy_id = strategy_id
        self._symbol = symbol.strip()
        self._interval = interval.strip()
        self._sub = subscriber
        self._router = router
        self._signal_fn = signal_fn or _default_signal_fn
        self._account_id = account_id

        self._meta = load_strategy_for_tenant(strategy_id=strategy_id, requester_tenant_id=tenant_id)

    def _channel(self) -> str:
        return bars_channel(self._tenant_id, self._symbol, self._interval)

    def _parse_bar(self, msg: str) -> Bar | None:
        try:
            payload = json.loads(msg)
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        try:
            bar = Bar.model_validate(payload)
        except Exception:
            return None
        if bar.tenant_id != self._tenant_id:
            # ADR: mismatched tenant events must be dropped.
            return None
        return bar

    async def run(self, *, max_bars: int | None = None) -> None:
        n = 0
        async for raw in self._sub.subscribe(self._channel()):
            bar = self._parse_bar(raw)
            if bar is None:
                continue
            print(f"[BAR] {bar.symbol} {bar.bar_start.isoformat()} close={bar.close}")
            sigs = self._signal_fn(bar, self._meta)
            for s in sigs:
                if s.tenant_id != self._tenant_id or s.trading_mode != self._trading_mode:
                    continue
                print(f"[SIGNAL] {s.signal_type.value} {s.symbol} strength={s.signal_strength}")
                await self._router.route(s)
            n += 1
            if max_bars is not None and n >= max_bars:
                break


class _SimulatedSubscriber:
    """Fallback subscriber that emits synthetic bars (no external dependencies).

    Used for smoke-start validation when Redis wiring is not configured.
    """

    def __init__(self, *, tenant_id: str, symbol: str, interval: str) -> None:
        self._tenant_id = tenant_id
        self._symbol = symbol
        self._interval = interval

    async def subscribe(self, channel: str) -> AsyncIterator[str]:
        now = datetime.now(UTC)
        i = 0
        while True:
            bar = Bar(
                tenant_id=self._tenant_id,
                symbol=self._symbol,
                interval=self._interval,
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal("100") + Decimal(str(i % 3)),
                volume=Decimal("1"),
                bar_start=now + timedelta(minutes=i),
                bar_end=now + timedelta(minutes=i + 1),
            )
            yield json.dumps(bar.model_dump(mode="json"))
            i += 1
            await asyncio.sleep(1.0)


class _InProcessPubSub:
    """Minimal in-process pub/sub for wiring MarketDataPipeline -> StrategyRunner in CLI runs."""

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[str]] = {}

    async def publish(self, channel: str, message: str) -> None:
        q = self._queues.setdefault(channel, asyncio.Queue())
        await q.put(message)

    async def subscribe(self, channel: str) -> AsyncIterator[str]:
        q = self._queues.setdefault(channel, asyncio.Queue())
        while True:
            yield await q.get()


class _FanInBarSubscriber:
    """Feeds StrategyRunner from a single queue (multi-symbol MultiSymbolScanner fan-in)."""

    def __init__(self, queue: asyncio.Queue[str]) -> None:
        self._queue = queue

    async def subscribe(self, channel: str) -> AsyncIterator[str]:
        while True:
            yield await self._queue.get()


def _parse_symbol_list(raw: str) -> list[str]:
    """Split CLI ``--symbol`` on commas; normalize to uppercase tickers."""
    out: list[str] = []
    for part in raw.replace(" ", "").split(","):
        p = part.strip().upper()
        if p and p not in out:
            out.append(p)
    return out if out else ["SPY"]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m src.execution.runner")
    p.add_argument("--tenant", required=True, dest="tenant_id")
    p.add_argument("--strategy", required=True, dest="strategy_id")
    p.add_argument("--mode", required=True, choices=["paper", "live"], dest="trading_mode")
    p.add_argument("--symbol", default="SPY")
    p.add_argument("--interval", default="1m")
    p.add_argument("--account-id", default="A1")
    p.add_argument("--max-bars", type=int, default=0, help="If >0, stop after N bars (smoke test).")
    return p.parse_args(argv)


async def _proactive_oauth_refresh(adapter: Any, tok_pre: AuthToken) -> None:
    """Refresh the access token only when it is missing expiry or expires within 10 minutes.

    Skipping refresh when the token is still healthy avoids multiple runner processes
    serializing on one TradeStation ``refresh_token`` call (~seconds) against the same DB row.
    """
    if tok_pre.expires_at is not None:
        remaining = tok_pre.expires_at - datetime.now(UTC)
        if remaining.total_seconds() > 600:
            print("[RUNNER] Token valid — skipping refresh")
            return

    print("[RUNNER] Proactive OAuth refresh on startup")
    if not tok_pre.refresh_token:
        raise RuntimeError("no refresh_token in broker session")
    try:
        await adapter.refresh_token(tok_pre)
        print("[RUNNER] Token refreshed automatically")
    except asyncio.TimeoutError:
        print("[RUNNER] Refresh timeout — using existing token")


async def _run_cli(ns: argparse.Namespace) -> int:
    settings = get_settings()
    if ns.trading_mode == "paper" and not settings.paper_trading_mode:
        raise SystemExit("PAPER_TRADING_MODE must be True when running --mode paper")

    # Ensure DB tables exist for execution logging.
    init_db()
    print(f"[RUNNER] DB initialised")
    print(f"[RUNNER] Tenant: {ns.tenant_id}")
    print(f"[RUNNER] Strategy: {ns.strategy_id}")
    print(f"[RUNNER] Mode: {ns.trading_mode}")
    factory = get_session_factory()
    with factory.begin() as s:
        if s.get(Tenant, ns.tenant_id) is None:
            s.add(Tenant(tenant_id=ns.tenant_id, display_name=ns.tenant_id, status="active"))

    signal_fn = _ensure_strategy_ready(ns.strategy_id, ns.tenant_id, ns.trading_mode)
    print(f"[RUNNER] Strategy loaded OK")

    # Build broker adapter with DB-backed token store so market data streams can authenticate.
    # TradeStation adapter: paper mode requires sim order URLs; market data may use the live API.
    factory = get_session_factory()
    session = factory()
    store = BrokerCredentialsStore(session)
    audit = InMemoryAuditLogger()

    key = settings.broker_impl.strip().lower()
    adapter = create_adapter(
        key,
        store=store,
        audit=audit,
        auth_base_url=settings.broker_auth_base_url,
        api_base_url=settings.broker_api_base_url,
        market_data_base_url=settings.market_data_base_url,
        ws_base_url=settings.broker_ws_base_url,
        client_id=settings.ts_client_id or settings.broker_client_id,
        client_secret=settings.ts_client_secret or settings.broker_client_secret,
        redirect_uri=settings.ts_redirect_uri or settings.broker_redirect_uri,
        trading_mode=ns.trading_mode,
        # Use the equity account id for market data token lookups by default.
        account_id=settings.ts_equity_account_id or settings.ts_account_id or ns.account_id,
        paper_trading_mode=settings.paper_trading_mode,
    )

    # OAuth rows are stored with account_id_default "" (see scripts/auth_tradestation.py).
    oauth_key = ""
    existing: AuthToken | None = None
    try:
        existing = store.get_auth_token(
            tenant_id=ns.tenant_id,
            trading_mode=ns.trading_mode,
            broker_name=key,
            account_id=oauth_key,
        )
    except BrokerAuthError:
        pass
    if existing is None:
        access = (os.environ.get("BROKER_ACCESS_TOKEN") or "").strip()
        refresh = (os.environ.get("BROKER_REFRESH_TOKEN") or "").strip() or None
        exp_s = (os.environ.get("BROKER_EXPIRES_IN_S") or "").strip()
        expires_at = None
        if exp_s:
            try:
                expires_at = datetime.now(UTC) + timedelta(seconds=float(exp_s))
            except Exception:
                expires_at = None
        if access:
            store.upsert_tokens(
                tenant_id=ns.tenant_id,
                trading_mode=ns.trading_mode,
                broker_name=key,
                account_id=oauth_key,
                token=AuthToken(
                    tenant_id=ns.tenant_id,
                    access_token=access,
                    refresh_token=refresh,
                    expires_at=expires_at,
                ),
            )
            print("[RUNNER] Broker session seeded from environment variables")

    # Proactive token refresh before pipeline.run() so the first stream request has a valid access token.
    tok_pre = store.get_auth_token(
        tenant_id=ns.tenant_id,
        trading_mode=ns.trading_mode,
        broker_name=key,
        account_id=oauth_key,
    )
    try:
        await _proactive_oauth_refresh(adapter, tok_pre)
    except Exception as e:
        print(f"[RUNNER] Token refresh failed: {e}")
        print("[RUNNER] Run: python scripts/auth_tradestation.py")
        raise SystemExit(1)

    print(f"[RUNNER] Broker connected OK")

    async def _scheduled_oauth_refresh() -> None:
        while True:
            await asyncio.sleep(600.0)
            try:
                t = store.get_auth_token(
                    tenant_id=ns.tenant_id,
                    trading_mode=ns.trading_mode,
                    broker_name=key,
                    account_id=oauth_key,
                )
            except BrokerAuthError:
                continue
            if not t.refresh_token:
                continue
            try:
                await adapter.refresh_token(t)
                print("[RUNNER] Token refreshed automatically (10m schedule)")
            except Exception as e:
                print(f"[RUNNER] Scheduled OAuth refresh failed: {type(e).__name__}")

    refresh_task = asyncio.create_task(_scheduled_oauth_refresh())

    tracker = PositionTracker()
    tracker.set_cash(
        tenant_id=ns.tenant_id,
        trading_mode=ns.trading_mode,
        account_id=ns.account_id,
        strategy_id=ns.strategy_id,
        cash=Decimal("10000"),
    )

    logger = ExecutionLogger(tenant_id=ns.tenant_id, trading_mode=ns.trading_mode)
    router = OrderRouter(
        tenant_id=ns.tenant_id,
        trading_mode=ns.trading_mode,
        adapter=adapter,  # type: ignore[arg-type]
        tracker=tracker,
        logger=logger,
    )

    # Wire market data: single-symbol uses MarketDataPipeline; comma-separated symbols use
    # MultiSymbolScanner (one TradeStation barchart stream per symbol — API does not accept CSV paths).
    symbols = _parse_symbol_list(ns.symbol)
    max_bars = None if ns.max_bars <= 0 else ns.max_bars
    sym_primary = symbols[0]

    if len(symbols) > 1:
        fan_q: asyncio.Queue[str] = asyncio.Queue()
        sub: BarSubscriber = _FanInBarSubscriber(fan_q)  # type: ignore[assignment]

        async def _run_multi_scanner() -> None:
            scanner = MultiSymbolScanner(ns.tenant_id, adapter)
            await scanner.subscribe(symbols, interval=ns.interval)

            async def _fan_in(bar: Bar) -> None:
                await fan_q.put(json.dumps(bar.model_dump(mode="json")))

            handlers = {s: _fan_in for s in scanner.symbols}
            try:
                await scanner.run(handlers, max_bars=max_bars)
            except BrokerError as e:
                print(f"[PIPELINE_ERR] {type(e).__name__}: {e}")
                raise
            except Exception as e:
                print(f"[PIPELINE_ERR] {type(e).__name__}: {e}")
                raise

        pipe_task = asyncio.create_task(_run_multi_scanner())
        print(f"[RUNNER] Multi-symbol streams ({len(symbols)}): {', '.join(symbols)}")
    else:
        bus = _InProcessPubSub()
        pipeline = MarketDataPipeline(
            adapter,
            redis=bus,
            tenant_id=ns.tenant_id,
            symbol=sym_primary,
            interval=ns.interval,
            trading_mode=ns.trading_mode,
            store=None,
        )

        async def _run_pipeline() -> None:
            try:
                await pipeline.run(max_bars=max_bars)
            except BrokerError as e:
                print(f"[PIPELINE_ERR] {type(e).__name__}: {e}")
                raise
            except Exception as e:
                print(f"[PIPELINE_ERR] {type(e).__name__}: {e}")
                raise

        pipe_task = asyncio.create_task(_run_pipeline())
        sub = bus  # type: ignore[assignment]

    print(f"[RUNNER] Subscribed to market data")
    runner = StrategyRunner(
        tenant_id=ns.tenant_id,
        trading_mode=ns.trading_mode,
        strategy_id=ns.strategy_id,
        symbol=sym_primary,
        interval=ns.interval,
        subscriber=sub,
        router=router,
        signal_fn=signal_fn,
    )
    runner_task = asyncio.create_task(runner.run(max_bars=max_bars))
    try:
        done, pending = await asyncio.wait({runner_task, pipe_task}, return_when=asyncio.FIRST_EXCEPTION)
        for t in done:
            exc = t.exception()
            if exc is not None:
                for p in pending:
                    p.cancel()
                raise exc
        if max_bars is not None:
            await asyncio.gather(runner_task, pipe_task)
    finally:
        refresh_task.cancel()
    return 0


def main(argv: list[str] | None = None) -> int:
    ns = _parse_args(argv)
    return asyncio.run(_run_cli(ns))


if __name__ == "__main__":
    raise SystemExit(main())



