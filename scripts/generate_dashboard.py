#!/usr/bin/env python3
"""Generate dashboard.html from per-ticker sentiment_summary.json + finviz_quote.json files."""
from __future__ import annotations

import argparse
import html as html_lib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PACIFIC_TZ = ZoneInfo("America/Los_Angeles")
MAX_HEADLINES = 10

_SENT_CLASS = {"bullish": "bull", "bearish": "bear", "neutral": "neut"}


# ── Shared helpers ────────────────────────────────────────────────────────────

def _cls(sentiment: str) -> str:
    return _SENT_CLASS.get(sentiment, "neut")


def _score_html(score: float | None, title: str = "") -> str:
    if score is None:
        return '<span class="missing">—</span>'
    sign = "+" if score >= 0 else ""
    c = "score-pos" if score > 0.1 else ("score-neg" if score < -0.1 else "score-neut")
    t = f' title="{html_lib.escape(title)}"' if title else ""
    return f'<span class="{c}"{t}>{sign}{score:.2f}</span>'


def _score_cell(score: float | None, title: str = "") -> str:
    """Colored <td> for a −1..+1 signal score, with optional hover tooltip."""
    if score is None:
        return f'<td class="missing" style="text-align:center">—</td>'
    sign = "+" if score >= 0 else ""
    sc = "bull" if score > 0.1 else ("bear" if score < -0.1 else "neut")
    t = f' title="{html_lib.escape(title)}"' if title else ""
    return f'<td class="{sc}" style="text-align:center"{t}>{sign}{score:.2f}</td>'


# ── Sentiment data loaders ────────────────────────────────────────────────────

def _load_summary(data_root: Path, ticker: str) -> dict | None:
    p = data_root / ticker / "sentiment_summary.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _load_today_headlines(data_root: Path, ticker: str, date: str) -> list[dict]:
    """Read sentiment_log.jsonl, keep today's records, return newest-first (up to MAX_HEADLINES)."""
    p = data_root / ticker / "sentiment_log.jsonl"
    if not p.exists():
        return []
    records = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
            if r.get("run_date") == date and not r.get("analysis_error"):
                records.append(r)
        except Exception:
            pass
    records.sort(key=lambda r: r.get("analyzed_at", ""), reverse=True)
    return records[:MAX_HEADLINES]


# ── Sparkline ─────────────────────────────────────────────────────────────────

def _sparkline_svg(by_date_entries: list[dict]) -> str:
    """Inline SVG line chart from all by_date entries, oldest → newest left → right."""
    entries = sorted(by_date_entries, key=lambda e: e.get("date", ""))
    if not entries:
        return '<span class="missing">—</span>'

    W, H, PAD = 130, 34, 4
    scores     = [e.get("score_avg", 0.0) for e in entries]
    sentiments = [e.get("sentiment", "neutral") for e in entries]
    n = len(scores)

    def fy(score: float) -> float:
        return H - PAD - ((score + 1) / 2) * (H - 2 * PAD)

    def fx(i: int) -> float:
        return float(PAD) if n == 1 else PAD + i * (W - 2 * PAD) / (n - 1)

    zero_y = fy(0.0)
    points  = [(fx(i), fy(s)) for i, s in enumerate(scores)]

    svg = (
        f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        f'style="display:block" xmlns="http://www.w3.org/2000/svg">'
        f'<line x1="{PAD}" y1="{zero_y:.1f}" x2="{W - PAD}" y2="{zero_y:.1f}" '
        f'stroke="#e5e7eb" stroke-width="1"/>'
    )
    if n > 1:
        pts = " ".join(f"{px:.1f},{py:.1f}" for px, py in points)
        svg += (
            f'<polyline points="{pts}" fill="none" stroke="#94a3b8" '
            f'stroke-width="1.5" stroke-linejoin="round"/>'
        )
    dot_fill = {"bullish": "#16a34a", "bearish": "#dc2626", "neutral": "#9ca3af"}
    r = 2.5 if n <= 14 else 1.5
    for i, (px, py) in enumerate(points):
        fill = dot_fill.get(sentiments[i], "#9ca3af")
        svg += f'<circle cx="{px:.1f}" cy="{py:.1f}" r="{r}" fill="{fill}"/>'
    svg += "</svg>"
    return svg


