# Market Tracker

A dependency-free market watchlist tracker. It pulls daily closes for stocks,
ETFs, indices, crypto, FX and futures, stores them in SQLite, and renders both a
terminal table and a static HTML dashboard.

No API keys. No `pip install`. Python 3.9+ standard library only.

```
MARKET TRACKER — 2026-09-25 23:06 UTC
========================================================================

INDEX & BROAD MARKET
  SYMBOL            LAST       1D       5D       1M      YTD   OFF HI  TREND
  ^GSPC            7,743   +0.51%   +1.21%   +0.88%  +13.12%   -0.71%  uptrend     ▁▃▆▆▅▇▆▆▆█▇▆▅▅▄▅▄▅▅▆
  ^IXIC           27,069   +0.48%   +2.06%   +3.59%  +16.46%   -0.64%  uptrend     ▁▃▅▄▄▅▅▅▅▆▆▅▄▄▃▄▃▃▃▅
  ^VIX             14.87   -5.11%   +0.41%   +2.48%   -0.54%  -52.11%  downtrend   ▄▅▄▂▂▃▃▁▁▁▂▄▂▄▂▄▃▂▁▁
```

## Why it exists

Most trackers either want an API key, a paid data plan, or a `requirements.txt`
thirty lines long. This one is a single package you can drop on any machine with
Python and run immediately, and the database it builds is yours.

## Quick start

```bash
git clone https://github.com/willriley88/market-tracker.git
cd market-tracker

python3 -m market_tracker update            # fetch, store, print
python3 -m market_tracker update --export   # also write the HTML dashboard
open docs/index.html
```

## Commands

| Command | What it does |
|---|---|
| `update` | Fetch the latest bars, store them, print the table |
| `show` | Re-render from the local database — no network |
| `show --json` | Machine-readable output for piping elsewhere |
| `export` | Write `docs/index.html` and `data/latest.json` |
| `add SYMBOL` | Append a ticker to the watchlist |

Useful flags:

```bash
python3 -m market_tracker update --range 5y     # deeper history (1mo/6mo/1y/2y/5y)
python3 -m market_tracker update --export --quiet
python3 -m market_tracker show --no-color
python3 -m market_tracker add TSLA --label Tesla --group Equities
python3 -m market_tracker --db /tmp/other.db show
```

## Watchlist

`watchlist.json` drives everything. Groups become table sections:

```json
{
  "groups": {
    "Equities": ["AAPL", {"symbol": "MU", "label": "Micron Technology"}],
    "Crypto":   ["BTC-USD", "ETH-USD"]
  }
}
```

Any Yahoo Finance symbol works, which covers more than just US equities:

- Indices — `^GSPC`, `^IXIC`, `^VIX`, `^TNX`
- Crypto — `BTC-USD`, `ETH-USD`
- FX — `EURUSD=X`, `DX-Y.NYB`
- Futures — `GC=F` (gold), `CL=F` (WTI crude)
- International — `SAP.DE`, `7203.T`, `SHOP.TO`

The shipped default tracks 24 symbols across five groups.

## What it computes

Per symbol: last close, 1D / 5D / 1M / 3M / YTD / full-period change, 52-week
high and low, percent off the high, 20/50/200-day SMAs, annualized volatility
from daily returns, maximum drawdown, and a blunt trend label
(`uptrend` when price > SMA50 > SMA200, `downtrend` when inverted, else `mixed`).

YTD is measured from the last close of the previous calendar year — it returns
nothing rather than guessing when that bar isn't in the history window.

## Storage

Bars land in `data/market.db`, keyed by `(symbol, date)` and upserted. Each run
only requests a trailing window, but the database keeps everything it has ever
seen, so history accumulates the longer you run it. Revised closes overwrite
cleanly. Every run is logged to a `runs` table.

```sql
sqlite3 data/market.db "SELECT symbol, date, close FROM bars
                        WHERE symbol='AAPL' ORDER BY date DESC LIMIT 5;"
```

## Automating it

The included workflow (`.github/workflows/update.yml`) runs on weekdays after
the US close, commits the refreshed data, and publishes the dashboard to GitHub
Pages. Enable it under *Settings → Pages → Source: GitHub Actions*.

Locally, cron works just as well:

```cron
30 17 * * 1-5 cd ~/projects/market-tracker && python3 -m market_tracker update --export --quiet
```

## Tests

```bash
python3 -m unittest discover -s tests -v
```

35 tests, fully offline — parsing is checked against fixture payloads, so the
suite never touches the network and never flakes on market hours.

## Layout

```
market_tracker/
  config.py      watchlist loading
  fetch.py       HTTP + response parsing
  store.py       SQLite schema and upserts
  analytics.py   pure return/vol/drawdown math
  render.py      terminal, HTML and JSON output
  cli.py         argparse entry point
tests/           offline unit tests
watchlist.json   what to track
docs/index.html  generated dashboard
data/market.db   generated database
```

Each layer is independent: `analytics` never imports `fetch`, `render` never
touches the database. That is what makes the test suite offline.

## Caveats

Data comes from Yahoo Finance's public chart endpoint — undocumented, unofficial,
rate-limited, and occasionally wrong. Symbols that fail are reported and skipped;
the rest of the run continues. Prices are delayed daily closes, not real time.

**This is informational tooling, not investment advice.** It is read-only by
design: no brokerage connection, no credentials, no orders, ever.

## License

MIT
