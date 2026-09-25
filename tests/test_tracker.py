"""Offline tests: no network, no real database files outside tmp."""
from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from market_tracker import analytics, render, store  # noqa: E402
from market_tracker.config import load_watchlist  # noqa: E402
from market_tracker.fetch import Bar, FetchError, Quote, _parse  # noqa: E402


def make_series(closes, start_day=1, year="2026"):
    return [(f"{year}-01-{start_day + i:02d}", c) for i, c in enumerate(closes)]


class TestAnalytics(unittest.TestCase):
    def test_pct_change(self):
        self.assertAlmostEqual(analytics.pct_change(110, 100), 0.10)
        self.assertAlmostEqual(analytics.pct_change(90, 100), -0.10)

    def test_pct_change_guards_zero_and_none(self):
        self.assertIsNone(analytics.pct_change(110, 0))
        self.assertIsNone(analytics.pct_change(110, None))
        self.assertIsNone(analytics.pct_change(None, 100))

    def test_change_over_needs_enough_history(self):
        self.assertIsNone(analytics.change_over([100.0, 101.0], 5))
        self.assertAlmostEqual(analytics.change_over([100.0, 110.0], 1), 0.10)

    def test_sma(self):
        self.assertEqual(analytics.sma([1, 2, 3, 4], 2), 3.5)
        self.assertIsNone(analytics.sma([1, 2], 5))

    def test_max_drawdown(self):
        # 100 -> 50 is a 50% peak-to-trough decline
        self.assertAlmostEqual(analytics.max_drawdown([100, 120, 60, 80]), -0.5)
        self.assertAlmostEqual(analytics.max_drawdown([100, 110, 120]), 0.0)
        self.assertIsNone(analytics.max_drawdown([100]))

    def test_annualized_vol_requires_observations(self):
        self.assertIsNone(analytics.annualized_vol([100.0] * 10))
        noisy = [100 + (i % 7) * 3 for i in range(80)]
        self.assertGreater(analytics.annualized_vol(noisy), 0)

    def test_flat_series_has_zero_vol(self):
        self.assertAlmostEqual(analytics.annualized_vol([100.0] * 60), 0.0)

    def test_ytd_uses_prior_year_close(self):
        series = [("2025-12-31", 100.0), ("2026-01-02", 110.0)]
        self.assertAlmostEqual(analytics.ytd_change(series), 0.10)

    def test_ytd_none_without_prior_year(self):
        self.assertIsNone(analytics.ytd_change(make_series([100.0, 105.0])))

    def test_classify_trend(self):
        self.assertEqual(analytics.classify(110, 105, 100), "uptrend")
        self.assertEqual(analytics.classify(90, 95, 100), "downtrend")
        self.assertEqual(analytics.classify(110, 95, 100), "mixed")
        self.assertEqual(analytics.classify(110, None, None), "insufficient history")

    def test_compute_end_to_end(self):
        series = make_series([100.0, 102.0, 101.0, 105.0])
        m = analytics.compute("TEST", "Test Co", "Equities", "USD", series)
        self.assertEqual(m.symbol, "TEST")
        self.assertEqual(m.last_close, 105.0)
        self.assertEqual(m.bars, 4)
        self.assertAlmostEqual(m.change_1d, 105.0 / 101.0 - 1)
        self.assertAlmostEqual(m.change_period, 0.05)
        self.assertEqual(m.high_52w, 105.0)
        self.assertEqual(m.low_52w, 100.0)
        self.assertAlmostEqual(m.pct_off_high, 0.0)

    def test_compute_rejects_empty(self):
        with self.assertRaises(ValueError):
            analytics.compute("X", "X", "G", "USD", [])


