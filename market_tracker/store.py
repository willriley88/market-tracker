"""SQLite persistence for bars and run history.

History accumulates: every run upserts bars keyed by (symbol, date), so the
database becomes a growing local record even though each fetch only asks for
a trailing window.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS symbols (
    symbol    TEXT PRIMARY KEY,
    name      TEXT,
    currency  TEXT,
    exchange  TEXT,
    grp       TEXT,
    label     TEXT
);

CREATE TABLE IF NOT EXISTS bars (
    symbol  TEXT NOT NULL,
    date    TEXT NOT NULL,
    open    REAL,
    high    REAL,
    low     REAL,
    close   REAL NOT NULL,
    volume  INTEGER,
    PRIMARY KEY (symbol, date)
);

CREATE INDEX IF NOT EXISTS idx_bars_symbol_date ON bars(symbol, date);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,
    ok_count    INTEGER NOT NULL,
    fail_count  INTEGER NOT NULL,
    notes       TEXT
);
"""


def connect(db_path) -> sqlite3.Connection:
    """Open (creating if needed) the tracker database."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def upsert_quote(conn: sqlite3.Connection, quote, group="Other", label=None) -> int:
    """Insert or update a symbol and all of its bars. Returns bars written."""
    conn.execute(
        """INSERT INTO symbols (symbol, name, currency, exchange, grp, label)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(symbol) DO UPDATE SET
             name=excluded.name, currency=excluded.currency,
             exchange=excluded.exchange, grp=excluded.grp, label=excluded.label""",
        (quote.symbol, quote.name, quote.currency, quote.exchange, group, label or quote.symbol),
    )
    rows = [
        (quote.symbol, b.date, b.open, b.high, b.low, b.close, b.volume)
        for b in quote.bars
    ]
    conn.executemany(
        """INSERT INTO bars (symbol, date, open, high, low, close, volume)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(symbol, date) DO UPDATE SET
             open=excluded.open, high=excluded.high, low=excluded.low,
             close=excluded.close, volume=excluded.volume""",
        rows,
    )
    return len(rows)


def record_run(conn: sqlite3.Connection, started_at: str, ok: int, fail: int, notes: str = "") -> None:
    conn.execute(
        "INSERT INTO runs (started_at, ok_count, fail_count, notes) VALUES (?, ?, ?, ?)",
        (started_at, ok, fail, notes),
    )


def load_closes(conn: sqlite3.Connection, symbol: str, limit: int = 400):
    """Return [(date, close)] oldest-first for the most recent `limit` days."""
    cur = conn.execute(
        "SELECT date, close FROM bars WHERE symbol = ? ORDER BY date DESC LIMIT ?",
        (symbol, limit),
    )
    return [(r["date"], r["close"]) for r in cur.fetchall()][::-1]


def load_symbols(conn: sqlite3.Connection):
    cur = conn.execute("SELECT * FROM symbols ORDER BY grp, symbol")
    return [dict(r) for r in cur.fetchall()]
