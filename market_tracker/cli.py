"""Command line entry point.

    python -m market_tracker update      fetch + store + print table
    python -m market_tracker show        render from the local DB, no network
    python -m market_tracker export      write docs/index.html and data/latest.json
    python -m market_tracker add TICKER  append a symbol to the watchlist
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import __version__, analytics, render, store
from .config import DEFAULT_DB, DEFAULT_HTML, DEFAULT_WATCHLIST, load_watchlist
from .fetch import FetchError, fetch_symbol


def _rows_from_db(conn, tickers, spark_days=90):
    """Build render rows for every watchlist symbol that has stored bars."""
    rows, missing = [], []
    for t in tickers:
        series = store.load_closes(conn, t.symbol)
        if not series:
            missing.append((t.symbol, "no stored data — run `update` first"))
            continue
        meta = conn.execute(
            "SELECT name, currency FROM symbols WHERE symbol = ?", (t.symbol,)
        ).fetchone()
        m = analytics.compute(
            t.symbol, t.label, t.group, (meta["currency"] if meta else ""), series
        )
        row = m.to_dict()
        closes = [c for _, c in series]
        row["series"] = closes[-spark_days:]
        row["spark"] = render.sparkline(closes[-spark_days:])
        rows.append(row)
    return rows, missing


def cmd_update(args) -> int:
    tickers = load_watchlist(args.watchlist)
    conn = store.connect(args.db)
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    failures = []
    ok = 0

    for t in tickers:
        try:
            quote = fetch_symbol(t.symbol, range_=args.range)
            store.upsert_quote(conn, quote, group=t.group, label=t.label)
            ok += 1
            if not args.quiet:
                print(f"  ok   {t.symbol:<12} {len(quote.bars):>4} bars  last {quote.last.date}",
                      file=sys.stderr)
        except FetchError as exc:
            failures.append((t.symbol, str(exc)))
            print(f"  FAIL {t.symbol:<12} {exc}", file=sys.stderr)

    store.record_run(conn, started, ok, len(failures))
    conn.commit()

    if ok == 0:
        print("every symbol failed — check network connectivity", file=sys.stderr)
        return 2

    rows, missing = _rows_from_db(conn, tickers)
    print(render.render_terminal(rows, failures + missing, color=not args.no_color))
    if args.export:
        _export(rows, failures + missing, args)
    conn.close()
    return 1 if failures else 0


def cmd_show(args) -> int:
    tickers = load_watchlist(args.watchlist)
    conn = store.connect(args.db)
    rows, missing = _rows_from_db(conn, tickers)
    if not rows:
        print("no data stored yet — run: python -m market_tracker update", file=sys.stderr)
        return 2
    if args.json:
        print(render.render_json(rows, missing))
    else:
        print(render.render_terminal(rows, missing, color=not args.no_color))
    conn.close()
    return 0


def cmd_export(args) -> int:
    tickers = load_watchlist(args.watchlist)
    conn = store.connect(args.db)
    rows, missing = _rows_from_db(conn, tickers)
    if not rows:
        print("nothing to export — run `update` first", file=sys.stderr)
        return 2
    _export(rows, missing, args)
    conn.close()
    return 0


def _export(rows, failures, args) -> None:
    html_path = Path(args.html)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(render.render_html(rows, failures), encoding="utf-8")

    json_path = Path(args.db).parent / "latest.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(render.render_json(rows, failures), encoding="utf-8")
    print(f"wrote {html_path} and {json_path}", file=sys.stderr)


def cmd_add(args) -> int:
    path = Path(args.watchlist)
    data = json.loads(path.read_text(encoding="utf-8"))
    group = args.group
    data.setdefault("groups", {}).setdefault(group, [])
    existing = {
        (i if isinstance(i, str) else i["symbol"]).upper()
        for items in data["groups"].values()
        for i in items
    }
    if args.symbol.upper() in existing:
        print(f"{args.symbol} is already in the watchlist", file=sys.stderr)
        return 1
    data["groups"][group].append({"symbol": args.symbol, "label": args.label or args.symbol})
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"added {args.symbol} to group '{group}'")
    return 0


def _global_flags(suppress: bool = False) -> argparse.ArgumentParser:
    """Flags shared by the root parser and every subcommand.

    Attaching them in both places is what lets `update --db X` and
    `--db X update` both work; argparse before 3.10 will not accept a
    root-level flag positioned after the subcommand otherwise.

    The subcommand copies use ``SUPPRESS`` defaults so that an omitted flag
    leaves the root parser's value alone instead of overwriting it.
    """
    def d(value):
        return argparse.SUPPRESS if suppress else value

    g = argparse.ArgumentParser(add_help=False)
    g.add_argument("--watchlist", default=d(str(DEFAULT_WATCHLIST)), help="path to watchlist.json")
    g.add_argument("--db", default=d(str(DEFAULT_DB)), help="path to the SQLite database")
    g.add_argument("--html", default=d(str(DEFAULT_HTML)), help="path for the exported dashboard")
    g.add_argument("--no-color", action="store_true", default=d(False), help="disable ANSI colour")
    return g


def build_parser() -> argparse.ArgumentParser:
    root_flags = _global_flags()
    sub_flags = _global_flags(suppress=True)
    p = argparse.ArgumentParser(prog="market-tracker", description=__doc__,
                                parents=[root_flags],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"market-tracker {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    u = sub.add_parser("update", parents=[sub_flags], help="fetch latest bars, store, and print")
    u.add_argument("--range", default="1y", help="history window (1mo, 6mo, 1y, 2y, 5y)")
    u.add_argument("--export", action="store_true", help="also write HTML/JSON")
    u.add_argument("--quiet", action="store_true", help="suppress per-symbol progress")
    u.set_defaults(func=cmd_update)

    s = sub.add_parser("show", parents=[sub_flags], help="render from local DB without fetching")
    s.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    s.set_defaults(func=cmd_show)

    e = sub.add_parser("export", parents=[sub_flags],
                       help="write docs/index.html + data/latest.json")
    e.set_defaults(func=cmd_export)

    a = sub.add_parser("add", parents=[sub_flags], help="add a symbol to the watchlist")
    a.add_argument("symbol")
    a.add_argument("--label", default=None)
    a.add_argument("--group", default="Watchlist")
    a.set_defaults(func=cmd_add)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as exc:
        print(f"file not found: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
