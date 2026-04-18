"""Download OHLCV from Yahoo Finance chart API (v8).

Stooq free CSV now requires an ``apikey`` query parameter; Yahoo chart API works with a
browser User-Agent for reproducible local CSV snapshots.

**5-minute limitation (Yahoo):** intraday ``5m`` data is only available for the **last ~60
calendar days** from *now*. Older 5-minute history cannot be retrieved via this endpoint.
For full-year 5m (2025–2026), use Stooq with an API key, broker history, or another vendor.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def _fetch_chart(symbol: str, period1: int, period2: int, interval: str) -> dict:
    q = urllib.parse.quote(symbol, safe="")
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{q}"
        f"?period1={period1}&period2={period2}&interval={interval}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())


def _write_daily_csv(symbol: str, dest: Path, period1: int, period2: int) -> int:
    data = _fetch_chart(symbol, period1, period2, "1d")
    res = data.get("chart", {}).get("result")
    if not res:
        err = data.get("chart", {}).get("error", {})
        raise RuntimeError(f"No chart result for {symbol}: {err}")
    r0 = res[0]
    ts = r0.get("timestamp") or []
    q = r0.get("indicators", {}).get("quote", [{}])[0]
    if not ts:
        raise RuntimeError(f"Empty timestamps for {symbol}")
    lines = ["Date,Open,High,Low,Close,Volume"]
    for i, t in enumerate(ts):
        from datetime import datetime, timezone

        dt = datetime.fromtimestamp(t, tz=timezone.utc).date().isoformat()
        o = q.get("open", [None] * len(ts))[i]
        h = q.get("high", [None] * len(ts))[i]
        l = q.get("low", [None] * len(ts))[i]
        c = q.get("close", [None] * len(ts))[i]
        v = q.get("volume", [None] * len(ts))[i]
        if c is None:
            continue
        lines.append(
            f"{dt},{float(o) if o is not None else c},"
            f"{float(h) if h is not None else c},{float(l) if l is not None else c},"
            f"{float(c)},{int(v) if v is not None else 0}"
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines) - 1


def _write_daily_csv_range_param(symbol: str, dest: Path, range_param: str) -> int:
    """Use ``range=2y`` when fixed period fails (e.g. recent IPO)."""
    q = urllib.parse.quote(symbol, safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{q}?range={range_param}&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode())
    res = data.get("chart", {}).get("result")
    if not res:
        raise RuntimeError(f"No chart result for {symbol}")
    r0 = res[0]
    ts = r0.get("timestamp") or []
    q = r0.get("indicators", {}).get("quote", [{}])[0]
    lines = ["Date,Open,High,Low,Close,Volume"]
    for i, t in enumerate(ts):
        from datetime import datetime, timezone

        dt = datetime.fromtimestamp(t, tz=timezone.utc).date().isoformat()
        o = q.get("open", [None] * len(ts))[i]
        h = q.get("high", [None] * len(ts))[i]
        l = q.get("low", [None] * len(ts))[i]
        c = q.get("close", [None] * len(ts))[i]
        v = q.get("volume", [None] * len(ts))[i]
        if c is None:
            continue
        lines.append(
            f"{dt},{float(o) if o is not None else c},"
            f"{float(h) if h is not None else c},{float(l) if l is not None else c},"
            f"{float(c)},{int(v) if v is not None else 0}"
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines) - 1


def _write_intraday_csv_recent(symbol: str, dest: Path, days_back: int = 58) -> int:
    """5m bars — Yahoo only serves ~the last 60 days."""
    from datetime import datetime, timezone

    now = int(datetime.now(timezone.utc).timestamp())
    p2 = now
    p1 = now - days_back * 86400
    data = _fetch_chart(symbol, p1, p2, "5m")
    res = data.get("chart", {}).get("result")
    if not res:
        err = data.get("chart", {}).get("error", {})
        raise RuntimeError(f"No chart result for {symbol}: {err}")
    r0 = res[0]
    ts = r0.get("timestamp") or []
    q = r0.get("indicators", {}).get("quote", [{}])[0]
    lines = ["Datetime,Open,High,Low,Close,Volume"]
    for i, t in enumerate(ts):
        from datetime import datetime, timezone

        dt = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        o = q.get("open", [None] * len(ts))[i]
        h = q.get("high", [None] * len(ts))[i]
        l = q.get("low", [None] * len(ts))[i]
        c = q.get("close", [None] * len(ts))[i]
        v = q.get("volume", [None] * len(ts))[i]
        if c is None:
            continue
        lines.append(
            f"{dt},{float(o) if o is not None else c},"
            f"{float(h) if h is not None else c},{float(l) if l is not None else c},"
            f"{float(c)},{int(v) if v is not None else 0}"
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines) - 1


def main() -> None:
    # 2023-01-01 UTC .. 2026-01-01 UTC (exclusive upper bound on Yahoo side)
    p1_3y = 1672531200
    p2_3y = 1767225600

    daily = [
        ("AVGO", "avgo_2023_2026.csv", False),
        ("LLY", "lly_2023_2026.csv", False),
        ("TSM", "tsm_2023_2026.csv", False),
        ("GEV", "gev_2023_2026.csv", False),
        ("LASR", "lasr_2023_2026.csv", False),
        ("LITE", "lite_2023_2026.csv", False),
        ("COHR", "cohr_2023_2026.csv", False),
        ("SNDK", "sndk_2023_2026.csv", True),
        ("STRL", "strl_2023_2026.csv", False),
        ("^VIX", "vix_2023_2026.csv", False),
    ]
    for sym, fname, use_range in daily:
        if use_range:
            n = _write_daily_csv_range_param(sym, DATA / fname, "5y")
        else:
            n = _write_daily_csv(sym, DATA / fname, p1_3y, p2_3y)
        print(f"OK {fname} rows={n}")
        time.sleep(0.35)

    fut = [
        ("ES=F", "es_f_2025_2026_5m.csv"),
        ("NQ=F", "nq_f_2025_2026_5m.csv"),
    ]
    for sym, fname in fut:
        n = _write_intraday_csv_recent(sym, DATA / fname, days_back=58)
        print(f"OK {fname} rows={n} (Yahoo 5m ~last 60d)")
        time.sleep(0.5)


if __name__ == "__main__":
    main()