class TestStore(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.db = Path(self.tmp.name) / "t.db"

    def tearDown(self):
        self.tmp.cleanup()

    def _quote(self, closes, start=1):
        bars = [
            Bar(date=f"2026-01-{start + i:02d}", open=c, high=c, low=c, close=c, volume=10)
            for i, c in enumerate(closes)
        ]
        return Quote("TEST", "Test Co", "USD", "NYSE", bars)

    def test_roundtrip(self):
        conn = store.connect(self.db)
        store.upsert_quote(conn, self._quote([10.0, 11.0]), group="Equities")
        conn.commit()
        self.assertEqual(store.load_closes(conn, "TEST"), [("2026-01-01", 10.0), ("2026-01-02", 11.0)])
        self.assertEqual(store.load_symbols(conn)[0]["grp"], "Equities")

    def test_upsert_is_idempotent_and_accumulates(self):
        conn = store.connect(self.db)
        store.upsert_quote(conn, self._quote([10.0, 11.0]))
        store.upsert_quote(conn, self._quote([10.0, 11.0]))  # same window again
        store.upsert_quote(conn, self._quote([12.0], start=3))  # new day
        conn.commit()
        self.assertEqual(len(store.load_closes(conn, "TEST")), 3)

    def test_revised_close_overwrites(self):
        conn = store.connect(self.db)
        store.upsert_quote(conn, self._quote([10.0]))
        store.upsert_quote(conn, self._quote([99.0]))
        conn.commit()
        self.assertEqual(store.load_closes(conn, "TEST"), [("2026-01-01", 99.0)])

    def test_closes_ordered_oldest_first_under_limit(self):
        conn = store.connect(self.db)
        store.upsert_quote(conn, self._quote([float(i) for i in range(1, 11)]))
        conn.commit()
        got = store.load_closes(conn, "TEST", limit=3)
        self.assertEqual([c for _, c in got], [8.0, 9.0, 10.0])

    def test_record_run(self):
        conn = store.connect(self.db)
        store.record_run(conn, "2026-01-01T00:00:00+00:00", 5, 1, "test")
        conn.commit()
        self.assertEqual(conn.execute("SELECT ok_count FROM runs").fetchone()[0], 5)


class TestFetchParsing(unittest.TestCase):
    def payload(self, closes, stamps=None):
        stamps = stamps or [1767225600 + i * 86400 for i in range(len(closes))]
        return {
            "chart": {
                "result": [{
                    "meta": {"symbol": "TEST", "longName": "Test Co", "currency": "USD",
                             "exchangeName": "NMS", "gmtoffset": 0},
                    "timestamp": stamps,
                    "indicators": {"quote": [{
                        "open": closes, "high": closes, "low": closes,
                        "close": closes, "volume": [100] * len(closes),
                    }]},
                }]
            }
        }

    def test_parses_bars(self):
        q = _parse("TEST", self.payload([10.0, 11.0]))
        self.assertEqual(q.name, "Test Co")
        self.assertEqual(len(q.bars), 2)
        self.assertEqual(q.last.close, 11.0)

    def test_skips_null_closes(self):
        q = _parse("TEST", self.payload([10.0, None, 12.0]))
        self.assertEqual([b.close for b in q.bars], [10.0, 12.0])

    def test_null_ohlc_falls_back_to_close(self):
        p = self.payload([10.0])
        p["chart"]["result"][0]["indicators"]["quote"][0]["open"] = [None]
        q = _parse("TEST", p)
        self.assertEqual(q.bars[0].open, 10.0)

    def test_api_error_raises(self):
        bad = {"chart": {"error": {"description": "No data found"}, "result": None}}
        with self.assertRaises(FetchError):
            _parse("BOGUS", bad)

    def test_empty_result_raises(self):
        with self.assertRaises(FetchError):
            _parse("X", {"chart": {"result": []}})

    def test_all_null_closes_raises(self):
        with self.assertRaises(FetchError):
            _parse("X", self.payload([None, None]))


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.path = Path(self.tmp.name) / "w.json"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, obj):
        self.path.write_text(json.dumps(obj), encoding="utf-8")
        return self.path

    def test_groups_and_strings(self):
        p = self.write({"groups": {"Equities": ["AAPL", {"symbol": "VOO", "label": "S&P"}]}})
        t = load_watchlist(p)
        self.assertEqual([x.symbol for x in t], ["AAPL", "VOO"])
        self.assertEqual(t[0].label, "AAPL")
        self.assertEqual(t[1].label, "S&P")
        self.assertEqual(t[1].group, "Equities")

    def test_flat_tickers(self):
        self.assertEqual(len(load_watchlist(self.write({"tickers": ["AAPL", "MSFT"]}))), 2)

    def test_dedupes_case_insensitively(self):
        p = self.write({"groups": {"A": ["AAPL"], "B": ["aapl"]}})
        self.assertEqual(len(load_watchlist(p)), 1)

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            load_watchlist(self.write({"groups": {}}))

    def test_shipped_watchlist_is_valid(self):
        shipped = Path(__file__).resolve().parent.parent / "watchlist.json"
        self.assertGreater(len(load_watchlist(shipped)), 10)


