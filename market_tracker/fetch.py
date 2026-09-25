"""Fetch daily OHLCV bars from the public Yahoo Finance chart endpoint.

Stdlib only, no API key. Failures are raised per symbol so one bad ticker
never kills a whole run.
"""
from __future__ import annotations

import gzip
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
USER_AGENT = "Mozilla/5.0 (compatible; market-tracker/0.1)"


class FetchError(RuntimeError):
    """Raised when a symbol could not be fetched or parsed."""


@dataclass
class Bar:
    date: str  # ISO date of the exchange-local trading day
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass
class Quote:
    symbol: str
    name: str
    currency: str
    exchange: str
    bars: list

    @property
    def last(self) -> Bar:
        return self.bars[-1]


def _http_get_json(url: str, timeout: float = 20.0) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def fetch_symbol(symbol, range_="1y", interval="1d", retries=3, timeout=20.0) -> Quote:
    """Fetch one symbol's bars. Retries transient network errors with backoff."""
    url = "{}?range={}&interval={}".format(
        CHART_URL.format(symbol=urllib.parse.quote(symbol)), range_, interval
    )
    last_err = None
    for attempt in range(retries):
        try:
            return _parse(symbol, _http_get_json(url, timeout=timeout))
        except FetchError:
            raise  # a real data problem: retrying will not help
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            last_err = exc
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
    raise FetchError(f"{symbol}: network failure after {retries} attempts ({last_err})")


def _parse(symbol: str, payload: dict) -> Quote:
    chart = payload.get("chart") or {}
    if chart.get("error"):
        err = chart["error"]
        raise FetchError(f"{symbol}: {err.get('description', err)}")
    results = chart.get("result") or []
    if not results:
        raise FetchError(f"{symbol}: empty response")

    res = results[0]
    meta = res.get("meta", {})
    stamps = res.get("timestamp") or []
    quote = (res.get("indicators", {}).get("quote") or [{}])[0]
    offset = meta.get("gmtoffset", 0) or 0

    bars = []
    for i, ts in enumerate(stamps):
        close = _at(quote.get("close"), i)
        if close is None:
            continue  # holiday or partial bar
        bars.append(
            Bar(
                date=time.strftime("%Y-%m-%d", time.gmtime(ts + offset)),
                open=_num(_at(quote.get("open"), i), close),
                high=_num(_at(quote.get("high"), i), close),
                low=_num(_at(quote.get("low"), i), close),
                close=float(close),
                volume=int(_at(quote.get("volume"), i) or 0),
            )
        )
    if not bars:
        raise FetchError(f"{symbol}: no usable bars in response")

    return Quote(
        symbol=meta.get("symbol", symbol),
        name=meta.get("longName") or meta.get("shortName") or symbol,
        currency=meta.get("currency") or "",
        exchange=meta.get("fullExchangeName") or meta.get("exchangeName") or "",
        bars=bars,
    )


def _at(seq, i):
    if not seq or i >= len(seq):
        return None
    return seq[i]


def _num(value, fallback):
    return float(value) if value is not None else float(fallback)
