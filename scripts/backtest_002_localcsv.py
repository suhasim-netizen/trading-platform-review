"""Local-CSV backtest for Strategy 002 (Equity Momentum).

CRITICAL DATA RULE:
- Uses ONLY local CSV files under data/
- Uses the exact load_csv() function provided by the user
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


def load_csv(ticker: str) -> pd.DataFrame:
    path = f"data/{ticker.lower()}_2023_2026.csv"
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Missing: {path}. "
            f"Download from: https://stooq.com/q/d/l/"
            f"?s={ticker.lower()}.us&d1=20230101&d2=20260101&i=d"
        )
    df = pd.read_csv(path, parse_dates=["Date"], index_col="Date")
    df.columns = [c.lower() for c in df.columns]
    df = df.sort_index()  # Stooq returns newest first
    return df


@dataclass(frozen=True)
class Position:
    ticker: str
    shares: int
    entry_price: float
    entry_date: pd.Timestamp
    stop_price: float


@dataclass(frozen=True)
class Trade:
    ticker: str
    entry_date: pd.Timestamp
    entry_price: float
    exit_date: pd.Timestamp
    exit_price: float
    shares: int

    @property
    def pnl(self) -> float:
        return (self.exit_price - self.entry_price) * self.shares


def _sharpe(daily_ret: pd.Series) -> float:
    r = daily_ret.dropna().astype(float)
    if len(r) < 2:
        return 0.0
    mu = float(r.mean())
    sig = float(r.std(ddof=1))
    return float((mu / sig) * np.sqrt(252.0)) if sig > 1e-12 else 0.0


def _max_drawdown_from_equity(equity: pd.Series) -> float:
    eq = equity.dropna().astype(float)
    if eq.empty:
        return 0.0
    peak = eq.cummax()
    dd = (eq - peak) / peak
    return float(dd.min())


def _total_return_from_equity(equity: pd.Series) -> float:
    eq = equity.dropna().astype(float)
    if len(eq) < 2:
        return 0.0
    return float(eq.iloc[-1] / eq.iloc[0] - 1.0)


def run_backtest_002(
    *,
    tickers: list[str],
    start: str,
    end: str,
    capital: float,
    per_position_cap: float,
) -> tuple[pd.Series, pd.Series, list[Trade]]:
    """Loop-based simulation.

    - Signals evaluated on close of day d.
    - Entries/exits filled on next trading day open for that ticker (no lookahead).
    - Stop: if day's low <= stop price, exit same day at stop price.
    """

    px: dict[str, pd.DataFrame] = {t: load_csv(t) for t in tickers}
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)

    sig_buy: dict[str, pd.Series] = {}
    sig_sell: dict[str, pd.Series] = {}
    next_day: dict[str, dict[pd.Timestamp, pd.Timestamp]] = {}

    for t, df0 in px.items():
        df = df0.loc[(df0.index >= start_ts) & (df0.index < end_ts)].copy()
        if df.empty:
            sig_buy[t] = pd.Series(dtype=bool)
            sig_sell[t] = pd.Series(dtype=bool)
            next_day[t] = {}
            px[t] = df
            continue

        c = df["close"].astype(float)
        v = df["volume"].astype(float)
        sma20 = c.rolling(20, min_periods=20).mean()
        sma50 = c.rolling(50, min_periods=50).mean()
        v20 = v.rolling(20, min_periods=20).mean()

        sig_buy[t] = ((c > sma20) & (c > sma50) & (v > 1.5 * v20)).fillna(False)
        sig_sell[t] = (c < sma20).fillna(False)

        idx = list(df.index)
        next_day[t] = {idx[i]: idx[i + 1] for i in range(len(idx) - 1)}
        px[t] = df

    # Union calendar for daily equity marking.
    all_days = sorted({d for df in px.values() for d in df.index})

    cash = float(capital)
    positions: dict[str, Position] = {}
    trades: list[Trade] = []

    pending_entries: dict[pd.Timestamp, list[str]] = {}
    pending_exits: dict[pd.Timestamp, list[str]] = {}

    def schedule_entry(t: str, signal_day: pd.Timestamp) -> None:
        nd = next_day[t].get(signal_day)
        if nd is not None:
            pending_entries.setdefault(nd, []).append(t)

    def schedule_exit(t: str, signal_day: pd.Timestamp) -> None:
        nd = next_day[t].get(signal_day)
        if nd is not None:
            pending_exits.setdefault(nd, []).append(t)

    equity_vals: list[float] = []
    equity_days: list[pd.Timestamp] = []

    for day in all_days:
        # Exits at open.
        for t in pending_exits.get(day, []):
            if t not in positions:
                continue
            if day not in px[t].index:
                continue
            open_px = float(px[t].loc[day, "open"])
            pos = positions.pop(t)
            cash += pos.shares * open_px
            trades.append(
                Trade(
                    ticker=t,
                    entry_date=pos.entry_date,
                    entry_price=pos.entry_price,
                    exit_date=day,
                    exit_price=open_px,
                    shares=pos.shares,
                )
            )

        # Entries at open (max 2 positions).
        for t in pending_entries.get(day, []):
            if t in positions:
                continue
            if len(positions) >= 2:
                continue
            if day not in px[t].index:
                continue
            open_px = float(px[t].loc[day, "open"])
            if open_px <= 0:
                continue
            shares = int(np.floor(per_position_cap / open_px))
            if shares <= 0:
                continue
            cost = shares * open_px
            if cost > cash + 1e-6:
                continue
            cash -= cost
            positions[t] = Position(
                ticker=t,
                shares=shares,
                entry_price=open_px,
                entry_date=day,
                stop_price=open_px * 0.92,
            )

        # Stops intraday.
        for t, pos in list(positions.items()):
            if day not in px[t].index:
                continue
            low = float(px[t].loc[day, "low"])
            if low <= pos.stop_price:
                cash += pos.shares * pos.stop_price
                positions.pop(t)
                trades.append(
                    Trade(
                        ticker=t,
                        entry_date=pos.entry_date,
                        entry_price=pos.entry_price,
                        exit_date=day,
                        exit_price=pos.stop_price,
                        shares=pos.shares,
                    )
                )

        # End-of-day signal evaluation at close.
        for t in tickers:
            if day not in px[t].index:
                continue
            if t in positions:
                if bool(sig_sell[t].loc[day]):
                    schedule_exit(t, day)
            else:
                if bool(sig_buy[t].loc[day]):
                    schedule_entry(t, day)

        # Mark to market at close.
        mtm = cash
        for t, pos in positions.items():
            if day in px[t].index:
                close_px = float(px[t].loc[day, "close"])
            else:
                close_px = float(px[t]["close"].iloc[-1])
            mtm += pos.shares * close_px
        equity_vals.append(float(mtm))
        equity_days.append(day)

    equity = pd.Series(equity_vals, index=pd.DatetimeIndex(equity_days), name="equity").sort_index()
    daily_ret = equity.pct_change().fillna(0.0)
    return equity, daily_ret, trades


def main() -> None:
    tickers = ["AVGO", "LLY", "TSM", "GEV"]
    start = "2023-01-01"
    end = "2026-01-01"
    split = pd.Timestamp("2025-01-01")

    equity, daily_ret, trades = run_backtest_002(
        tickers=tickers,
        start=start,
        end=end,
        capital=20_000.0,
        per_position_cap=10_000.0,
    )

    is_mask = equity.index < split
    oos_mask = (equity.index >= split) & (equity.index < pd.Timestamp(end))

    is_eq = equity.loc[is_mask]
    oos_eq = equity.loc[oos_mask]
    is_ret = daily_ret.loc[is_mask]
    oos_ret = daily_ret.loc[oos_mask]

    is_sh = _sharpe(is_ret)
    oos_sh = _sharpe(oos_ret)
    is_dd = _max_drawdown_from_equity(is_eq)
    oos_dd = _max_drawdown_from_equity(oos_eq)
    is_tr = _total_return_from_equity(is_eq)
    oos_tr = _total_return_from_equity(oos_eq)

    is_trades = [tr for tr in trades if tr.exit_date < split]
    oos_trades = [tr for tr in trades if split <= tr.exit_date < pd.Timestamp(end)]

    def win_rate(ts: list[Trade]) -> float:
        return float(sum(1 for tr in ts if tr.pnl > 0) / len(ts)) if ts else 0.0

    is_wr = win_rate(is_trades)
    oos_wr = win_rate(oos_trades)

    verdict = "PASS" if (oos_sh >= 0.8 and abs(oos_dd) <= 0.25) else "FAIL"

    out = Path("docs/backtests/backtest_002_v0.1.0_results.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "\n".join(
            [
                "# Backtest — Strategy 002 (Equity Momentum) v0.1.0",
                "",
                "**Data:** Local CSVs from `data/` (Stooq format).",
                "",
                "**Execution assumptions:** signals evaluated on **close**; entries/exits filled on **next session open**; stop-loss uses same-day **low** with fill at stop price.",
                "",
                f"**Capital:** $20,000 (max 2 positions, $10,000 each).",
                f"**Window:** {start} to {end}. **IS:** {start} to 2025-01-01. **OOS:** 2025-01-01 to {end}.",
                "",
                "| Metric | In-Sample | Out-of-Sample |",
                "| --- | --- | --- |",
                f"| Sharpe ratio | {is_sh:.3f} | {oos_sh:.3f} |",
                f"| Max drawdown % | {abs(is_dd)*100:.2f} | {abs(oos_dd)*100:.2f} |",
                f"| Total return % | {is_tr*100:.2f} | {oos_tr*100:.2f} |",
                f"| Win rate % | {is_wr*100:.2f} | {oos_wr*100:.2f} |",
                f"| Num trades | {len(is_trades)} | {len(oos_trades)} |",
                "",
                f"**Verdict:** {verdict} — PASS if OOS Sharpe ≥ 0.8 and |OOS max DD| ≤ 25%.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    print("IS Sharpe:", round(is_sh, 3), "OOS Sharpe:", round(oos_sh, 3))
    print("IS MaxDD%:", round(abs(is_dd) * 100, 2), "OOS MaxDD%:", round(abs(oos_dd) * 100, 2))
    print("IS TotRet%:", round(is_tr * 100, 2), "OOS TotRet%:", round(oos_tr * 100, 2))
    print("IS Win%:", round(is_wr * 100, 2), "OOS Win%:", round(oos_wr * 100, 2))
    print("IS Trades:", len(is_trades), "OOS Trades:", len(oos_trades))


if __name__ == "__main__":
    main()

