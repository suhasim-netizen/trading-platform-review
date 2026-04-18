# PAPER TRADING MODE

"""TradeStation order update stream → execution_orders / execution_fills / DB positions + PositionTracker."""

from __future__ import annotations

import asyncio
import json
import os
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import select
from brokers.base import BrokerAdapter
from brokers.models import InstrumentType, Order, OrderSide, OrderStatus, OrderUpdate, OrderType, TimeInForce
from brokers.tradestation.adapter import FUTURES_FRONT_MONTH
from config import get_settings
from db.models import Account as DbAccount
from db.models import ExecutionFill
from db.models import ExecutionOrder as DbExecutionOrder
from db.models import Position as DbPosition
from db.session import get_session_factory

from .logger import ExecutionLogger
from .tracker import PositionTracker


def _dec(v: object) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except Exception:
        return None


def _str(v: object | None) -> str | None:
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        return s if s else None
    return str(v)


END_OF_SNAPSHOT_ORDER_ID = "_stream_end_of_snapshot_"


def _is_filled_event(update: dict[str, Any]) -> bool:
    """Detect a fill when Status is missing but Legs / FilledPrice / StatusDescription say filled."""
    status = str(update.get("Status", "") or "").strip()
    status_desc = str(update.get("StatusDescription", "") or "").strip()
    legs_raw = update.get("Legs") or []
    legs = legs_raw if isinstance(legs_raw, list) else []
    leg: dict[str, Any] = legs[0] if legs and isinstance(legs[0], dict) else {}
    fp = update.get("FilledPrice")
    has_fill_price = _dec(fp) is not None and _dec(fp) != Decimal("0")
    eq = leg.get("ExecQuantity") if isinstance(leg, dict) else None
    has_exec_qty = _dec(eq) is not None and _dec(eq) != Decimal("0")
    sd_ok = status_desc.lower() == "filled"
    st_ok = status.upper() in ("FLL", "FILLED", "FLD")
    return st_ok or sd_ok or (has_fill_price and has_exec_qty)


def _extract_fill_fields(update: dict[str, Any]) -> dict[str, Any]:
    """Normalize TradeStation order stream payloads (including multi-leg) into fill scalars."""
    legs_raw = update.get("Legs") or []
    legs = legs_raw if isinstance(legs_raw, list) else []
    leg: dict[str, Any] = legs[0] if legs and isinstance(legs[0], dict) else {}

    fill_price = _dec(update.get("FilledPrice") or leg.get("ExecutionPrice")) or Decimal("0")
    q_raw = leg.get("ExecQuantity") or leg.get("QuantityOrdered") or update.get("FilledQuantity")
    fill_qty = _dec(q_raw) or Decimal("0")

    bos = str(leg.get("BuyOrSell", "") or "").strip().lower()
    if bos in ("b", "buy"):
        side = "buy"
    elif bos in ("s", "sell"):
        side = "sell"
    else:
        side = ""

    sym = _str(leg.get("Underlying") or leg.get("Symbol")) or "?"
    order_id = str(update.get("OrderID") or update.get("OrderId") or "").strip() or None
    account_id = str(update.get("AccountID") or update.get("AccountId") or "").strip()
    commission = _dec(update.get("CommissionFee")) or Decimal("0")

    valid = fill_price > 0 and fill_qty > 0
    return {
        "fill_price": fill_price,
        "fill_qty": fill_qty,
        "side": side,
        "symbol": sym,
        "order_id": order_id,
        "account_id": account_id,
        "commission": commission,
        "valid": valid,
    }


def _futures_root_from_symbol(sym: str) -> str | None:
    s = sym.strip().upper().lstrip("@")
    if s.startswith("MNQ"):
        return "MNQ"
    if s.startswith("MES"):
        return "MES"
    if s.startswith("NQ"):
        return "NQ"
    if s.startswith("ES"):
        return "ES"
    return None


