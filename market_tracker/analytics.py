"""Return, drawdown, volatility and moving-average math.

All functions are pure and take plain lists of closes (oldest first), so
they are trivially testable without touching the network or a database.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict

TRADING_DAYS = 252


@dataclass
class Metrics:
    symbol: str
    label: str
    group: str
    currency: str
    last_close: float
    last_date: str
    change_1d: float | None
    change_5d: float | None
    change_1m: float | None
    change_3m: float | None
    change_ytd: float | None
    change_period: float | None
    high_52w: float | None
    low_52w: float | None
    pct_off_high: float | None
    sma_20: float | None
    sma_50: float | None
    sma_200: float | None
    vol_annualized: float | None
    max_drawdown: float | None
    trend: str
    bars: int

    def to_dict(self) -> dict:
        return asdict(self)


def pct_change(new: float, old: float):
    """Percent change as a fraction. None when the base is unusable."""
    if old is None or new is None or old == 0:
        return None
    return (new - old) / old


def change_over(closes, days: int):
    """Change over `days` trading days back from the latest close."""
    if len(closes) < days + 1:
        return None
    return pct_change(closes[-1], closes[-1 - days])


def sma(closes, window: int):
    if len(closes) < window:
        return None
    return sum(closes[-window:]) / window


def daily_returns(closes):
    out = []
    for prev, cur in zip(closes, closes[1:]):
        if prev:
            out.append((cur - prev) / prev)
    return out


def annualized_vol(closes):
    """Stdev of daily returns, scaled to a year. Needs >= 20 observations."""
    rets = daily_returns(closes)
    if len(rets) < 20:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(TRADING_DAYS)


def max_drawdown(closes):
    """Worst peak-to-trough decline as a negative fraction."""
    if len(closes) < 2:
        return None
    peak = closes[0]
    worst = 0.0
    for c in closes:
        peak = max(peak, c)
        if peak:
            worst = min(worst, (c - peak) / peak)
    return worst


def ytd_change(series):
    """Change from the last close of the previous year, if we have it."""
    if not series:
        return None
    last_date, last_close = series[-1]
    year = last_date[:4]
    prior = [c for d, c in series if d[:4] < year]
    if not prior:
        return None
    return pct_change(last_close, prior[-1])


def classify(last: float, s50, s200) -> str:
    """A blunt, honest trend label. Not advice, just where price sits."""
    if s50 is None or s200 is None:
        return "insufficient history"
    if last > s50 > s200:
        return "uptrend"
    if last < s50 < s200:
        return "downtrend"
    return "mixed"


def compute(symbol: str, label: str, group: str, currency: str, series) -> Metrics:
    """Build a Metrics row from [(date, close)] oldest-first."""
    if not series:
        raise ValueError(f"{symbol}: no price series")
    closes = [c for _, c in series]
    last_date, last_close = series[-1]
    window = closes[-TRADING_DAYS:] if len(closes) > TRADING_DAYS else closes
    hi = max(window)
    lo = min(window)
    s50 = sma(closes, 50)
    s200 = sma(closes, 200)

    return Metrics(
        symbol=symbol,
        label=label,
        group=group,
        currency=currency,
        last_close=last_close,
        last_date=last_date,
        change_1d=change_over(closes, 1),
        change_5d=change_over(closes, 5),
        change_1m=change_over(closes, 21),
        change_3m=change_over(closes, 63),
        change_ytd=ytd_change(series),
        change_period=pct_change(last_close, closes[0]),
        high_52w=hi,
        low_52w=lo,
        pct_off_high=pct_change(last_close, hi),
        sma_20=sma(closes, 20),
        sma_50=s50,
        sma_200=s200,
        vol_annualized=annualized_vol(closes),
        max_drawdown=max_drawdown(closes),
        trend=classify(last_close, s50, s200),
        bars=len(closes),
    )