# ── Fundamental scoring ───────────────────────────────────────────────────────

def _v(snap: dict, key: str) -> float | None:
    """Parse a snapshot table value to float.
    Handles: '364.65', '-4.61%', '498.83 -19.98%' (takes last token), '-' → None.
    """
    raw = snap.get(key, "")
    if not raw or str(raw).strip() in ("-", ""):
        return None
    token = str(raw).strip().split()[-1]
    token = token.rstrip("%").replace(",", "")
    try:
        return float(token)
    except (ValueError, AttributeError):
        return None


def _clamp(v: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _score_momentum(snap: dict) -> tuple[float | None, str]:
    """Price vs SMAs — positive = price above moving average (bullish)."""
    results = []
    parts   = []
    for key, label, scale in [
        ("SMA20",  "SMA20",  10.0),  # ±10% from MA = full signal
        ("SMA50",  "SMA50",  10.0),
        ("SMA200", "SMA200", 15.0),
    ]:
        v = _v(snap, key)
        if v is not None:
            results.append(_clamp(v / scale))
            sign = "+" if v >= 0 else ""
            parts.append(f"{label} {sign}{v:.1f}%")
    if not results:
        return None, "—"
    return round(sum(results) / len(results), 3), " | ".join(parts)


def _score_52w(snap: dict) -> tuple[float | None, str]:
    """Position in 52W range. Near high → +1, near low → −1."""
    pct_below_high = _v(snap, "52W High")  # e.g. -19.98  (negative: below high)
    pct_above_low  = _v(snap, "52W Low")   # e.g. +38.22  (positive: above low)
    if pct_below_high is None or pct_above_low is None:
        return None, "—"
    below = abs(pct_below_high)
    above = pct_above_low
    total = above + below
    if total == 0:
        return 0.0, "at midpoint"
    position = above / total            # 0 = at 52W low, 1 = at 52W high
    score    = round(position * 2 - 1, 3)
    return score, (
        f"{position * 100:.0f}% of range "
        f"({pct_below_high:.1f}% from high, +{above:.1f}% from low)"
    )


def _score_analyst(snap: dict) -> tuple[float | None, str]:
    """Recom (1=Strong Buy → 5=Strong Sell) + target price upside."""
    recom  = _v(snap, "Recom")
    target = _v(snap, "Target Price")
    price  = _v(snap, "Price")
    parts, scores = [], []

    if recom is not None:
        s = _clamp((3 - recom) / 2)  # 1→+1, 3→0, 5→-1
        scores.append(s)
        parts.append(f"Recom {recom:.2f}")

    if target is not None and price and price > 0:
        upside = (target - price) / price * 100
        s = _clamp(upside / 25)       # ±25% upside = full signal
        scores.append(s)
        sign = "+" if upside >= 0 else ""
        parts.append(f"Target {sign}{upside:.1f}% upside (${target:.0f})")

    if not scores:
        return None, "—"
    return round(sum(scores) / len(scores), 3), " | ".join(parts)


def _score_short(snap: dict) -> tuple[float | None, str]:
    """Short float — higher short % = more bearish pressure."""
    sf = _v(snap, "Short Float")
    if sf is None:
        return None, "—"
    score = round(_clamp(-sf / 20), 3)   # 20%+ short = −1.0
    return score, f"{sf:.1f}% short float"


def _score_rsi(snap: dict) -> tuple[float | None, str]:
    """RSI — contrarian: oversold (<30) → bullish, overbought (>70) → bearish."""
    rsi = _v(snap, "RSI (14)")
    if rsi is None:
        return None, "—"
    score = round(_clamp((50 - rsi) / 20), 3)
    label = "oversold" if rsi < 30 else ("overbought" if rsi > 70 else "neutral")
    return score, f"RSI {rsi:.1f} ({label})"


def _score_earnings(snap: dict) -> tuple[float | None, str]:
    """Recent earnings momentum — EPS Q/Q and Sales Q/Q."""
    parts, scores = [], []
    for key, label, scale in [
        ("EPS Q/Q",   "EPS Q/Q",   30.0),
        ("Sales Q/Q", "Sales Q/Q", 20.0),
    ]:
        v = _v(snap, key)
        if v is not None:
            scores.append(_clamp(v / scale))
            sign = "+" if v >= 0 else ""
            parts.append(f"{label} {sign}{v:.1f}%")
    if not scores:
        return None, "—"
    return round(sum(scores) / len(scores), 3), " | ".join(parts)


def compute_fundamental(data_root: Path, ticker: str) -> dict | None:
    """Find the most recent finviz_quote.json for ticker and return scored signals."""
    ticker_dir = data_root / ticker
    if not ticker_dir.exists():
        return None

    quote_path = None
    for d in sorted(ticker_dir.iterdir(), reverse=True):
        c = d / "finviz_quote.json"
        if c.exists():
            quote_path = c
            break
    if not quote_path:
        return None

    try:
        quote = json.loads(quote_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    snap       = quote.get("snapshot_table", {})
    quote_date = quote_path.parent.name

    momentum_s, momentum_d   = _score_momentum(snap)
    range_s,    range_d      = _score_52w(snap)
    analyst_s,  analyst_d    = _score_analyst(snap)
    short_s,    short_d      = _score_short(snap)
    rsi_s,      rsi_d        = _score_rsi(snap)
    earnings_s, earnings_d   = _score_earnings(snap)

    valid = [s for s in [momentum_s, range_s, analyst_s, short_s, rsi_s, earnings_s]
             if s is not None]
    overall   = round(sum(valid) / len(valid), 3) if valid else None
    sentiment = (
        "bullish" if (overall is not None and overall > 0.1)
        else "bearish" if (overall is not None and overall < -0.1)
        else "neutral"
    )

    return {
        "quote_date": quote_date,
        "overall":    overall,
        "sentiment":  sentiment,
        "components": {
            "momentum":  {"score": momentum_s,  "detail": momentum_d},
            "52w_range": {"score": range_s,     "detail": range_d},
            "analyst":   {"score": analyst_s,   "detail": analyst_d},
            "short":     {"score": short_s,     "detail": short_d},
            "rsi":       {"score": rsi_s,       "detail": rsi_d},
            "earnings":  {"score": earnings_s,  "detail": earnings_d},
        },
        "key_stats": {
            "pe":          _v(snap, "P/E"),
            "forward_pe":  _v(snap, "Forward P/E"),
            "short_float": _v(snap, "Short Float"),
            "rsi":         _v(snap, "RSI (14)"),
            "recom":       _v(snap, "Recom"),
            "target":      _v(snap, "Target Price"),
            "price":       _v(snap, "Price"),
            "beta":        _v(snap, "Beta"),
            "market_cap":  snap.get("Market Cap", "—"),
        },
    }


# ── Dashboard assembly ────────────────────────────────────────────────────────

def generate(tickers: list[str], date: str, data_root: Path, output: Path) -> None:
    now = datetime.now(PACIFIC_TZ)
    h   = html_lib.escape

    # Load sentiment data
    summaries: dict[str, dict] = {}
    for t in tickers:
        s = _load_summary(data_root, t)
        if s:
            summaries[t] = s

    date_map:  dict[str, dict] = {}
    all_dates: set[str]        = set()
    for t, s in summaries.items():
        date_map[t] = {e["date"]: e for e in s.get("by_date", [])}
        all_dates.update(date_map[t])

    recent_dates = sorted(all_dates, reverse=True)[:7]

    # Load fundamental data
    fundamentals: dict[str, dict] = {}
    for t in tickers:
        f = compute_fundamental(data_root, t)
        if f:
            fundamentals[t] = f

    # ── Today's snapshot (news only) ──────────────────────────────────────────
    today_rows = ""
    for ticker in tickers:
        summary = summaries.get(ticker)
        if not summary:
            today_rows += (
                f"<tr><td><strong>{ticker}</strong></td>"
                f'<td colspan="3" class="missing">no data</td></tr>\n'
            )
            continue
        entry = date_map.get(ticker, {}).get(date)
        if entry:
            sent  = entry.get("sentiment", "neutral")
            score = entry.get("score_avg")
            count = entry.get("articles_analyzed", 0)
        else:
            sent, score, count = "neutral", None, 0
        sc = _cls(sent)
        today_rows += (
            f"<tr>"
            f"<td><strong>{ticker}</strong></td>"
            f'<td class="{sc}">{sent}</td>'
            f"<td>{_score_html(score)}</td>"
            f'<td style="text-align:center">{count or "—"}</td>'
            f"</tr>\n"
        )

    # ── Score-by-day trend table (news) ───────────────────────────────────────
    date_headers = "".join(f"<th>{d[5:]}</th>" for d in recent_dates)

    trend_rows = ""
    for ticker in tickers:
        summary = summaries.get(ticker)
        if not summary:
            trend_rows += (
                f"<tr><td><strong>{ticker}</strong></td>"
                f'<td colspan="{3 + len(recent_dates)}" class="missing">no data</td></tr>\n'
            )
            continue
        overall_sent  = summary.get("overall_sentiment", "neutral")
        overall_score = summary.get("overall_score_avg", 0.0)
        total         = summary.get("total_analyzed", 0)
        sign          = "+" if overall_score >= 0 else ""
        sc            = _cls(overall_sent)
        spark         = _sparkline_svg(summary.get("by_date", []))

        day_cells = ""
        dm = date_map.get(ticker, {})
        for d in recent_dates:
            e = dm.get(d)
            if e:
                s        = e.get("score_avg", 0.0)
                day_sign = "+" if s >= 0 else ""
                dc       = _cls(e.get("sentiment", "neutral"))
                day_cells += f'<td class="{dc}" style="text-align:center">{day_sign}{s:.2f}</td>'
            else:
                day_cells += '<td class="missing" style="text-align:center">—</td>'

        trend_rows += (
            f"<tr>"
            f"<td><strong>{ticker}</strong></td>"
            f'<td style="padding:0.2rem 0.6rem">{spark}</td>'
            f'<td class="{sc}">{overall_sent} {sign}{overall_score:.2f} ({total})</td>'
            f"{day_cells}"
            f"</tr>\n"
        )

    # ── Fundamental signals table ──────────────────────────────────────────────
    fund_rows = ""
    for ticker in tickers:
        f = fundamentals.get(ticker)
        if not f:
            fund_rows += (
                f"<tr><td><strong>{ticker}</strong></td>"
                f'<td colspan="11" class="missing">no quote data</td></tr>\n'
            )
            continue

        c   = f["components"]
        ks  = f["key_stats"]
        sc  = _cls(f["sentiment"])
        overall_sign = "+" if (f["overall"] or 0) >= 0 else ""

        def stat(val, fmt=".1f", suffix=""):
            return f"{val:{fmt}}{suffix}" if val is not None else "—"

        def recom_label(r):
            if r is None: return "—"
            if r <= 1.5:  return f"{r:.2f} StrongBuy"
            if r <= 2.5:  return f"{r:.2f} Buy"
            if r <= 3.5:  return f"{r:.2f} Hold"
            if r <= 4.5:  return f"{r:.2f} Sell"
            return f"{r:.2f} StrongSell"

        fund_rows += (
            f"<tr>"
            f"<td><strong>{ticker}</strong>"
            f'<br><span class="meta-inline">{f["quote_date"]}</span></td>'
            # Overall fundamental score
            + _score_cell(f["overall"], f["sentiment"])
            # Component scores (with hover tooltip showing detail)
            + _score_cell(c["momentum"]["score"],  c["momentum"]["detail"])
            + _score_cell(c["52w_range"]["score"], c["52w_range"]["detail"])
            + _score_cell(c["analyst"]["score"],   c["analyst"]["detail"])
            + _score_cell(c["short"]["score"],     c["short"]["detail"])
            + _score_cell(c["rsi"]["score"],       c["rsi"]["detail"])
            + _score_cell(c["earnings"]["score"],  c["earnings"]["detail"])
            # Raw key stats
            + f'<td style="text-align:right">{stat(ks["pe"])}</td>'
            + f'<td style="text-align:right">{stat(ks["forward_pe"])}</td>'
            + f'<td style="text-align:right">{stat(ks["beta"])}</td>'
            + f'<td style="text-align:right">{recom_label(ks["recom"])}</td>'
            + f"</tr>\n"
        )

    # ── Today's headlines per ticker ──────────────────────────────────────────
    headlines_html = ""
    for ticker in tickers:
        summary  = summaries.get(ticker)
        entry    = date_map.get(ticker, {}).get(date)
        articles = _load_today_headlines(data_root, ticker, date)
        if not summary:
            continue

        overall_sent  = summary.get("overall_sentiment", "neutral")
        overall_score = summary.get("overall_score_avg", 0.0)
        overall_sign  = "+" if overall_score >= 0 else ""
        sc            = _cls(overall_sent)

        if entry:
            today_sent  = entry.get("sentiment", "neutral")
            today_score = entry.get("score_avg", 0.0)
            today_sign  = "+" if today_score >= 0 else ""
            today_count = entry.get("articles_analyzed", 0)
            sc_today    = _cls(today_sent)
            subtitle    = (
                f'Today: <span class="{sc_today}">{today_sent} {today_sign}{today_score:.2f}</span>'
                f" &middot; {today_count} articles"
            )
        else:
            subtitle = '<span class="missing">no articles today</span>'

        ticker_label = (
            f'<span class="{sc}">{overall_sent} {overall_sign}{overall_score:.2f} all-time</span>'
        )
        headlines_html += (
            f"<h3><strong>{ticker}</strong> &nbsp; {ticker_label}"
            f' &nbsp;<span class="meta-inline">{subtitle}</span></h3>\n'
        )

        if not articles:
            headlines_html += '<p class="missing" style="margin:0 0 1.5rem">No articles analyzed today.</p>\n'
            continue

        rows = ""
        for r in articles:
            score        = r.get("score")
            sent         = r.get("sentiment", "neutral")
            sc2          = _cls(sent)
            headline     = h((r.get("headline") or "")[:120])
            publisher    = h(r.get("publisher") or "")
            summary_text = h(r.get("summary") or "")
            pub_tag      = f'<span class="pub">{publisher}</span>' if publisher else ""
            rows += (
                f"<tr>"
                f'<td class="{sc2}" style="text-align:center;white-space:nowrap">{_score_html(score)}</td>'
                f"<td>{headline} {pub_tag}</td>"
                f'<td class="summary-cell">{summary_text}</td>'
                f"</tr>\n"
            )
        headlines_html += (
            f"<table>\n"
            f"  <thead><tr><th>Score</th><th>Headline</th><th>Market implication</th></tr></thead>\n"
            f"  <tbody>\n{rows}  </tbody>\n</table>\n\n"
        )

    # ── Assemble final HTML ───────────────────────────────────────────────────
    ts = now.strftime("%Y-%m-%d %H:%M PT")
    n  = len([t for t in tickers if t in summaries])

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>finzwiz Dashboard &mdash; {date}</title>
<style>
  body  {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          max-width: 1400px; margin: 2rem auto; padding: 0 1rem; color: #111; }}
  h1   {{ font-size: 1.35rem; margin: 0; }}
  h2   {{ font-size: 0.85rem; color: #6b7280; margin: 2.2rem 0 0.5rem;
          border-bottom: 1px solid #e5e7eb; padding-bottom: 0.3rem;
          text-transform: uppercase; letter-spacing: 0.06em; }}
  h3   {{ font-size: 1rem; margin: 1.8rem 0 0.4rem; }}
  .meta        {{ color: #9ca3af; font-size: 0.8rem; margin: 0.2rem 0 1.5rem; }}
  .meta-inline {{ color: #9ca3af; font-size: 0.8rem; font-weight: normal; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 0.86rem; margin-bottom: 0.25rem; }}
  th, td {{ padding: 0.38rem 0.75rem; text-align: left; border: 1px solid #e5e7eb; }}
  th   {{ background: #f9fafb; font-weight: 600; white-space: nowrap; }}
  tr:hover td {{ background-color: #fafafa; }}
  .bull {{ background: #dcfce7; color: #15803d; font-weight: 600; }}
  .bear {{ background: #fee2e2; color: #b91c1c; font-weight: 600; }}
  .neut {{ background: #f3f4f6; color: #6b7280; }}
  .score-pos  {{ color: #15803d; font-weight: 600; }}
  .score-neg  {{ color: #b91c1c; font-weight: 600; }}
  .score-neut {{ color: #6b7280; }}
  .missing {{ color: #d1d5db; }}
  .pub {{ color: #9ca3af; font-size: 0.78rem; }}
  .summary-cell {{ color: #4b5563; font-size: 0.82rem; max-width: 480px; }}
  .section-note {{ color: #9ca3af; font-size: 0.78rem; margin: 0.1rem 0 0.6rem; }}
</style>
</head>
<body>

<h1>finzwiz Dashboard &mdash; {date}</h1>
<p class="meta">Generated {ts} &nbsp;&middot;&nbsp; {n} of {len(tickers)} tickers with data</p>

<h2>News &mdash; Today&rsquo;s Snapshot</h2>
<table>
  <thead><tr><th>Ticker</th><th>Sentiment</th><th>Score</th><th>Articles</th></tr></thead>
  <tbody>
{today_rows}  </tbody>
</table>

<h2>News &mdash; Score by Day (newest &rarr; oldest)</h2>
<table>
  <thead><tr>
    <th>Ticker</th><th>Trend (all history)</th><th>All-time</th>{date_headers}
  </tr></thead>
  <tbody>
{trend_rows}  </tbody>
</table>

<h2>Fundamentals &mdash; Signal Scores</h2>
<p class="section-note">Each signal −1.0 (bearish) to +1.0 (bullish). Hover a cell to see the underlying values.</p>
<table>
  <thead><tr>
    <th>Ticker</th>
    <th title="Equal-weighted average of all signals">Overall</th>
    <th title="Price vs SMA20 / SMA50 / SMA200">Momentum</th>
    <th title="Price position in 52-week high/low range">52W Range</th>
    <th title="Analyst consensus (Recom 1-5) + target price upside">Analyst</th>
    <th title="Short float % — higher short = more bearish pressure">Short</th>
    <th title="RSI(14) — contrarian: oversold = bullish, overbought = bearish">RSI</th>
    <th title="Recent earnings: EPS Q/Q and Sales Q/Q growth">Earnings</th>
    <th>P/E</th>
    <th>Fwd P/E</th>
    <th>Beta</th>
    <th>Analyst Recom</th>
  </tr></thead>
  <tbody>
{fund_rows}  </tbody>
</table>

<h2>News &mdash; Today&rsquo;s Headlines (latest first, up to {MAX_HEADLINES} per ticker)</h2>
{headlines_html}
</body>
</html>"""

    output.write_text(page, encoding="utf-8")
    print(f"dashboard written → {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers",  required=True, help="Space-separated ticker list")
    parser.add_argument("--date",     required=True, help="Today's date YYYY-MM-DD")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--output",   default="dashboard.html")
    args = parser.parse_args()

    generate(
        tickers=args.tickers.split(),
        date=args.date,
        data_root=Path(args.data_dir),
        output=Path(args.output),
    )


if __name__ == "__main__":
    main()
