"""Terminal and HTML rendering. No template engine, no JS libraries."""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone

SPARK = "▁▂▃▄▅▆▇█"


def sparkline(values, width: int = 40) -> str:
    """Unicode sparkline of the last `width` values."""
    vals = [v for v in values if v is not None][-width:]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    if hi == lo:
        return SPARK[0] * len(vals)
    span = hi - lo
    return "".join(SPARK[min(int((v - lo) / span * (len(SPARK) - 1)), len(SPARK) - 1)] for v in vals)


def fmt_pct(value, width: int = 8) -> str:
    if value is None:
        return "—".rjust(width)
    return f"{value * 100:+.2f}%".rjust(width)


def fmt_money(value, width: int = 12) -> str:
    if value is None:
        return "—".rjust(width)
    if abs(value) >= 1000:
        return f"{value:,.0f}".rjust(width)
    if abs(value) >= 1:
        return f"{value:,.2f}".rjust(width)
    return f"{value:,.4f}".rjust(width)


def render_terminal(rows, failures=None, color: bool = True) -> str:
    """Grouped console table with sparklines."""
    failures = failures or []
    out = []
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out.append(f"MARKET TRACKER — {stamp}")
    out.append("=" * 104)

    def paint(text: str, value) -> str:
        if not color or value is None:
            return text
        if value > 0:
            return f"\033[32m{text}\033[0m"
        if value < 0:
            return f"\033[31m{text}\033[0m"
        return text

    for group in dict.fromkeys(r["group"] for r in rows):
        out.append("")
        out.append(group.upper())
        out.append(
            f"  {'SYMBOL':<10}{'LAST':>12}{'1D':>9}{'5D':>9}{'1M':>9}{'YTD':>9}"
            f"{'OFF HI':>9}  {'TREND':<12}SPARK (90d)"
        )
        out.append("  " + "-" * 100)
        for r in [x for x in rows if x["group"] == group]:
            out.append(
                f"  {r['symbol']:<10}{fmt_money(r['last_close'])}"
                f"{paint(fmt_pct(r['change_1d'], 9), r['change_1d'])}"
                f"{paint(fmt_pct(r['change_5d'], 9), r['change_5d'])}"
                f"{paint(fmt_pct(r['change_1m'], 9), r['change_1m'])}"
                f"{paint(fmt_pct(r['change_ytd'], 9), r['change_ytd'])}"
                f"{fmt_pct(r['pct_off_high'], 9)}  {r['trend']:<12}{r.get('spark', '')}"
            )

    out.append("")
    if failures:
        out.append(f"FAILED ({len(failures)}):")
        for symbol, reason in failures:
            out.append(f"  {symbol:<10} {reason}")
        out.append("")
    out.append(f"{len(rows)} symbols tracked. Data: Yahoo Finance daily closes. Informational only.")
    return "\n".join(out)


def _svg_sparkline(values, width=150, height=34) -> str:
    vals = [v for v in values if v is not None][-120:]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    step = width / (len(vals) - 1)
    pts = " ".join(
        f"{i * step:.1f},{height - 2 - ((v - lo) / span) * (height - 4):.1f}"
        for i, v in enumerate(vals)
    )
    stroke = "#16a34a" if vals[-1] >= vals[0] else "#dc2626"
    return (
        f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'preserveAspectRatio="none"><polyline fill="none" stroke="{stroke}" '
        f'stroke-width="1.5" points="{pts}"/></svg>'
    )


