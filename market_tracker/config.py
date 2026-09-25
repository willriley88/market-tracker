"""Watchlist loading and path resolution."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(os.environ.get("MARKET_TRACKER_ROOT", Path(__file__).resolve().parent.parent))
DEFAULT_WATCHLIST = ROOT / "watchlist.json"
DEFAULT_DB = ROOT / "data" / "market.db"
DEFAULT_HTML = ROOT / "docs" / "index.html"


@dataclass(frozen=True)
class Ticker:
    symbol: str
    label: str
    group: str = "Other"

    @classmethod
    def from_obj(cls, obj, group: str = "Other") -> "Ticker":
        if isinstance(obj, str):
            return cls(symbol=obj, label=obj, group=group)
        symbol = obj["symbol"]
        return cls(symbol=symbol, label=obj.get("label", symbol), group=obj.get("group", group))


def load_watchlist(path=None) -> list:
    """Read watchlist.json into Ticker objects.

    Accepted shapes::

        {"groups": {"Equities": ["AAPL", {"symbol": "VOO", "label": "S&P 500 ETF"}]}}
        {"tickers": ["AAPL", "BTC-USD"]}

    Duplicate symbols are dropped; first occurrence wins.
    """
    path = Path(path) if path else DEFAULT_WATCHLIST
    data = json.loads(path.read_text(encoding="utf-8"))

    tickers = []
    if "groups" in data:
        for group, items in data["groups"].items():
            for item in items:
                tickers.append(Ticker.from_obj(item, group=group))
    for item in data.get("tickers", []):
        tickers.append(Ticker.from_obj(item))

    seen = set()
    unique = []
    for t in tickers:
        key = t.symbol.upper()
        if key in seen:
            continue
        seen.add(key)
        unique.append(t)
    if not unique:
        raise ValueError(f"watchlist at {path} contains no tickers")
    return unique
