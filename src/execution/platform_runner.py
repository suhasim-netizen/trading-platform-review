# PAPER TRADING MODE

"""Unified platform runner: one process, one event loop, one broker adapter, all strategies concurrent."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import os
import sys
import traceback
from dataclasses import dataclass
from datetime import UTC, datetime, time as time_of_day, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

# Match pytest.ini ``pythonpath = src``
_SRC_ROOT = Path(__file__).resolve().parent.parent
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

import brokers  # noqa: F401 — broker adapter registration
from brokers.models import AuthToken, Bar, InstrumentType, Order, OrderSide, OrderType, TimeInForce
from brokers.registry import create_adapter
from config import get_settings
from db.models import Strategy as DbStrategy
from db.models import Tenant
from db.session import get_session_factory, init_db
from services.audit_log import InMemoryAuditLogger
from services.broker_credentials_store import BrokerCredentialsStore
from services.paper_accounts_seed import seed_paper_accounts
from sqlalchemy import select

from brokers.exceptions import BrokerAuthError, BrokerError, BrokerNetworkError

from execution.account_router import AccountRouter
from execution.intraday_manager import IntradayPositionManager
from execution.logger import ExecutionLogger
from execution.order_tracker import OrderTracker
from execution.router import OrderRouter
from execution.runner import (
    _bar_to_dict,
    _dict_to_signals,
    _normalize_code_ref,
    _proactive_oauth_refresh,
    _strategy_meta_from_row,
)
from execution.tracker import PositionTracker
from strategies.registry import StrategyAccessDenied, StrategyNotFound, load_strategy_for_tenant, register

PLATFORM_STRATEGY_IDS: tuple[str, ...] = ("strategy_004", "strategy_007")

# Paused in DB / docs — not loaded by ``_load_strategies`` (see startup banner).
PLATFORM_PAUSED_STRATEGY_IDS: tuple[str, ...] = ("strategy_002", "strategy_006")

_NY = ZoneInfo("America/New_York")


def _broker_symbol_matches_handler_symbol_list(broker_sym: str, handler_symbols: list[Any]) -> bool:
    """Match broker position symbol (e.g. ``MESM26``, ``AVGO``) to strategy universe (``@MES``, ``AVGO``)."""
    b = broker_sym.strip().upper()
    roots = sorted(
        (str(x).strip().upper().lstrip("@") for x in handler_symbols),
        key=len,
        reverse=True,
    )
    for su in roots:
        if b == su or b.startswith(su):
            return True
    return False


def _dedupe_account_ids(*ids: str | None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in ids:
        if not x or not str(x).strip():
            continue
        s = str(x).strip()
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _is_outside_equity_stream_window_et(now: datetime) -> bool:
    """True when not in Mon–Fri 9:25am–4:05pm America/New_York (weekends count as outside)."""
    z = now.astimezone(_NY)
    if z.weekday() >= 5:
        return True
    t = z.time()
    return t < time_of_day(9, 25) or t > time_of_day(16, 5)


def _seconds_until_next_monfri_925_et(now: datetime) -> float:
    """Seconds until the next Mon–Fri 9:25am ET strictly after *now*."""
    z = now.astimezone(_NY)
    open_t = time_of_day(9, 25)
    for offset in range(0, 10):
        day = (z + timedelta(days=offset)).date()
        if day.weekday() >= 5:
            continue
        cand = datetime.combine(day, open_t, tzinfo=_NY)
        if cand > z:
            return (cand - z).total_seconds()
    return 300.0


_DAILY_POLL_ET = time_of_day(16, 5)


def _next_scheduled_405_et(now: datetime) -> datetime:
    """When to run the next daily fetch: wait until Mon–Fri 16:05 if before that; otherwise run now (weekday); weekend → next Mon 16:05."""
    z = now.astimezone(_NY)
    d = z.date()
    slot = datetime.combine(d, _DAILY_POLL_ET, tzinfo=_NY)
    if d.weekday() < 5:
        if z < slot:
            return slot
        return z
    day = d + timedelta(days=1)
    for _ in range(15):
        if day.weekday() < 5:
            return datetime.combine(day, _DAILY_POLL_ET, tzinfo=_NY)
        day += timedelta(days=1)
    raise RuntimeError("no upcoming weekday for daily bar poll")


def _next_trading_day_405_after(dt: datetime) -> datetime:
    """Earliest Mon–Fri 16:05 ET strictly after ``dt`` (sleep target after a daily fetch)."""
    z = dt.astimezone(_NY)
    d = z.date()
    cand = datetime.combine(d, _DAILY_POLL_ET, tzinfo=_NY)
    if d.weekday() < 5 and cand > z:
        return cand
    day = d + timedelta(days=1)
    for _ in range(15):
        if day.weekday() < 5:
            c2 = datetime.combine(day, _DAILY_POLL_ET, tzinfo=_NY)
            if c2 > z:
                return c2
        day += timedelta(days=1)
    raise RuntimeError("no upcoming weekday for daily bar poll")


@dataclass(frozen=True, slots=True)
class LoadedStrategy:
    strategy_id: str
    name: str
    handler: Any
    symbols: list[str]
    interval: str


def _interval_display(interval: str) -> str:
    u = (interval or "").strip().upper()
    if u == "1D":
        return "daily"
    return (interval or "1m").strip().lower()


def _check_symbol_conflicts(strategies: list[LoadedStrategy]) -> None:
    """Raise if two loaded strategies share the same symbol at the same bar interval."""
    seen: dict[tuple[str, str], str] = {}
    for strat in strategies:
        interval = str(strat.interval or "1m").strip()
        interval_key = interval.upper()
        for symbol in strat.symbols:
            sym_u = str(symbol).strip().upper().lstrip("@")
            key = (sym_u, interval_key)
            if key in seen:
                raise ValueError(
                    f"Symbol conflict: {sym_u} ({interval}) used by both "
                    f"{seen[key]} and {strat.strategy_id}"
                )
            seen[key] = strat.strategy_id
    print("[PLATFORM] No symbol conflicts — all instruments unique per interval")


def _log_stream_connections(loaded: list[LoadedStrategy]) -> None:
    stream_specs = [s for s in loaded if (s.interval or "").strip().upper() != "1D"]
    daily_specs = [s for s in loaded if (s.interval or "").strip().upper() == "1D"]
    n_stream = sum(len(s.symbols) for s in stream_specs)
    n_daily = sum(len(s.symbols) for s in daily_specs)
    if n_stream:
        print(f"[PLATFORM] Opening {n_stream} minute stream connection(s):")
        for spec in stream_specs:
            parts = " ".join(f"{sym}({spec.interval})" for sym in spec.symbols)
            print(f"  {spec.strategy_id}: {parts}")
    if n_daily:
        print(f"[PLATFORM] Scheduling {n_daily} daily REST barchart poll(s) (Mon–Fri 4:05pm ET):")
        for spec in daily_specs:
            parts = " ".join(f"{sym}({spec.interval})" for sym in spec.symbols)
            print(f"  {spec.strategy_id}: {parts}")
    if not n_stream and not n_daily:
        print("[PLATFORM] No market data tasks (empty symbol lists).")


class TradingPlatform:
    """Runs all active platform strategies concurrently in one process (one broker adapter, one event loop)."""

    def __init__(self, tenant_id: str, trading_mode: str) -> None:
        self.tenant_id = tenant_id.strip()
        self.trading_mode = trading_mode.strip()
        self.adapter: Any = None
        self._store: BrokerCredentialsStore | None = None
        self._broker_key: str = ""
        self._oauth_key: str = ""
        self._credential_session: Any = None
        self._router: OrderRouter | None = None
        self._tracker: PositionTracker | None = None
        self._exec_logger: ExecutionLogger | None = None
        self.order_tracker: OrderTracker | None = None
        self._refresh_task: asyncio.Task[None] | None = None
        self._strategies: list[LoadedStrategy] = []

    def _load_strategies(self) -> list[LoadedStrategy]:
        factory = get_session_factory()
        stmt = (
            select(DbStrategy)
            .where(
                DbStrategy.owner_tenant_id == self.tenant_id,
                DbStrategy.id.in_(PLATFORM_STRATEGY_IDS),
            )
            .order_by(DbStrategy.id)
        )
        out: list[LoadedStrategy] = []
        with factory() as session:
            rows = list(session.execute(stmt).scalars().all())
        for row in rows:
            code_ref = (row.code_ref or "").strip()
            if not code_ref:
                print(f"[PLATFORM] Skip {row.id}: empty code_ref")
                continue
            mod_name = _normalize_code_ref(code_ref)
            try:
                mod = importlib.import_module(mod_name)
            except ModuleNotFoundError:
                print(f"[PLATFORM] Skip {row.id}: module not found {mod_name}")
                continue
            cls = getattr(mod, "HANDLER_CLASS", None)
            if cls is None:
                print(f"[PLATFORM] Skip {row.id}: no HANDLER_CLASS")
                continue
            try:
                load_strategy_for_tenant(strategy_id=row.id, requester_tenant_id=self.tenant_id)
            except StrategyNotFound:
                register(_strategy_meta_from_row(row))
            except StrategyAccessDenied:
                print(f"[PLATFORM] Skip {row.id}: access denied")
                continue
            try:
                load_strategy_for_tenant(strategy_id=row.id, requester_tenant_id=self.tenant_id)
            except (StrategyNotFound, StrategyAccessDenied):
                print(f"[PLATFORM] Skip {row.id}: registry load failed")
                continue

            handler = cls()
            set_ctx = getattr(handler, "set_broker_context", None)
            if callable(set_ctx) and self.adapter is not None:
                set_ctx(self.adapter, self.tenant_id)
            symbols = list(getattr(handler, "symbols", []) or [])
            interval = str(getattr(handler, "interval", "1m") or "1m")
            out.append(
                LoadedStrategy(
                    strategy_id=row.id,
                    name=row.name,
                    handler=handler,
                    symbols=symbols,
                    interval=interval,
                )
            )
        return out

    def _print_platform_strategy_status(self) -> None:
        """Log active (loaded) vs paused platform strategies."""
        loaded = self._strategies
        print(f"[PLATFORM] Active strategies: {len(loaded)}")
        for spec in loaded:
            syms = " ".join(str(s).strip().upper() for s in spec.symbols)
            iv = _interval_display(spec.interval)
            print(f"  {spec.strategy_id}: {syms} ({iv})")
        paused = list(PLATFORM_PAUSED_STRATEGY_IDS)
        factory = get_session_factory()
        with factory() as session:
            rows = list(
                session.execute(
                    select(DbStrategy.id, DbStrategy.status).where(
                        DbStrategy.owner_tenant_id == self.tenant_id,
                        DbStrategy.id.in_(paused),
                    ).order_by(DbStrategy.id)
                ).all()
            )
        status_by_id = {r.id: r.status for r in rows}
        print(f"[PLATFORM] Paused strategies: {len(paused)}")
        for pid in paused:
            st = status_by_id.get(pid, "paused")
            print(f"  {pid}: {st}")

    def _initial_cash_account_for_strategy(self, spec: LoadedStrategy) -> str:
        """Broker account id used for risk / fills (must match AccountRouter + order stream)."""
        sym0 = str(spec.symbols[0]).strip().upper() if spec.symbols else ""
        inst = InstrumentType.FUTURES if sym0.startswith("@") else InstrumentType.EQUITY
        o = Order(
            symbol=spec.symbols[0] if spec.symbols else "SPY",
            instrument_type=inst,
            side=OrderSide.BUY,
            quantity=Decimal("1"),
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            strategy_id=spec.strategy_id,
        )
        return AccountRouter().resolve(o, tenant_id=self.tenant_id)

    async def _eod_flatten_task(self) -> None:
        """Safety net — flatten intraday-tagged symbols via broker at 15:50 ET Mon–Fri."""
        ET = ZoneInfo("America/New_York")
        while True:
            try:
                now = datetime.now(ET)
                target = now.replace(hour=15, minute=50, second=0, microsecond=0)
                if now >= target:
                    target = target + timedelta(days=1)
                while target.weekday() >= 5:
                    target = target + timedelta(days=1)
                wait_seconds = max(0.0, (target - now).total_seconds())
                print(f"[EOD_FLATTEN] Next safety flatten: {target.strftime('%Y-%m-%d %H:%M ET')}")
                await asyncio.sleep(wait_seconds)
                print("[EOD_FLATTEN] Safety flatten triggered @ 15:50 ET")
                print("[EOD_FLATTEN] Running safety flatten for all intraday strategies")
                if self.adapter is None:
                    continue
                settings = get_settings()
                acct = (settings.ts_equity_account_id or "").strip() or (settings.ts_account_id or "").strip()
                if not acct:
                    print("[EOD_FLATTEN] No equity account id configured — skip")
                    continue
                manager = IntradayPositionManager(self.trading_mode, account_id=acct)
                await manager.enforce_eod_close(
                    self.tenant_id,
                    self.adapter,
                    close_time="15:50",
                    account_id=acct,
                )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"[EOD_FLATTEN] Error: {e}")

    async def _refresh_loop(self) -> None:
        assert self.adapter is not None and self._store is not None
        while True:
            await asyncio.sleep(600.0)
            try:
                t = self._store.get_auth_token(
                    tenant_id=self.tenant_id,
                    trading_mode=self.trading_mode,
                    broker_name=self._broker_key,
                    account_id=self._oauth_key,
                )
            except BrokerAuthError:
                continue
            if not t.refresh_token:
                continue
            try:
                await self.adapter.refresh_token(t)
                print("[PLATFORM] Token auto-refreshed")
            except Exception as e:
                print(f"[PLATFORM] Refresh error: {e}")

    async def _handle_bar(self, spec: LoadedStrategy, bar: Bar) -> None:
        assert self._router is not None
        bar_d = _bar_to_dict(bar)
        pre = getattr(spec.handler, "prefetch_session_data_async", None)
        if pre is not None:
            await pre(bar_d)
        raw = spec.handler.on_bar(bar.symbol, bar_d)
        for sig in _dict_to_signals(
            raw,
            tenant_id=self.tenant_id,
            trading_mode=self.trading_mode,
            strategy_id=spec.strategy_id,
        ):
            try:
                await self._router.route(sig)
            except BrokerError as e:
                print(f"[ORDER_ERR] Order failed: {e} — stream continues")
        post_bar = getattr(spec.handler, "post_bar_async", None)
        if post_bar is not None:
            await post_bar(bar.symbol, bar_d)

    async def _stream_symbol(self, spec: LoadedStrategy, symbol: str) -> None:
        assert self.adapter is not None
        md_base = getattr(self.adapter, "market_data_url", None) or getattr(
            self.adapter, "_market_data_url", ""
        )
        od_base = getattr(self.adapter, "order_api_url", None) or getattr(
            self.adapter, "_order_api_url", ""
        )
        print(
            f"[STREAM] task start symbol={symbol!r} strategy={spec.strategy_id} "
            f"interval={spec.interval!r} tenant_id={self.tenant_id!r} "
            f"market_data_base={md_base} order_api_base={od_base}"
        )
        n_bar = 0
        n_tenant_skip = 0
        reconnect = 0
        while True:
            try:
                reconnect += 1
                print(
                    f"[STREAM] opening stream_bars attempt={reconnect} symbol={symbol!r} "
                    f"interval={spec.interval!r} (watch for [TS_STREAM] and [BAR] lines)"
                )
                stream = self.adapter.stream_bars(symbol, spec.interval, self.tenant_id)
                bars_this_connection = 0
                async for bar in stream:
                    if bar.tenant_id != self.tenant_id:
                        n_tenant_skip += 1
                        if n_tenant_skip <= 3:
                            print(
                                f"[STREAM] {symbol} tenant mismatch: "
                                f"expected={self.tenant_id!r} bar.tenant_id={bar.tenant_id!r}"
                            )
                        continue
                    n_bar += 1
                    bars_this_connection += 1
                    if n_bar <= 10 or n_bar % 50 == 0:
                        print(
                            f"[BAR] {spec.strategy_id} {symbol} n={n_bar} "
                            f"close={bar.close} start={bar.bar_start.isoformat()}"
                        )
                    await self._handle_bar(spec, bar)
                last_err = getattr(self.adapter, "_last_barchart_stream_error", None) or ""
                print(
                    f"[STREAM] {symbol} stream iterator finished (HTTP connection closed); "
                    f"bars_total={n_bar} bars_this_connection={bars_this_connection} "
                    f"tenant_skips={n_tenant_skip} last_stream_error={last_err!r}"
                )
                if bars_this_connection == 0 and "InvalidSymbol" in last_err:
                    print(f"[STREAM] {symbol} — InvalidSymbol, waiting 60s before retry")
                    await asyncio.sleep(60.0)
                elif (
                    not symbol.strip().startswith("@")
                    and "no data available" in last_err.lower()
                ):
                    now_et = datetime.now(_NY)
                    if _is_outside_equity_stream_window_et(now_et):
                        print(f"[STREAM] {symbol} market closed — sleeping until 9:25am ET")
                        await asyncio.sleep(max(_seconds_until_next_monfri_925_et(now_et), 1.0))
                    else:
                        await asyncio.sleep(5.0)
                else:
                    await asyncio.sleep(5.0)
            except asyncio.CancelledError:
                raise
            except BrokerNetworkError:
                print(f"[STREAM] {symbol} connection reset — reconnecting in 5s")
                await asyncio.sleep(5.0)
            except Exception as e:
                print(f"[STREAM] {symbol} unexpected: {e}")
                traceback.print_exc()
                last_err = getattr(self.adapter, "_last_barchart_stream_error", None) or ""
                if "InvalidSymbol" in last_err:
                    print(f"[STREAM] {symbol} — InvalidSymbol after error, waiting 60s before retry")
                    await asyncio.sleep(60.0)
                elif (
                    not symbol.strip().startswith("@")
                    and "no data available" in last_err.lower()
                ):
                    now_et = datetime.now(_NY)
                    if _is_outside_equity_stream_window_et(now_et):
                        print(f"[STREAM] {symbol} market closed — sleeping until 9:25am ET")
                        await asyncio.sleep(max(_seconds_until_next_monfri_925_et(now_et), 1.0))
                    else:
                        await asyncio.sleep(5.0)
                else:
                    await asyncio.sleep(5.0)

    async def _poll_daily_bar(self, spec: LoadedStrategy, symbol: str) -> None:
        """Daily strategies: REST barcharts once per session at 4:05pm ET (no minute streaming)."""
        assert self.adapter is not None
        fetch = getattr(self.adapter, "fetch_latest_daily_bar", None)
        if fetch is None:
            print(f"[DAILY] {symbol} — adapter has no fetch_latest_daily_bar; skipping")
            return
        while True:
            try:
                now = datetime.now(_NY)
                target = _next_scheduled_405_et(now)
                wait_secs = (target - now).total_seconds()
                if wait_secs > 0:
                    print(
                        f"[DAILY] {symbol} — waiting {wait_secs / 3600.0:.1f}h until 4:05pm ET "
                        f"({target.strftime('%Y-%m-%d')})"
                    )
                    await asyncio.sleep(wait_secs)

                bar = await fetch(symbol, self.tenant_id)
                if bar is None:
                    print(f"[DAILY] {symbol} — no bar returned — retry in 60s")
                    await asyncio.sleep(60.0)
                    continue

                print(f"[DAILY] {symbol} close={bar.close}")
                if bar.tenant_id != self.tenant_id:
                    continue
                await self._handle_bar(spec, bar)

                nafter = _next_trading_day_405_after(datetime.now(_NY))
                sleep_s = (nafter - datetime.now(_NY)).total_seconds()
                if sleep_s > 0:
                    await asyncio.sleep(sleep_s)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"[DAILY] {symbol} error: {e} — retrying in 60s")
                await asyncio.sleep(60.0)

    async def _run_strategy(self, spec: LoadedStrategy) -> None:
        if not spec.symbols:
            return
        interval_u = (spec.interval or "").strip().upper()
        if interval_u == "1D":
            syms = " ".join(spec.symbols)
            print(f"[DAILY] Polling: {syms} ({spec.strategy_id}) — 4:05pm ET")
            sub_tasks = [asyncio.create_task(self._poll_daily_bar(spec, sym)) for sym in spec.symbols]
            await asyncio.gather(*sub_tasks, return_exceptions=True)
            return

        syms = " ".join(spec.symbols)
        print(f"[STREAM] Subscribing: {syms} ({spec.strategy_id})")
        sub_tasks = [asyncio.create_task(self._stream_symbol(spec, sym)) for sym in spec.symbols]
        await asyncio.gather(*sub_tasks, return_exceptions=True)

    async def _strategy_supervisor(self, spec: LoadedStrategy) -> None:
        while True:
            try:
                await self._run_strategy(spec)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"[PLATFORM] Strategy {spec.strategy_id} error: {e} — restarting in 5s")
                await asyncio.sleep(5.0)

    async def _setup_broker_and_auth(self) -> None:
        """One broker adapter, one proactive OAuth pass — shared by all strategies."""
        settings = get_settings()
        if self.trading_mode == "paper" and not settings.paper_trading_mode:
            raise SystemExit("PAPER_TRADING_MODE must be True when running --mode paper")

        init_db()
        print("[PLATFORM] DB initialised")

        factory = get_session_factory()
        with factory.begin() as s:
            if s.get(Tenant, self.tenant_id) is None:
                s.add(Tenant(tenant_id=self.tenant_id, display_name=self.tenant_id, status="active"))

        self._credential_session = factory()
        self._store = BrokerCredentialsStore(self._credential_session)
        audit = InMemoryAuditLogger()
        self._broker_key = settings.broker_impl.strip().lower()

        adapter = create_adapter(
            self._broker_key,
            store=self._store,
            audit=audit,
            auth_base_url=settings.broker_auth_base_url,
            api_base_url=settings.broker_api_base_url,
            market_data_base_url=settings.market_data_base_url,
            ws_base_url=settings.broker_ws_base_url,
            client_id=settings.ts_client_id or settings.broker_client_id,
            client_secret=settings.ts_client_secret or settings.broker_client_secret,
            redirect_uri=settings.ts_redirect_uri or settings.broker_redirect_uri,
            trading_mode=self.trading_mode,
            account_id=settings.ts_equity_account_id or settings.ts_account_id or "A1",
            paper_trading_mode=settings.paper_trading_mode,
        )
        self.adapter = adapter

        existing: AuthToken | None = None
        try:
            existing = self._store.get_auth_token(
                tenant_id=self.tenant_id,
                trading_mode=self.trading_mode,
                broker_name=self._broker_key,
                account_id=self._oauth_key,
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
            if access and self._store is not None:
                self._store.upsert_tokens(
                    tenant_id=self.tenant_id,
                    trading_mode=self.trading_mode,
                    broker_name=self._broker_key,
                    account_id=self._oauth_key,
                    token=AuthToken(
                        tenant_id=self.tenant_id,
                        access_token=access,
                        refresh_token=refresh,
                        expires_at=expires_at,
                    ),
                )
                print("[PLATFORM] Broker session seeded from environment variables")

        print("[PLATFORM] Authenticating...")
        assert self._store is not None
        tok_pre = self._store.get_auth_token(
            tenant_id=self.tenant_id,
            trading_mode=self.trading_mode,
            broker_name=self._broker_key,
            account_id=self._oauth_key,
        )
        try:
            await _proactive_oauth_refresh(adapter, tok_pre)
        except Exception as e:
            print(f"[PLATFORM] Auth failed: {e}")
            print("[PLATFORM] Run: python scripts/auth_tradestation.py")
            raise SystemExit(1) from e
        print("[PLATFORM] Auth complete")

        self._tracker = PositionTracker()
        self._exec_logger = ExecutionLogger(tenant_id=self.tenant_id, trading_mode=self.trading_mode)
        self._router = OrderRouter(
            tenant_id=self.tenant_id,
            trading_mode=self.trading_mode,
            adapter=adapter,  # type: ignore[arg-type]
            tracker=self._tracker,
            logger=self._exec_logger,
        )
        self.order_tracker = OrderTracker(
            tenant_id=self.tenant_id,
            trading_mode=self.trading_mode,
            tracker=self._tracker,
            logger=self._exec_logger,
        )

    async def _seed_accounts(self) -> None:
        await asyncio.to_thread(seed_paper_accounts, self.tenant_id, self.trading_mode)

    async def _reconstruct_positions_from_snapshot(self) -> None:
        """Restore open-position awareness from broker positions API before any strategy work starts."""
        settings = get_settings()
        if self.adapter is None:
            return
        equity_acct = (settings.ts_equity_account_id or "").strip()
        futures_acct = (settings.ts_futures_account_id or "").strip()
        broker_accts = [a for a in (equity_acct, futures_acct) if a]

        print("[PLATFORM] Reconstructing open positions from TradeStation...")
        if not broker_accts:
            print("[PLATFORM] No broker account ids configured for reconstruction")
            return

        positions_found = 0
        for broker_acct in broker_accts:
            try:
                # BrokerAdapter contract: get_positions(account_id, tenant_id)
                positions = await self.adapter.get_positions(broker_acct, self.tenant_id)
                positions = positions or []
                print(f"[PLATFORM] {broker_acct}: {len(positions)} position(s)")
                for pos in positions:
                    positions_found += 1
                    try:
                        symbol = (pos.symbol or "").strip().lstrip("@").upper()
                        qty = pos.quantity
                        avg_cost = getattr(pos, "avg_cost", None)
                    except Exception:
                        continue
                    print(f"[STARTUP] {symbol} qty={qty} avg={avg_cost}")

                    if not symbol or qty is None or qty == 0:
                        continue
                    if not self._strategies:
                        continue

                    side = "short" if qty < 0 else "long"
                    for strategy in self._strategies:
                        h = getattr(strategy, "handler", None)
                        if h is None or not hasattr(h, "update_position"):
                            continue
                        syms = getattr(h, "symbols", []) or []
                        if not _broker_symbol_matches_handler_symbol_list(symbol, syms):
                            continue
                        try:
                            h.update_position(symbol, side)
                            print(
                                f"[STARTUP] Restored position: {symbol} "
                                f"{'SHORT' if qty < 0 else 'LONG'} qty={abs(qty)} avg={avg_cost}"
                            )
                        except Exception:
                            continue
            except Exception as e:
                print(f"[PLATFORM] get_positions failed for {broker_acct}: {e}")

        if positions_found == 0:
            print("[PLATFORM] No open positions — starting fresh")

    async def start(self) -> None:
        await self._seed_accounts()
        await self._setup_broker_and_auth()

        self._strategies = self._load_strategies()
        if not self._strategies:
            print("[PLATFORM] No strategies loaded (check strategies table and code_ref).")
            raise SystemExit(1)

        _check_symbol_conflicts(self._strategies)
        self._print_platform_strategy_status()

        await self._reconstruct_positions_from_snapshot()
        _log_stream_connections(self._strategies)

        for spec in self._strategies:
            acct = self._initial_cash_account_for_strategy(spec)
            self._tracker.set_cash(
                tenant_id=self.tenant_id,
                trading_mode=self.trading_mode,
                account_id=acct,
                strategy_id=spec.strategy_id,
                cash=Decimal("10000"),
            )

        self._refresh_task = asyncio.create_task(self._refresh_loop())

        print(f"[PLATFORM] Running {len(self._strategies)} strategies concurrently")
        strategy_tasks = [asyncio.create_task(self._strategy_supervisor(s)) for s in self._strategies]
        gather_list: list[asyncio.Task[Any]] = list(strategy_tasks)
        gather_list.append(asyncio.create_task(self._eod_flatten_task()))
        if self.order_tracker is not None:
            settings = get_settings()
            stream_accounts = _dedupe_account_ids(
                settings.ts_equity_account_id,
                settings.ts_options_account_id,
                settings.ts_futures_account_id,
                settings.ts_account_id,
            )
            gather_list.append(
                asyncio.create_task(
                    self.order_tracker.start(
                        tenant_id=self.tenant_id,
                        account_ids=stream_accounts,
                        adapter=self.adapter,
                    )
                )
            )
        await asyncio.gather(*gather_list, return_exceptions=True)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m src.execution.platform_runner")
    p.add_argument("--tenant", required=True, dest="tenant_id")
    p.add_argument("--mode", required=True, choices=["paper", "live"], dest="trading_mode")
    return p.parse_args(argv)


async def _async_main(ns: argparse.Namespace) -> int:
    tp = TradingPlatform(ns.tenant_id, ns.trading_mode)
    await tp.start()
    return 0


def main(argv: list[str] | None = None) -> int:
    ns = _parse_args(argv)
    return asyncio.run(_async_main(ns))


if __name__ == "__main__":
    raise SystemExit(main())