def render_html(rows, failures=None, title="Market Tracker") -> str:
    """Self-contained static dashboard, safe to publish on GitHub Pages."""
    failures = failures or []
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    def cell(value):
        if value is None:
            return '<td class="num muted">—</td>'
        cls = "pos" if value > 0 else "neg" if value < 0 else ""
        return f'<td class="num {cls}">{value * 100:+.2f}%</td>'

    body = []
    for group in dict.fromkeys(r["group"] for r in rows):
        body.append(f'<tr class="group"><td colspan="9">{html.escape(group)}</td></tr>')
        for r in [x for x in rows if x["group"] == group]:
            body.append(
                "<tr>"
                f'<td class="sym"><strong>{html.escape(r["symbol"])}</strong>'
                f'<span class="name">{html.escape(r["label"])}</span></td>'
                f'<td class="num">{fmt_money(r["last_close"]).strip()}</td>'
                + cell(r["change_1d"]) + cell(r["change_5d"]) + cell(r["change_1m"])
                + cell(r["change_ytd"]) + cell(r["pct_off_high"])
                + f'<td class="trend t-{r["trend"].split()[0]}">{html.escape(r["trend"])}</td>'
                f'<td class="spark">{_svg_sparkline(r.get("series", []))}</td>'
                "</tr>"
            )

    fail_html = ""
    if failures:
        items = "".join(
            f"<li><code>{html.escape(s)}</code> — {html.escape(str(m))}</li>" for s, m in failures
        )
        fail_html = f'<div class="fails"><strong>Failed to fetch</strong><ul>{items}</ul></div>'

    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
:root {{ color-scheme: dark; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; padding:28px 18px; background:#0b0e14; color:#d4d8e2;
  font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace; }}
.wrap {{ max-width:1100px; margin:0 auto; }}
h1 {{ font-size:19px; margin:0 0 4px; letter-spacing:.14em; text-transform:uppercase; color:#f0f3f8; }}
.sub {{ color:#6b7488; font-size:12px; margin-bottom:22px; }}
table {{ width:100%; border-collapse:collapse; }}
th {{ text-align:right; font-size:10.5px; letter-spacing:.1em; text-transform:uppercase;
  color:#6b7488; padding:8px 10px; border-bottom:1px solid #222836; font-weight:600; }}
th:first-child, .sym {{ text-align:left; }}
td {{ padding:9px 10px; border-bottom:1px solid #161b26; white-space:nowrap; }}
tr:hover td {{ background:#111725; }}
.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
.pos {{ color:#3ddc84; }} .neg {{ color:#ff6b6b; }} .muted {{ color:#4a5163; }}
.name {{ display:block; color:#6b7488; font-size:11px; font-weight:400;
  max-width:190px; overflow:hidden; text-overflow:ellipsis; }}
.group td {{ background:#141a26; color:#8d97ad; font-size:10.5px; letter-spacing:.14em;
  text-transform:uppercase; padding:7px 10px; }}
.group:hover td {{ background:#141a26; }}
.trend {{ text-align:right; font-size:11.5px; color:#8d97ad; }}
.t-uptrend {{ color:#3ddc84; }} .t-downtrend {{ color:#ff6b6b; }}
.spark {{ text-align:right; width:160px; padding-right:0; }}
.fails {{ margin-top:22px; padding:12px 14px; background:#1d1410;
  border-left:3px solid #d97706; font-size:12px; }}
.fails ul {{ margin:6px 0 0; padding-left:18px; }}
footer {{ margin-top:26px; color:#4a5163; font-size:11px; line-height:1.7; }}
@media(max-width:760px) {{ .spark, .trend {{ display:none; }} body {{ padding:16px 8px; }} }}
</style></head>
<body><div class="wrap">
<h1>Market Tracker</h1>
<div class="sub">Generated {stamp} · {len(rows)} symbols · daily closes</div>
<table>
<thead><tr><th>Symbol</th><th>Last</th><th>1D</th><th>5D</th><th>1M</th><th>YTD</th>
<th>Off High</th><th>Trend</th><th>90d</th></tr></thead>
<tbody>{''.join(body)}</tbody>
</table>
{fail_html}
<footer>
Source: Yahoo Finance public chart endpoint. Prices are delayed daily closes and may be
revised or wrong.<br>
This dashboard is informational only — not investment advice, not a recommendation,
and not connected to any brokerage.
</footer>
</div></body></html>
"""


def render_json(rows, failures=None) -> str:
    return json.dumps(
        {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "count": len(rows),
            "rows": [{k: v for k, v in r.items() if k != "series"} for r in rows],
            "failures": [{"symbol": s, "error": str(m)} for s, m in (failures or [])],
        },
        indent=2,
    )
