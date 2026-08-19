#!/usr/bin/env python3
"""Generate dashboard.html from sentiment, quote, and monitor report data."""
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


def _load_scraped_news_count(data_root: Path, ticker: str, date: str) -> int:
    news_file = data_root / ticker / date / "finviz_news.json"
    if not news_file.exists():
        return 0
    try:
        payload = json.loads(news_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    return len(payload.get("items", [])) if isinstance(payload, dict) else 0


def _load_monitor_entry(reports_root: Path, ticker: str, date: str) -> dict | None:
    """Read the structured LEDGER_ENTRY embedded in today's monitor report."""
    report = reports_root / ticker / "daily" / f"{date}.md"
    if not report.exists():
        return None
    text = report.read_text(encoding="utf-8")
    marker = "```json LEDGER_ENTRY"
    start = text.find(marker)
    if start < 0:
        return None
    start += len(marker)
    end = text.find("```", start)
    if end < 0:
        return None
    try:
        entry = json.loads(text[start:end].strip())
    except json.JSONDecodeError:
        return None
    return entry if isinstance(entry, dict) else None


def _verdict_class(verdict: str) -> str:
    value = verdict.lower()
    if any(word in value for word in ("buy", "accumulate")):
        return "bull"
    if any(word in value for word in ("sell", "trim", "avoid")):
        return "bear"
    return "neut"


def _monitor_score(sentiment: object) -> float | None:
    if not isinstance(sentiment, (int, float)):
        return None
    return round(max(-1.0, min(1.0, (float(sentiment) - 3.0) / 2.0)), 3)


def _score_sentiment(score: float | None) -> str:
    if score is None:
        return "neutral"
    if score > 0.1:
        return "bullish"
    if score < -0.1:
        return "bearish"
    return "neutral"


def _action_zone(entry: dict) -> str:
    price = entry.get("price")
    zones = entry.get("action_zones") or {}
    if not isinstance(price, (int, float)):
        return "—"
    accumulate = zones.get("accumulate_range")
    hold = zones.get("hold_range")
    if isinstance(accumulate, list) and len(accumulate) == 2 and price <= accumulate[1]:
        return "Accumulate"
    if isinstance(hold, list) and len(hold) == 2 and price <= hold[1]:
        return "Hold"
    if price >= zones.get("avoid_above", float("inf")):
        return "Avoid"
    if price >= zones.get("trim_above", float("inf")):
        return "Trim"
    return "—"


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


def compute_monitor_fundamental(entry: dict) -> dict:
    """Build the fundamentals row from the monitor's structured daily entry."""
    momentum_scores = []
    momentum_parts = []
    for key, label in (("vs_sma20", "SMA20"), ("vs_sma50", "SMA50"), ("vs_sma200", "SMA200")):
        value = entry.get(key)
        if value == "above":
            momentum_scores.append(1.0)
            momentum_parts.append(f"{label} above")
        elif value == "below":
            momentum_scores.append(-1.0)
            momentum_parts.append(f"{label} below")
    momentum_s = round(sum(momentum_scores) / len(momentum_scores), 3) if momentum_scores else None
    momentum_d = " | ".join(momentum_parts) if momentum_parts else "—"

    range_s = None
    range_d = "—"
    below_high = entry.get("pct_from_w52_high")
    above_low = entry.get("pct_from_w52_low")
    if isinstance(below_high, (int, float)) and isinstance(above_low, (int, float)):
        total = abs(below_high) + above_low
        if total:
            position = above_low / total
            range_s = round(position * 2 - 1, 3)
            range_d = f"{position * 100:.0f}% of range"

    analyst_map = {"strong buy": 1.0, "buy": 0.7, "hold": 0.0, "sell": -0.7, "strong sell": -1.0}
    analyst_value = str(entry.get("analyst_consensus") or "").lower()
    analyst_s = analyst_map.get(analyst_value)
    analyst_d = entry.get("analyst_consensus") or "—"
    recom_map = {"strong buy": 1.0, "buy": 2.0, "hold": 3.0, "sell": 4.0, "strong sell": 5.0}
    target = entry.get("target_price")
    price = entry.get("price")
    if isinstance(target, (int, float)) and isinstance(price, (int, float)) and price > 0:
        upside = (target - price) / price * 100
        target_s = _clamp(upside / 25)
        analyst_s = target_s if analyst_s is None else round((analyst_s + target_s) / 2, 3)
        analyst_d = f"{analyst_d}; target {upside:+.1f}%"

    short_float = entry.get("short_float_pct")
    short_s = round(_clamp(-short_float / 20), 3) if isinstance(short_float, (int, float)) else None
    short_d = f"{short_float:.1f}% short float" if isinstance(short_float, (int, float)) else "—"

    rsi = entry.get("rsi")
    rsi_s = round(_clamp((50 - rsi) / 20), 3) if isinstance(rsi, (int, float)) else None
    rsi_d = f"RSI {rsi:.1f}" if isinstance(rsi, (int, float)) else "—"

    earnings_scores = []
    earnings_parts = []
    for key, label, scale in (("eps_growth_yoy", "EPS growth", 30.0), ("revenue_growth_yoy", "Revenue growth", 20.0)):
        value = entry.get(key)
        if isinstance(value, (int, float)):
            earnings_scores.append(_clamp(value / scale))
            earnings_parts.append(f"{label} {value:+.1f}%")
    earnings_s = round(sum(earnings_scores) / len(earnings_scores), 3) if earnings_scores else None
    earnings_d = " | ".join(earnings_parts) if earnings_parts else "—"

    component_scores = [momentum_s, range_s, analyst_s, short_s, rsi_s, earnings_s]
    valid = [score for score in component_scores if score is not None]
    overall = round(sum(valid) / len(valid), 3) if valid else None
    return {
        "quote_date": entry.get("date", "—"),
        "overall": overall,
        "sentiment": _score_sentiment(overall),
        "components": {
            "momentum": {"score": momentum_s, "detail": momentum_d},
            "52w_range": {"score": range_s, "detail": range_d},
            "analyst": {"score": analyst_s, "detail": analyst_d},
            "short": {"score": short_s, "detail": short_d},
            "rsi": {"score": rsi_s, "detail": rsi_d},
            "earnings": {"score": earnings_s, "detail": earnings_d},
        },
        "key_stats": {
            "pe": entry.get("pe"),
            "forward_pe": entry.get("fwd_pe"),
            "short_float": short_float,
            "rsi": rsi,
            "recom": recom_map.get(analyst_value),
            "target": target,
            "price": price,
            "beta": entry.get("beta"),
        },
    }


# ── Dashboard assembly ────────────────────────────────────────────────────────

def generate(
    tickers: list[str],
    date: str,
    data_root: Path,
    output: Path,
    reports_root: Path,
) -> None:
    now = datetime.now(PACIFIC_TZ)
    h   = html_lib.escape

    # Load sentiment data
    summaries: dict[str, dict] = {}
    for t in tickers:
        s = _load_summary(data_root, t)
        if s:
            summaries[t] = s

    monitor_entries = {
        t: entry
        for t in tickers
        if (entry := _load_monitor_entry(reports_root, t, date)) is not None
    }

    date_map:  dict[str, dict] = {}
    all_dates: set[str]        = set()
    for t, s in summaries.items():
        date_map[t] = {e["date"]: e for e in s.get("by_date", [])}
        all_dates.update(date_map[t])

    # Monitor sentiment is the current-day fallback when article sentiment is
    # disabled or has not been rebuilt yet. It is mapped from 1-5 to -1..+1.
    for ticker, monitor_entry in monitor_entries.items():
        monitor_score = _monitor_score(monitor_entry.get("sentiment"))
        date_map.setdefault(ticker, {})
        if date not in date_map[ticker]:
            date_map[ticker][date] = {
                "date": date,
                "sentiment": _score_sentiment(monitor_score),
                "score_avg": monitor_score,
                "articles_analyzed": _load_scraped_news_count(data_root, ticker, date),
                "source": "monitor",
                "monitor_sentiment": monitor_entry.get("sentiment"),
            }
            all_dates.add(date)

    recent_dates = sorted(all_dates, reverse=True)[:7]

    # Load fundamental data
    fundamentals: dict[str, dict] = {}
    for t in tickers:
        f = compute_monitor_fundamental(monitor_entries[t]) if t in monitor_entries else compute_fundamental(data_root, t)
        if f:
            fundamentals[t] = f

    # ── Today's snapshot (news only) ──────────────────────────────────────────
    today_rows = ""
    for ticker in tickers:
        summary = summaries.get(ticker)
        entry = date_map.get(ticker, {}).get(date)
        if not summary and not entry:
            today_rows += (
                f"<tr><td><strong>{ticker}</strong></td>"
                f'<td colspan="3" class="missing">no data</td></tr>\n'
            )
            continue
        if entry:
            sent  = entry.get("sentiment", "neutral")
            score = entry.get("score_avg")
            count = entry.get("articles_analyzed", 0)
        else:
            sent, score, count = "neutral", None, 0
        sc = _cls(sent)
        source = " monitor" if entry and entry.get("source") == "monitor" else ""
        today_rows += (
            f"<tr>"
            f"<td><strong>{ticker}</strong></td>"
            f'<td class="{sc}">{sent}{source}</td>'
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

    # ── Today's monitor reports ──────────────────────────────────────────────
    monitor_rows = ""
    for ticker in tickers:
        entry = monitor_entries.get(ticker)
        if not entry:
            continue
        verdict = str(entry.get("verdict") or "—")
        sentiment = entry.get("sentiment")
        sentiment_text = f"{sentiment}/5" if sentiment is not None else "—"
        price = entry.get("price")
        price_text = f"${price:,.2f}" if isinstance(price, (int, float)) else "—"
        report_href = f"monitor/reports/{ticker}/daily/{date}.md"
        monitor_rows += (
            f"<tr>"
            f"<td><strong>{ticker}</strong></td>"
            f'<td class="{_verdict_class(verdict)}">{h(verdict)}</td>'
            f'<td style="text-align:center">{h(sentiment_text)}</td>'
            f'<td style="text-align:right">{price_text}</td>'
            f"<td>{h(_action_zone(entry))}</td>"
            f'<td><a href="{report_href}">Open report</a></td>'
            f"</tr>\n"
        )
    if not monitor_rows:
        monitor_rows = '<tr><td colspan="6" class="missing">No monitor reports generated today.</td></tr>\n'

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
            if entry.get("source") == "monitor":
                monitor_sentiment = entry.get("monitor_sentiment", "—")
                subtitle = (
                    f'Monitor: <span class="{sc_today}">{today_sent} {today_sign}{today_score:.2f}</span>'
                    f" ({monitor_sentiment}/5) &middot; {today_count} scraped articles"
                )
            else:
                subtitle = (
                    f'Today: <span class="{sc_today}">{today_sent} {today_sign}{today_score:.2f}</span>'
                    f" &middot; {today_count} analyzed articles"
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
  a {{ color: #2563eb; }}
  .section-note {{ color: #9ca3af; font-size: 0.78rem; margin: 0.1rem 0 0.6rem; }}
</style>
</head>
<body>

<h1>finzwiz Dashboard &mdash; {date}</h1>
<p class="meta">Generated {ts} &nbsp;&middot;&nbsp; {n} of {len(tickers)} tickers with data</p>

<h2>News &mdash; Today&rsquo;s Snapshot</h2>
<p class="section-note">Uses article sentiment when available; otherwise falls back to today&rsquo;s monitor sentiment and scraped article count.</p>
<table>
  <thead><tr><th>Ticker</th><th>Sentiment</th><th>Score</th><th>Articles</th></tr></thead>
  <tbody>
{today_rows}  </tbody>
</table>

<h2>News &mdash; Score by Day (newest &rarr; oldest)</h2>
<p class="section-note">Today&rsquo;s monitor sentiment is mapped from 1&ndash;5 to the dashboard&rsquo;s −1.0 to +1.0 scale when article sentiment is unavailable.</p>
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

<h2>Monitor &mdash; Today&rsquo;s Reports</h2>
<p class="section-note">Daily monitor verdicts generated from the latest structured report entries.</p>
<table>
  <thead><tr><th>Ticker</th><th>Verdict</th><th>Sentiment</th><th>Price</th><th>Zone</th><th>Report</th></tr></thead>
  <tbody>
{monitor_rows}  </tbody>
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
    parser.add_argument("--reports-dir", default="monitor/reports")
    parser.add_argument("--output",   default="dashboard.html")
    args = parser.parse_args()

    generate(
        tickers=args.tickers.split(),
        date=args.date,
        data_root=Path(args.data_dir),
        output=Path(args.output),
        reports_root=Path(args.reports_dir),
    )


if __name__ == "__main__":
    main()