KNOWN_EQUITY_SYMBOLS = frozenset(
    {"AVGO", "LLY", "TSM", "GEV", "LASR", "LITE", "COHR", "SNDK", "STRL"}
)
KNOWN_FUTURES_SYMBOLS = frozenset({"MES", "MNQ", "ES", "NQ"})


def _is_our_symbol(symbol: str) -> bool:
    """Symbols we actively trade; ignore external / other-app fills (e.g. index options)."""
    s = symbol.upper().strip().lstrip("@").lstrip("$")
    if not s or s == "?":
        return False
    if s in KNOWN_EQUITY_SYMBOLS:
        return True
    if s in KNOWN_FUTURES_SYMBOLS:
        return True
    for root in KNOWN_FUTURES_SYMBOLS:
        if s.startswith(root):
            return True
    return False


def _enrich_fill_from_raw(u: OrderUpdate) -> OrderUpdate:
    """Merge Legs / FilledPrice / StatusDescription into ``OrderUpdate`` when Status omits FLL."""
    r = u.raw or {}
    if not _is_filled_event(r):
        return _coalesce_order_update(u)
    f = _extract_fill_fields(r)
    if not f["valid"]:
        print(f"[WARN] Fill missing data: price={f['fill_price']} qty={f['fill_qty']} order={f['order_id']}")
        return _coalesce_order_update(u)
    side_str = f["side"]
    side: OrderSide | None = None
    if side_str == "buy":
        side = OrderSide.BUY
    elif side_str == "sell":
        side = OrderSide.SELL
    base = _coalesce_order_update(u)
    return base.model_copy(
        update={
            "avg_fill_price": f["fill_price"],
            "filled_quantity": f["fill_qty"],
            "symbol": f["symbol"] if f["symbol"] != "?" else base.symbol,
            "side": side or base.side,
            "account_id": f["account_id"] or base.account_id,
            "status": OrderStatus.FILLED,
            "order_id": f["order_id"] or base.order_id,
        }
    )


def _coalesce_order_update(u: OrderUpdate) -> OrderUpdate:
    """Fill in missing fields from ``raw`` (TradeStation field names vary by event type)."""
    r = u.raw or {}
    pick = lambda *keys: next((r.get(k) for k in keys if r.get(k) not in (None, "")), None)

    oid = u.order_id or str(pick("OrderID", "OrderId", "Id") or "")
    sym = u.symbol or _str(pick("Symbol", "Underlying", "FullSymbol", "LegSymbol"))
    avg = u.avg_fill_price if u.avg_fill_price is not None else _dec(
        pick(
            "AverageFillPrice",
            "FilledPrice",
            "AvgFillPrice",
            "ExecutionPrice",
            "AvgExecPrice",
            "AvgPrice",
            "Price",
            "LastPrice",
        )
    )
    fq = u.filled_quantity if u.filled_quantity is not None else _dec(
        pick("FilledQuantity", "QuantityFilled", "ExecQuantity", "CumulativeFilled", "CumulativeQuantity", "Quantity")
    )
    acct = (u.account_id or _str(pick("AccountID", "AccountId")) or "").strip() or u.account_id

    return u.model_copy(
        update={
            "order_id": oid or u.order_id,
            "symbol": sym,
            "avg_fill_price": avg,
            "filled_quantity": fq,
            "account_id": acct,
        }
    )


def _classify_update(u: OrderUpdate) -> tuple[bool, bool, bool, bool]:
    r = u.raw or {}
    evt = _str(r.get("Event")) or ""
    evt_l = evt.lower()
    ek = (u.event_kind or "").upper()
    st = u.status
    is_fill = (
        st in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED)
        or "FILL" in ek
        or "fill" in evt_l
        or _is_filled_event(r)
    )
    is_reject = st == OrderStatus.REJECTED or "reject" in evt_l or "REJECT" in ek
    is_cancel = st == OrderStatus.CANCELLED or "cancel" in evt_l or "CANCEL" in ek
    is_confirm = "confirm" in evt_l or "CONFIRM" in ek
    return is_fill, is_reject, is_cancel, is_confirm