class TestRender(unittest.TestCase):
    def rows(self):
        series = make_series([100.0, 101.0, 99.0, 105.0])
        m = analytics.compute("TEST", "Test Co", "Equities", "USD", series).to_dict()
        m["series"] = [c for _, c in series]
        m["spark"] = render.sparkline(m["series"])
        return [m]

    def test_sparkline(self):
        s = render.sparkline([1, 2, 3, 4])
        self.assertEqual(len(s), 4)
        self.assertEqual(s[0], "▁")
        self.assertEqual(s[-1], "█")

    def test_sparkline_flat_and_short(self):
        self.assertEqual(render.sparkline([5, 5, 5]), "▁▁▁")
        self.assertEqual(render.sparkline([1]), "")

    def test_fmt_pct_and_money(self):
        self.assertEqual(render.fmt_pct(0.0512, 0), "+5.12%")
        self.assertEqual(render.fmt_pct(None, 0), "—")
        self.assertEqual(render.fmt_money(1234.5, 0), "1,234")
        self.assertEqual(render.fmt_money(0.0521, 0), "0.0521")

    def test_terminal_output(self):
        out = render.render_terminal(self.rows(), color=False)
        self.assertIn("TEST", out)
        self.assertIn("EQUITIES", out)
        self.assertIn("1 symbols tracked", out)

    def test_terminal_lists_failures(self):
        out = render.render_terminal(self.rows(), [("BAD", "nope")], color=False)
        self.assertIn("FAILED (1)", out)
        self.assertIn("BAD", out)

    def test_html_is_wellformed_and_escapes(self):
        rows = self.rows()
        rows[0]["label"] = "<script>alert(1)</script>"
        out = render.render_html(rows)
        self.assertTrue(out.startswith("<!DOCTYPE html>"))
        self.assertIn("</html>", out)
        self.assertNotIn("<script>alert(1)</script>", out)
        self.assertIn("&lt;script&gt;", out)
        self.assertIn("<svg", out)

    def test_json_export_drops_series(self):
        payload = json.loads(render.render_json(self.rows(), [("BAD", "nope")]))
        self.assertEqual(payload["count"], 1)
        self.assertNotIn("series", payload["rows"][0])
        self.assertEqual(payload["failures"][0]["symbol"], "BAD")


class TestCLIParsing(unittest.TestCase):
    """Argparse wiring. Global flags must work before AND after the subcommand
    on every supported Python (pre-3.10 argparse does not do this for free)."""

    def setUp(self):
        from market_tracker.cli import build_parser
        self.parser = build_parser()

    def test_flag_after_subcommand(self):
        for argv in (
            ["show", "--no-color"],
            ["show", "--db", "/tmp/x.db"],
            ["update", "--watchlist", "/tmp/w.json"],
            ["export", "--html", "/tmp/out.html"],
            ["add", "TSLA", "--group", "Equities"],
        ):
            with self.subTest(argv=argv):
                self.assertIsNotNone(self.parser.parse_args(argv).func)

    def test_flag_before_subcommand(self):
        args = self.parser.parse_args(["--no-color", "show"])
        self.assertTrue(args.no_color)

    def test_subcommand_required(self):
        with self.assertRaises(SystemExit):
            self.parser.parse_args([])

    def test_defaults_and_specifics(self):
        args = self.parser.parse_args(["update", "--range", "5y", "--export"])
        self.assertEqual(args.range, "5y")
        self.assertTrue(args.export)
        self.assertFalse(args.quiet)

    def test_add_defaults_to_watchlist_group(self):
        self.assertEqual(self.parser.parse_args(["add", "TSLA"]).group, "Watchlist")


class TestCLICommands(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        d = Path(self.tmp.name)
        self.db = d / "t.db"
        self.wl = d / "w.json"
        self.wl.write_text(json.dumps({"groups": {"Equities": ["TEST"]}}), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, argv):
        from market_tracker.cli import main
        buf_out, buf_err = io.StringIO(), io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            return main(argv)

    def test_show_without_data_exits_nonzero(self):
        code = self.run_cli(["show", "--db", str(self.db), "--watchlist", str(self.wl)])
        self.assertEqual(code, 2)

    def test_add_then_load(self):
        code = self.run_cli(["add", "MSFT", "--watchlist", str(self.wl), "--group", "Equities"])
        self.assertEqual(code, 0)
        self.assertEqual([t.symbol for t in load_watchlist(self.wl)], ["TEST", "MSFT"])

    def test_add_duplicate_is_rejected(self):
        self.assertEqual(self.run_cli(["add", "TEST", "--watchlist", str(self.wl)]), 1)

    def test_missing_watchlist_exits_cleanly(self):
        code = self.run_cli(["show", "--watchlist", str(Path(self.tmp.name) / "nope.json")])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
