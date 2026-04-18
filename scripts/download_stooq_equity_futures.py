"""Download daily US equity and 5m futures CSVs from Stooq into data/."""

from __future__ import annotations

import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

DAILY_TICKERS = [
    "AVGO",
    "LLY",
    "TSM",
    "GEV",
    "LASR",
    "LITE",
    "COHR",
    "SNDK",
    "STRL",
    "^VIX",
]

FUTURES_5M = [
    ("es.f", "es_f_2025_2026_5m.csv"),
    ("nq.f", "nq_f_2025_2026_5m.csv"),
]


def _download(url: str, dest: Path) -> int:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; trading-platform/1.0)"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)
    return len(raw)


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    for t in DAILY_TICKERS:
        if t.startswith("^"):
            sym = "^vix"
            dest = DATA / "vix_2023_2026.csv"
        else:
            sym = f"{t.lower()}.us"
            dest = DATA / f"{t.lower()}_2023_2026.csv"
        q = urllib.parse.quote(sym, safe="")
        url = f"https://stooq.com/q/d/l/?s={q}&d1=20230101&d2=20260101&i=d"
        n = _download(url, dest)
        print(f"OK {dest.name} ({n} bytes)")

    for stooq_sym, fname in FUTURES_5M:
        q = urllib.parse.quote(stooq_sym, safe="")
        url = f"https://stooq.com/q/d/l/?s={q}&d1=20250101&d2=20260101&i=5"
        dest = DATA / fname
        n = _download(url, dest)
        print(f"OK {dest.name} ({n} bytes)")


if __name__ == "__main__":
    main()