class OrderTracker:
    """
    Listens to TradeStation order update stream.
    Updates execution_orders and execution_fills tables as events arrive.
    Updates PositionTracker on fills; mirrors open quantity to ``positions`` when an ``accounts`` row exists.
    """

    def __init__(
        self,
        *,
        tenant_id: str,
        trading_mode: str,
        tracker: PositionTracker,
        logger: ExecutionLogger,
    ) -> None:
        if not tenant_id or not trading_mode:
            raise ValueError("tenant_id and trading_mode are required")
        self._tenant_id = tenant_id
        self._trading_mode = trading_mode
        self._tracker = tracker
        self._logger = logger
        self._adapter: BrokerAdapter | None = None
        self._bracket_peer: dict[str, str] = {}
        self._bracket_leg_ids: set[str] = set()
        self._cum_filled_qty: dict[tuple[str, str], Decimal] = {}
        self._equity_fill_debug_count = 0

    async def _already_processed(self, tenant_id: str, order_id: str | None) -> bool:
        """True if this order_id already has an execution_fills row (idempotent stream replay)."""
        if not order_id:
            return False
        factory = get_session_factory()
        with factory() as session:
            r = session.execute(
                select(ExecutionFill.id).where(
                    ExecutionFill.tenant_id == tenant_id,
                    ExecutionFill.trading_mode == self._trading_mode,
                    ExecutionFill.order_id == order_id,
                ).limit(1)
            ).scalar_one_or_none()
            return r is not None

    async def _is_our_order(self, tenant_id: str, order_id: str) -> bool:
        factory = get_session_factory()
        with factory() as session:
            row = session.execute(
                select(DbExecutionOrder.id).where(
                    DbExecutionOrder.tenant_id == tenant_id,
                    DbExecutionOrder.trading_mode == self._trading_mode,
                    DbExecutionOrder.order_id == order_id,
                ).limit(1)
            ).scalar_one_or_none()
            return row is not None

    async def start(self, tenant_id: str, account_ids: list[str], adapter: BrokerAdapter) -> None:
        """Opens order stream for each account. Processes events and updates DB / tracker."""
        if tenant_id != self._tenant_id:
            raise ValueError("tenant_id mismatch on OrderTracker.start")
        self._adapter = adapter
        ids = [a.strip() for a in account_ids if a and a.strip()]
        if not ids:
            print("[ORDER_STREAM] no account ids configured; order tracker idle")
            return
        tasks = [asyncio.create_task(self._stream_account_orders(tenant_id, acct_id, adapter)) for acct_id in ids]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _stream_account_orders(self, tenant_id: str, account_id: str, adapter: BrokerAdapter) -> None:
        """Stream order updates for one account (snapshot replay vs live)."""
        while True:
            try:
                SNAPSHOT_TIMEOUT = 3.0  # inactivity threshold; must NOT close the stream
                snapshot_phase = True
                last_event_t = asyncio.get_running_loop().time()

                async def _inactivity_watcher() -> None:
                    nonlocal snapshot_phase, last_event_t
                    while snapshot_phase:
                        await asyncio.sleep(0.25)
                        now = asyncio.get_running_loop().time()
                        if now - last_event_t > SNAPSHOT_TIMEOUT:
                            snapshot_phase = False
                            print(f"[ORDER_STREAM] {account_id} snapshot complete (timeout) — now live")
                            return

                watcher = asyncio.create_task(_inactivity_watcher())

                async for update in adapter.stream_order_updates(account_id, tenant_id):
                    last_event_t = asyncio.get_running_loop().time()

                    if update.stream_marker == "EndOfSnapshot":
                        if snapshot_phase:
                            snapshot_phase = False
                            print(f"[ORDER_STREAM] {account_id} snapshot complete — now live")
                        continue

                    dbg = os.environ.get("ORDER_STREAM_DEBUG", "").strip().lower()
                    if dbg in ("1", "true", "yes", "on"):
                        try:
                            blob = json.dumps(update.raw or {}, default=str)[:500]
                            print(f"[RAW_EVENT] {blob}")
                        except Exception:
                            print(f"[RAW_EVENT] <unserializable>")

                    u = _enrich_fill_from_raw(_coalesce_order_update(update))
                    oid = u.order_id
                    if not oid or oid == END_OF_SNAPSHOT_ORDER_ID:
                        continue

                    is_snap = (
                        snapshot_phase
                        or (u.is_snapshot is True)
                        or ((u.raw or {}).get("IsSnapshot") is True)
                    )
                    is_fill, is_reject, is_cancel, is_confirm = _classify_update(u)

                    if is_snap:
                        if is_fill:
                            f = _extract_fill_fields(u.raw or {})
                            sym = (f.get("symbol") or u.symbol or "?").strip()
                            if not _is_our_symbol(sym):
                                print(f"[IGNORE] Unknown symbol {sym} — snapshot fill skipped")
                                continue
                            px = u.avg_fill_price
                            q = u.filled_quantity
                            print(f"[SNAPSHOT] Historical fill: {oid} (not re-processed for brackets)")
                            if px is not None and q is not None:
                                fill_oid = f.get("order_id") or oid
                                if await self._already_processed(tenant_id, fill_oid):
                                    print(f"[SKIP] Already processed fill {fill_oid} — skipping")
                                    continue
                                await self._record_fill_snapshot(tenant_id, u)
                            else:
                                print(
                                    f"[SNAPSHOT] skipped fill row (missing price/qty); "
                                    f"keys={list((u.raw or {}).keys())[:12]}"
                                )
                        elif is_reject:
                            reason = (
                                u.message
                                or _str((u.raw or {}).get("RejectReason"))
                                or (u.raw or {}).get("Error")
                                or u.raw
                            )
                            print(f"[SNAPSHOT] REJECT {u.symbol or '?'} reason: {reason}")
                            await self._record_rejection(tenant_id, u)
                        else:
                            if is_confirm:
                                print(f"[SNAPSHOT] CONFIRM {u.symbol or '?'} order id={oid}")
                            status_val = "cancelled" if is_cancel else u.status.value
                            self._patch_execution_order(tenant_id, oid, status_val, u.raw)
                        continue

                    await self._handle_live_update(tenant_id, update)
            except asyncio.CancelledError:
                raise
            except StopAsyncIteration:
                await asyncio.sleep(1)
            except Exception as e:
                print(f"[ORDER_STREAM] {account_id} error: {e} — reconnecting in 5s")
                await asyncio.sleep(5)
            finally:
                try:
                    watcher.cancel()  # type: ignore[name-defined]
                except Exception:
                    pass

    async def _handle_live_update(self, tenant_id: str, update: OrderUpdate) -> None:
        """Process one real-time order update (post-snapshot); brackets apply to entry fills."""
        u = _enrich_fill_from_raw(_coalesce_order_update(update))
        oid = (u.order_id or "").strip()

        is_fill, is_reject, is_cancel, is_confirm = _classify_update(u)

        if not is_fill and not oid:
            return

        if is_reject:
            reason = u.message or _str((u.raw or {}).get("RejectReason")) or (u.raw or {}).get("Error") or u.raw
            print(f"[REJECT] {u.symbol or '?'} reason: {reason}")
            await self._record_rejection(tenant_id, u)
            return

        if is_fill:
            r0 = update.raw or {}
            eq_acct = (get_settings().ts_equity_account_id or "").strip()
            if eq_acct and self._equity_fill_debug_count < 3:
                aid = str(r0.get("AccountID") or r0.get("AccountId") or "").strip()
                if aid.upper() == eq_acct.upper():
                    try:
                        print(f"[EQUITY_FILL_DEBUG] {json.dumps(r0, default=str)}")
                    except Exception as ex:
                        print(f"[EQUITY_FILL_DEBUG] json error: {ex} keys={list(r0.keys())[:24]}")
                    self._equity_fill_debug_count += 1
            f = _extract_fill_fields(u.raw or {})
            sym = (f.get("symbol") or u.symbol or "?").strip()
            if not _is_our_symbol(sym):
                print(f"[IGNORE] Unknown symbol {sym} — not from our strategies")
                return
            fill_oid = (f.get("order_id") or oid or "").strip()
            if not fill_oid:
                print("[FILL] skipped (no order_id)")
                return
            if fill_oid != (u.order_id or "").strip():
                u = u.model_copy(update={"order_id": fill_oid})
                oid = fill_oid
            if await self._already_processed(tenant_id, fill_oid):
                print(f"[SKIP] Already processed fill {fill_oid} — skipping")
                return
            await self._on_bracket_peer_fill(tenant_id, oid)
            px = u.avg_fill_price
            q = u.filled_quantity
            print(f"[FILL] {sym} @ {px} qty={q} order={fill_oid}")
            if px is None or q is None:
                print(f"[FILL] skipped persistence (missing price/qty); raw keys={list((u.raw or {}).keys())[:12]}")
                return
            recorded = await self._record_fill(tenant_id, u)
            if not recorded:
                print(f"[SKIP] Duplicate fill (persist) {fill_oid} — skipping tracker/position")
                return
            u_cum = self._tracker_cumulative_update(u, q, px)
            side_s = f["side"] or (
                "buy" if u.side == OrderSide.BUY else ("sell" if u.side == OrderSide.SELL else "")
            )
            await self._update_position(
                tenant_id, u_cum, live=True, leg_qty=q, fill_price=px, side=side_s
            )
            if not await self._is_our_order(tenant_id, fill_oid):
                print(f"[EXTERNAL] Fill {fill_oid} not from this app — skipping brackets")
                return
            await self._place_oco_bracket(tenant_id, f, u)
        else:
            if is_confirm:
                print(f"[CONFIRM] {u.symbol or '?'} order accepted id={oid}")
            status_val = "cancelled" if is_cancel else u.status.value
            self._patch_execution_order(tenant_id, oid, status_val, u.raw)

    def _tracker_cumulative_update(self, u: OrderUpdate, leg_qty: Decimal, px: Decimal) -> OrderUpdate:
        """Monotonic cumulative filled qty for ``PositionTracker.apply_fill`` (per account + order)."""
        acct = (u.account_id or "").strip()
        if not acct or not u.order_id:
            return u.model_copy(update={"filled_quantity": leg_qty, "avg_fill_price": px})
        k = (acct, u.order_id)
        prev = self._cum_filled_qty.get(k, Decimal("0"))
        new_c = prev + leg_qty
        self._cum_filled_qty[k] = new_c
        return u.model_copy(update={"filled_quantity": new_c, "avg_fill_price": px})

    async def _on_bracket_peer_fill(self, tenant_id: str, order_id: str) -> None:
        """OCO-style: when one bracket leg executes, cancel the sibling order."""
        if order_id not in self._bracket_peer:
            return
        peer = self._bracket_peer.pop(order_id, None)
        if peer:
            self._bracket_peer.pop(peer, None)
        self._bracket_leg_ids.discard(order_id)
        self._bracket_leg_ids.discard(peer or "")
        if not peer or self._adapter is None:
            return
        try:
            await self._adapter.cancel_order(peer, tenant_id)
            print(f"[BRACKET] cancelled sibling order {peer} after fill on {order_id}")
        except Exception as e:
            print(f"[BRACKET] could not cancel sibling {peer}: {e}")

    def _lookup_strategy_id(self, order_id: str) -> str | None:
        factory = get_session_factory()
        with factory() as session:
            return session.execute(
                select(DbExecutionOrder.strategy_id).where(
                    DbExecutionOrder.tenant_id == self._tenant_id,
                    DbExecutionOrder.trading_mode == self._trading_mode,
                    DbExecutionOrder.order_id == order_id,
                )
            ).scalar_one_or_none()

    def _lookup_execution_order_row(self, order_id: str) -> DbExecutionOrder | None:
        factory = get_session_factory()
        with factory() as session:
            return session.execute(
                select(DbExecutionOrder).where(
                    DbExecutionOrder.tenant_id == self._tenant_id,
                    DbExecutionOrder.trading_mode == self._trading_mode,
                    DbExecutionOrder.order_id == order_id,
                )
            ).scalar_one_or_none()

    def _resolve_side(self, update: OrderUpdate) -> OrderSide | None:
        if update.side is not None:
            return update.side
        factory = get_session_factory()
        with factory() as session:
            s = session.execute(
                select(DbExecutionOrder.side).where(
                    DbExecutionOrder.tenant_id == self._tenant_id,
                    DbExecutionOrder.trading_mode == self._trading_mode,
                    DbExecutionOrder.order_id == update.order_id,
                )
            ).scalar_one_or_none()
        if s == OrderSide.BUY.value:
            return OrderSide.BUY
        if s == OrderSide.SELL.value:
            return OrderSide.SELL
        return None

    def _patch_execution_order(
        self,
        tenant_id: str,
        order_id: str,
        status: str,
        extra: dict[str, Any] | None,
    ) -> None:
        factory = get_session_factory()
        with factory() as session:
            with session.begin():
                row = session.execute(
                    select(DbExecutionOrder).where(
                        DbExecutionOrder.tenant_id == tenant_id,
                        DbExecutionOrder.trading_mode == self._trading_mode,
                        DbExecutionOrder.order_id == order_id,
                    )
                ).scalar_one_or_none()
                if row is None:
                    return
                row.status = status
                if extra:
                    merged = dict(row.raw or {})
                    merged["last_stream"] = extra
                    row.raw = merged

    async def _record_fill(self, tenant_id: str, update: OrderUpdate) -> bool:
        """Persist fill; returns False if row already existed (dedupe — do not apply qty again)."""
        inserted = self._logger.log_fill(update=update, raw=update.raw, is_snapshot=False)
        if inserted:
            self._patch_execution_order(tenant_id, update.order_id, update.status.value, update.raw)
        return inserted

    async def _record_fill_snapshot(self, tenant_id: str, update: OrderUpdate) -> bool:
        """Persist replayed fills for audit; idempotent; no bracket orders."""
        inserted = self._logger.log_fill(update=update, raw=update.raw, is_snapshot=True)
        if inserted:
            self._patch_execution_order(tenant_id, update.order_id, update.status.value, update.raw)
        return inserted

    async def _place_oco_bracket(self, tenant_id: str, fields: dict[str, Any], u: OrderUpdate) -> None:
        """Place OCO stop+target for strategy_006 futures entries (live fills only)."""
        try:
            print(f"[OCO_START] Placing bracket for {fields.get('symbol')} @ {fields.get('fill_price')}")
        except Exception:
            print("[OCO_START] Placing bracket")
        if self._adapter is None:
            return
        oid = u.order_id
        if oid in self._bracket_leg_ids:
            return
        strategy_id = self._lookup_strategy_id(oid)
        if strategy_id != "strategy_006" or u.status != OrderStatus.FILLED:
            return
        settings = get_settings()
        acct = (str(fields.get("account_id") or "")).strip() or (u.account_id or "").strip()
        if not acct:
            print("[BRACKET] missing AccountID on fill; skipping OCO bracket")
            return

        root = _futures_root_from_symbol(str(fields.get("symbol") or u.symbol or ""))
        if root not in ("MES", "MNQ", "ES", "NQ"):
            return

        fill_price = fields["fill_price"]
        if not isinstance(fill_price, Decimal):
            fill_price = Decimal(str(fill_price))
        side = str(fields.get("side") or "").lower()
        if not side:
            side = "buy" if u.side == OrderSide.BUY else "sell"

        fill_qty = fields.get("fill_qty")
        try:
            qty_s = str(int(float(fill_qty)))
        except Exception:
            qty_s = "1"

        if root in ("ES", "MES"):
            path_symbol = FUTURES_FRONT_MONTH.get("MES", "MESM26")
            stop_dist = Decimal("4")
            target_dist = Decimal("8")
        else:
            path_symbol = FUTURES_FRONT_MONTH.get("MNQ", "MNQM26")
            stop_dist = Decimal("10")
            target_dist = Decimal("20")

        if side == "buy":
            stop_price = fill_price - stop_dist
            target_price = fill_price + target_dist
            exit_action = "SELL"
        else:
            stop_price = fill_price + stop_dist
            target_price = fill_price - target_dist
            exit_action = "BUY"

        print(
            f"[BRACKET] {root} {'SHORT' if side == 'sell' else 'LONG'}: "
            f"stop={stop_price:.2f} target={target_price:.2f} (OCO)"
        )

        oco_body: dict[str, Any] = {
            "Type": "OCO",
            "Orders": [
                {
                    "AccountID": acct,
                    "Symbol": path_symbol,
                    "Quantity": qty_s,
                    "OrderType": "StopMarket",
                    "TradeAction": exit_action,
                    "TimeInForce": {"Duration": "DAY"},
                    "AssetType": "FUTURE",
                    "StopPrice": f"{float(stop_price):.2f}",
                },
                {
                    "AccountID": acct,
                    "Symbol": path_symbol,
                    "Quantity": qty_s,
                    "OrderType": "Limit",
                    "TradeAction": exit_action,
                    "TimeInForce": {"Duration": "DAY"},
                    "AssetType": "FUTURE",
                    "LimitPrice": f"{float(target_price):.2f}",
                },
            ],
        }

        base = (
            getattr(self._adapter, "order_api_url", None)
            or getattr(self._adapter, "_order_api_url", "")
            or ""
        ).rstrip("/")
        if not base:
            print("[OCO_ERR] adapter missing order_api_url")
            return

        bearer_fn = getattr(self._adapter, "_bearer_token", None)
        if bearer_fn is None:
            print("[OCO_ERR] adapter missing _bearer_token")
            return
        bearer = await bearer_fn(tenant_id)  # type: ignore[misc]
        url = f"{base}/v3/orderexecution/ordergroups"
        headers = {
            "Authorization": f"Bearer {bearer}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json=oco_body, headers=headers)
            if resp.status_code in (200, 201):
                try:
                    data = resp.json()
                except Exception:
                    data = None
                # Best-effort: remember child order ids so we don't bracket bracket legs.
                if isinstance(data, dict) and isinstance(data.get("Orders"), list):
                    for r in data["Orders"]:
                        if isinstance(r, dict):
                            cid = r.get("OrderID") or r.get("OrderId")
                            if cid:
                                self._bracket_leg_ids.add(str(cid))
                print(f"[OCO] Bracket placed for {root} qty={qty_s}")
            else:
                print(f"[OCO_ERR] Status: {resp.status_code}")
                try:
                    print(f"[OCO_ERR] Response: {resp.text}")
                except Exception:
                    pass
        except Exception as e:
            print(f"[OCO_ERR] Failed: {e}")

    async def _record_rejection(self, tenant_id: str, update: OrderUpdate) -> None:
        self._patch_execution_order(tenant_id, update.order_id, OrderStatus.REJECTED.value, update.raw)

    async def _get_account_uuid(self, tenant_id: str, broker_account_id: str) -> str | None:
        """Resolve broker account string (e.g. SIM3236524F) to ``accounts.id`` UUID."""
        factory = get_session_factory()
        with factory() as session:
            r = session.execute(
                select(DbAccount.id).where(
                    DbAccount.tenant_id == tenant_id,
                    DbAccount.trading_mode == self._trading_mode,
                    DbAccount.broker_account_id == broker_account_id,
                ).limit(1)
            ).scalar_one_or_none()
            return str(r) if r else None

    async def _update_position(
        self,
        tenant_id: str,
        u_cum: OrderUpdate,
        *,
        live: bool,
        leg_qty: Decimal,
        fill_price: Decimal,
        side: str,
    ) -> None:
        """Update ``positions`` (explicit ledger); live fills also update ``PositionTracker`` for risk."""
        broker_acct = (u_cum.account_id or "").strip()
        sym = (u_cum.symbol or "").strip()
        if not broker_acct or not sym or not side:
            return
        sym_u = sym.upper()

        account_uuid = await self._get_account_uuid(tenant_id, broker_acct)
        if not account_uuid:
            print(
                f"[WARN] Account not found in DB: {broker_acct} — position not updated. "
                f"Run: python scripts/seed_accounts.py"
            )
            return

        strategy_id = self._lookup_strategy_id(u_cum.order_id)
        if live and strategy_id:
            side_e = OrderSide.BUY if side == "buy" else OrderSide.SELL
            self._tracker.apply_fill(
                tenant_id=tenant_id,
                trading_mode=self._trading_mode,
                account_id=broker_acct,
                strategy_id=strategy_id,
                order_id=u_cum.order_id,
                symbol=sym,
                side=side_e,
                update=u_cum,
            )

        self._apply_realtime_db_fill(account_uuid, sym_u, fill_price, leg_qty, side)

    def _apply_realtime_db_fill(
        self,
        account_uuid: str,
        symbol: str,
        fill_price: Decimal,
        fill_qty: Decimal,
        side: str,
    ) -> None:
        """Upsert ``positions`` row from fill deltas (signed quantity, VWAP on adds)."""
        if fill_qty <= 0 or side not in ("buy", "sell"):
            return
        is_buy = side == "buy"
        factory = get_session_factory()
        with factory() as session:
            with session.begin():
                row = session.execute(
                    select(DbPosition).where(
                        DbPosition.tenant_id == self._tenant_id,
                        DbPosition.trading_mode == self._trading_mode,
                        DbPosition.account_id == account_uuid,
                        DbPosition.symbol == symbol,
                    )
                ).scalar_one_or_none()
                current_qty = row.quantity if row is not None else Decimal("0")
                current_avg = row.avg_cost if row is not None else None

                if is_buy:
                    new_qty = current_qty + fill_qty
                    if current_qty <= 0:
                        new_avg: Decimal | None = fill_price
                    else:
                        ca = current_avg if current_avg is not None else fill_price
                        new_avg = (ca * current_qty + fill_price * fill_qty) / new_qty if new_qty != 0 else fill_price
                else:
                    new_qty = current_qty - fill_qty
                    new_avg = current_avg
                    if new_avg is None and new_qty != 0:
                        new_avg = fill_price

                if new_qty == 0:
                    if row is not None:
                        session.delete(row)
                    print(f"[POSITION] {symbol} CLOSED")
                    return

                direction = "LONG" if new_qty > 0 else "SHORT"
                if row is None:
                    session.add(
                        DbPosition(
                            tenant_id=self._tenant_id,
                            trading_mode=self._trading_mode,
                            account_id=account_uuid,
                            symbol=symbol,
                            quantity=new_qty,
                            avg_cost=new_avg,
                            raw=None,
                        )
                    )
                else:
                    row.quantity = new_qty
                    row.avg_cost = new_avg
                navg = float(new_avg) if new_avg is not None else 0.0
                print(f"[POSITION] {symbol} {direction} qty={abs(new_qty)} avg={navg:.2f}")
