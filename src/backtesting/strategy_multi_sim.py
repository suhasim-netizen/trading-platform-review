"""Simulations for Strategy 002, 004 (daily equities) and 006 (5m futures)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .engine import _metrics_from_returns

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"


def _load_daily(sym: str) -> pd.DataFrame:
    path = DATA / f"{sym.lower()}_2023_2026.csv"
    df = pd.read_csv(path, parse_dates=["Date"], index_col="Date")
    df.columns = [c.lower() for c in df.columns]
    return df.sort_index()


def _daily_returns_from_equity(eq: pd.Series) -> pd.Series:
    eq = eq.astype(float).replace(0.0, np.nan).ffill()
    return eq.pct_change().fillna(0.0)


# --- Strategy 002 ---


@dataclass
class Pos002:
    sym: str
    shares: int
    p0: float
    entry_idx: int


def run_strategy_002(
    *,
    start: str,
    end: str,
    is_split: str,
    oos_end: str,
    total_capital: float = 20_000.0,
    per_slot: float = 10_000.0,
    max_pos: int = 2,
) -> tuple[pd.Series, dict[str, Any]]:
    syms = ["AVGO", "LLY", "TSM", "GEV"]
    px = {s: _load_daily(s) for s in syms}
    vix = _load_daily("vix")

    all_idx = None
    for s in syms:
        ix = px[s].index[(px[s].index >= pd.Timestamp(start)) & (px[s].index < pd.Timestamp(end))]
        all_idx = ix if all_idx is None else all_idx.union(ix)
    vx = vix.index[(vix.index >= pd.Timestamp(start)) & (vix.index < pd.Timestamp(end))]
    all_idx = all_idx.union(vx).sort_values()

    dates = list(all_idx)

    def row(df: pd.DataFrame, d: pd.Timestamp) -> pd.Series | None:
        if d not in df.index:
            return None
        return df.loc[d]

    # Indicators (native calendar per symbol)
    ind: dict[str, dict[str, Any]] = {}
    for s in syms:
        c = px[s]["close"].astype(float)
        v = px[s]["volume"].astype(float)
        sma50 = c.rolling(50, min_periods=50).mean()
        sma20 = c.rolling(20, min_periods=20).mean()
        vbar20 = v.rolling(20, min_periods=20).mean()
        sig = ((c > sma50) & (c > sma20) & (v > 1.5 * vbar20)).fillna(False)
        ind[s] = {"c": c, "sma20": sma20, "sig": sig}

    cash = float(total_capital)
    positions: list[Pos002] = []
    pending: list[str] = []
    equity: list[float] = []
    eq_dates: list[pd.Timestamp] = []
    trades = 0

    for di, d in enumerate(dates):
        ohl = {s: row(px[s], d) for s in syms}
        vix_c = float(vix.loc[d, "close"]) if d in vix.index else np.nan
        vix_ref_entry = (
            float(vix.loc[dates[di - 1], "close"])
            if di > 0 and dates[di - 1] in vix.index
            else np.nan
        )

        # Entries at open (from prior night's pending). VIX gate uses prior session close (T-1).
        pending_sorted = sorted([s for s in pending if s in syms])
        pending = []
        for s in pending_sorted:
            if len(positions) >= max_pos:
                break
            if any(p.sym == s for p in positions):
                continue
            ro = ohl.get(s)
            if ro is None or pd.isna(ro.get("open")):
                continue
            if np.isnan(vix_ref_entry) or vix_ref_entry > 28.0:
                continue
            open_px = float(ro["open"])
            used = 0.0
            for p in positions:
                r2 = ohl.get(p.sym)
                if r2 is not None and not pd.isna(r2.get("open")):
                    used += p.shares * float(r2["open"])
            remaining = total_capital - used
            slot = min(per_slot, remaining, total_capital - used)
            if slot <= 0 or open_px <= 0:
                continue
            sh = int(np.floor(slot / open_px))
            if sh <= 0:
                continue
            cost = sh * open_px
            if cost > cash + 1e-6:
                continue
            cash -= cost
            positions.append(Pos002(s, sh, open_px, di))
            trades += 1

        # Intraday stops
        still: list[Pos002] = []
        for p in positions:
            ro = ohl.get(p.sym)
            if ro is None:
                still.append(p)
                continue
            low = float(ro["low"])
            stop = p.p0 * 0.92
            if low <= stop:
                cash += p.shares * stop
                trades += 1
            else:
                still.append(p)
        positions = still

        # Close: time exit & SMA cross (stop already handled intraday)
        still = []
        for p in positions:
            ro = ohl.get(p.sym)
            if ro is None:
                still.append(p)
                continue
            close = float(ro["close"])
            sessions = di - p.entry_idx + 1
            sma20_prev = ind[p.sym]["sma20"]
            c_prev = ind[p.sym]["c"]
            d_prev = dates[di - 1] if di > 0 else None
            cross = False
            if (
                d_prev is not None
                and d in sma20_prev.index
                and d_prev in sma20_prev.index
            ):
                c_y = float(c_prev.loc[d])
                c_x = float(c_prev.loc[d_prev])
                s_y = float(sma20_prev.loc[d])
                s_x = float(sma20_prev.loc[d_prev])
                cross = (c_y < s_y) and (c_x >= s_x)
            if sessions >= 20:
                cash += p.shares * close
                trades += 1
            elif cross:
                cash += p.shares * close
                trades += 1
            else:
                still.append(p)
        positions = still

        mtm = float(cash)
        for p in positions:
            ro = ohl.get(p.sym)
            if ro is not None and not pd.isna(ro.get("close")):
                mtm += p.shares * float(ro["close"])
        equity.append(mtm)
        eq_dates.append(d)

        # Signals after close -> pending for tomorrow (VIX evaluated on signal day close)
        if di + 1 < len(dates):
            pending = []
            for s in sorted(syms):
                if d not in ind[s]["sig"].index or not bool(ind[s]["sig"].loc[d]):
                    continue
                if np.isnan(vix_c) or vix_c > 28.0:
                    continue
                if any(x.sym == s for x in positions):
                    continue
                pending.append(s)

    eq_s = pd.Series(equity, index=pd.DatetimeIndex(eq_dates), name="equity")
    rets = _daily_returns_from_equity(eq_s)
    meta = {
        "num_trades": trades,
        "strategy_id": "strategy_002",
        "version": "0.1.0",
    }
    return rets, meta


# --- Strategy 004 ---


@dataclass
class Pos004:
    sym: str
    shares: int
    p0: float
    entry_idx: int


def run_strategy_004(
    *,
    start: str,
    end: str,
    is_split: str,
    oos_end: str,
    total_capital: float = 7_000.0,
    per_slot: float = 3_500.0,
    max_pos: int = 2,
) -> tuple[pd.Series, dict[str, Any]]:
    syms = ["LASR", "LITE", "COHR", "SNDK", "STRL"]
    px = {}
    for s in syms:
        px[s] = _load_daily(s)

    all_idx = None
    for s in syms:
        ix = px[s].index[(px[s].index >= pd.Timestamp(start)) & (px[s].index < pd.Timestamp(end))]
        all_idx = ix if all_idx is None else all_idx.union(ix)
    all_idx = all_idx.sort_values()
    dates = list(all_idx)

    cash = float(total_capital)
    positions: list[Pos004] = []
    pending: list[str] = []
    equity: list[float] = []
    eq_dates: list[pd.Timestamp] = []
    trades = 0

    for di, d in enumerate(dates):
        ohl = {s: px[s].loc[d] if d in px[s].index else None for s in syms}

        pending_sorted = sorted([s for s in pending if s in syms])
        pending = []
        for s in pending_sorted:
            if len(positions) >= max_pos:
                break
            if any(p.sym == s for p in positions):
                continue
            ro = ohl.get(s)
            if ro is None:
                continue
            open_px = float(ro["open"])
            used = 0.0
            for p in positions:
                r2 = ohl.get(p.sym)
                if r2 is not None and not pd.isna(r2.get("open")):
                    used += p.shares * float(r2["open"])
            remaining = total_capital - used
            slot = min(per_slot, remaining)
            if slot <= 0 or open_px <= 0:
                continue
            sh = int(np.floor(slot / open_px))
            if sh <= 0:
                continue
            cost = sh * open_px
            if cost > cash + 1e-6:
                continue
            cash -= cost
            positions.append(Pos004(s, sh, open_px, di))
            trades += 1

        still: list[Pos004] = []
        for p in positions:
            ro = ohl.get(p.sym)
            if ro is None:
                still.append(p)
                continue
            close = float(ro["close"])
            low = float(ro["low"])
            high = float(ro["high"])
            stop = p.p0 * 0.96
            tp = p.p0 * 1.08
            sessions = di - p.entry_idx + 1
            if low <= stop:
                cash += p.shares * stop
                trades += 1
            elif high >= tp:
                cash += p.shares * tp
                trades += 1
            elif sessions >= 10:
                cash += p.shares * close
                trades += 1
            else:
                still.append(p)
        positions = still

        mtm = cash
        for p in positions:
            ro = ohl.get(p.sym)
            if ro is not None:
                mtm += p.shares * float(ro["close"])
        equity.append(mtm)
        eq_dates.append(d)

        # Signals for next session open
        if di + 1 < len(dates):
            pending = []
            if di >= 2:
                d1 = dates[di - 1]
                d2 = dates[di - 2]
                for s in sorted(syms):
                    df = px[s]
                    if d not in df.index:
                        continue
                    c = df["close"].astype(float)
                    l = df["low"].astype(float)
                    v = df["volume"].astype(float)
                    sma50 = c.rolling(50, min_periods=50).mean()
                    sma10 = c.rolling(10, min_periods=10).mean()
                    vbar20 = v.rolling(20, min_periods=20).mean()
                    ok_pull = False
                    for dp in (d1, d2):
                        if dp not in df.index:
                            continue
                        sma10_p = float(sma10.loc[dp])
                        if sma10_p <= 0:
                            continue
                        lp = float(l.loc[dp])
                        if abs(lp - sma10_p) / sma10_p <= 0.01 and lp <= sma10_p:
                            ok_pull = True
                            break
                    ct = float(c.loc[d])
                    uptrend = ct > float(sma50.loc[d])
                    reclaim = ct > float(sma10.loc[d])
                    vols = float(v.loc[d]) > 1.2 * float(vbar20.loc[d])
                    if uptrend and ok_pull and reclaim and vols:
                        if any(x.sym == s for x in positions):
                            continue
                        pending.append(s)

    eq_s = pd.Series(equity, index=pd.DatetimeIndex(eq_dates), name="equity")
    rets = _daily_returns_from_equity(eq_s)
    meta = {"num_trades": trades, "strategy_id": "strategy_004", "version": "0.1.0"}
    return rets, meta


def _wilder_rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    gain = d.clip(lower=0.0)
    loss = (-d).clip(lower=0.0)
    ag = gain.ewm(alpha=1.0 / n, adjust=False).mean()
    al = loss.ewm(alpha=1.0 / n, adjust=False).mean()
    rs = ag / al.replace(0.0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def _session_atr(high: pd.Series, low: pd.Series, close: pd.Series, sess: pd.Series) -> pd.Series:
    prev_c = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_c).abs(),
            (low - prev_c).abs(),
        ],
        axis=1,
    ).max(axis=1)
    first = ~sess.duplicated()
    tr = tr.where(~first, (high - low).abs())
    out = pd.Series(np.nan, index=close.index)
    for sid in sess.unique():
        m = sess == sid
        sub = tr.loc[m].copy()
        vals = sub.values.astype(float)
        if len(vals) < 2:
            continue
        atr = np.zeros_like(vals)
        atr[0] = vals[0]
        for i in range(1, len(vals)):
            atr[i] = (atr[i - 1] * 13.0 + vals[i]) / 14.0
        out.loc[m] = atr
    return out


def _session_vwap(h: pd.Series, l: pd.Series, c: pd.Series, v: pd.Series, sess: pd.Series) -> pd.Series:
    tp = (h + l + c) / 3.0
    pv = tp * v.replace(0.0, np.nan).fillna(0.0)
    out = pd.Series(np.nan, index=c.index)
    for sid in sess.unique():
        m = sess == sid
        cs = pv.loc[m].cumsum()
        vv = v.loc[m].cumsum()
        out.loc[m] = cs / vv.replace(0.0, np.nan)
    return out


def run_strategy_006(
    *,
    start: str,
    end: str,
    is_split: str,
    oos_end: str,
    initial_cash: float = 50_000.0,
    es_mult: float = 50.0,
    nq_mult: float = 20.0,
) -> tuple[pd.Series, dict[str, Any]]:
    es = pd.read_csv(DATA / "es_f_2025_2026_5m.csv")
    nq = pd.read_csv(DATA / "nq_f_2025_2026_5m.csv")
    for df in (es, nq):
        df["ts"] = pd.to_datetime(df["Datetime"], utc=True).dt.tz_convert("America/New_York")
        df.set_index("ts", inplace=True)
        df.sort_index(inplace=True)

    def sim_one(df: pd.DataFrame, mult: float) -> tuple[pd.Series, int]:
        from datetime import time as dtime

        d = df.copy()
        d["session"] = d.index.normalize()
        msk = (d.index.time >= dtime(9, 30)) & (d.index.time <= dtime(15, 55))
        d = d.loc[msk]
        if d.empty:
            return pd.Series(dtype=float), 0

        sess = d["session"]
        c = d["Close"].astype(float)
        vwap = _session_vwap(d["High"], d["Low"], c, d["Volume"].astype(float), sess)
        atr = _session_atr(d["High"].astype(float), d["Low"].astype(float), c, sess)
        rsi = _wilder_rsi(c, 14)
        upper = vwap + 0.5 * atr
        lower = vwap - 0.5 * atr

        c_prev = c.shift(1)
        u_prev = upper.shift(1)
        l_prev = lower.shift(1)

        pos = 0
        entry = 0.0
        realized = 0.0
        round_trips = 0
        mtm_curve: list[float] = []
        idxs: list[pd.Timestamp] = []

        for i in range(1, len(d)):
            ts = d.index[i]
            ci = float(c.iloc[i])
            hi = float(d["High"].iloc[i])
            loi = float(d["Low"].iloc[i])
            cp = float(c_prev.iloc[i])
            up = float(upper.iloc[i])
            lp = float(lower.iloc[i])
            upr = float(u_prev.iloc[i]) if pd.notna(u_prev.iloc[i]) else np.nan
            lwr = float(l_prev.iloc[i]) if pd.notna(l_prev.iloc[i]) else np.nan
            rs = float(rsi.iloc[i]) if pd.notna(rsi.iloc[i]) else np.nan

            valid = pd.notna(atr.iloc[i]) and pd.notna(rsi.iloc[i])

            long_sig = valid and (
                pd.notna(upr)
                and pd.notna(cp)
                and cp <= upr
                and ci > up
                and rs > 55.0
            )
            short_sig = valid and (
                pd.notna(lwr)
                and pd.notna(cp)
                and cp >= lwr
                and ci < lp
                and rs < 45.0
            )
            if long_sig and short_sig:
                long_sig = short_sig = False

            is_last = i == len(d) - 1 or sess.iloc[i + 1] != sess.iloc[i]

            if pos == 1:
                stop = entry * 0.995
                tp = entry * 1.0075
                exit_px = None
                if loi <= stop:
                    exit_px = stop
                elif hi >= tp:
                    exit_px = tp
                elif is_last:
                    exit_px = ci
                if exit_px is not None:
                    realized += (exit_px - entry) * mult
                    pos = 0
                    round_trips += 1
            elif pos == -1:
                stop = entry * 1.005
                tp = entry * (1.0 - 0.0075)
                exit_px = None
                if hi >= stop:
                    exit_px = stop
                elif loi <= tp:
                    exit_px = tp
                elif is_last:
                    exit_px = ci
                if exit_px is not None:
                    realized += (entry - exit_px) * mult
                    pos = 0
                    round_trips += 1

            if pos == 0:
                if long_sig:
                    pos = 1
                    entry = ci
                elif short_sig:
                    pos = -1
                    entry = ci

            unreal = 0.0
            if pos == 1:
                unreal = (ci - entry) * mult
            elif pos == -1:
                unreal = (entry - ci) * mult
            mtm_curve.append(realized + unreal)
            idxs.append(ts)

        pnl_s = pd.Series(mtm_curve, index=pd.DatetimeIndex(idxs))
        return pnl_s, round_trips

    es_pnl, es_tr = sim_one(es, es_mult)
    nq_pnl, nq_tr = sim_one(nq, nq_mult)

    all_t = es_pnl.index.union(nq_pnl.index).sort_values()
    es_a = es_pnl.reindex(all_t).ffill().fillna(0.0)
    nq_a = nq_pnl.reindex(all_t).ffill().fillna(0.0)
    equity = initial_cash + es_a + nq_a
    equity = equity.sort_index()
    tz = equity.index.tz
    s0 = pd.Timestamp(start) if tz is None else pd.Timestamp(start).tz_localize(tz)
    s1 = pd.Timestamp(end) if tz is None else pd.Timestamp(end).tz_localize(tz)
    equity = equity[(equity.index >= s0) & (equity.index < s1)]
    eq_d = equity.resample("1D").last().dropna()
    if eq_d.empty or len(equity) == 0:
        raise RuntimeError(
            "Strategy 006: no bars in date window — widen end date (Yahoo 5m is last ~60 days only)."
        )
    rets = _daily_returns_from_equity(eq_d)
    meta = {
        "num_trades": int(es_tr + nq_tr),
        "strategy_id": "strategy_006",
        "version": "0.1.0",
    }
    return rets, meta
