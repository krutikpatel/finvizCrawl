#!/usr/bin/env python3
"""
Select the top N articles from a day's scrape for the stock monitor news scan.

Ranking (three-tier):
  1. Catalyst keywords in headline (always surface first)
  2. Highest abs(score) from sentiment_log.jsonl (conviction signal)
  3. Original Finviz news order (recency tiebreak — Finviz lists newest first)

Output: formatted text block ready to embed in a Claude prompt.
"""

import argparse
import json
from pathlib import Path

CATALYST_KEYWORDS = [
    "earnings", "guidance", "upgrade", "downgrade", "price target",
    "buy rating", "sell rating", "hold rating", "outperform", "underperform",
    "initiates", "raises", "lowers", "cuts", "beat", "miss",
    "acquire", "acquisition", "merger", "takeover",
    "fda", "sec", "ceo", "cfo", "recall", "lawsuit", "settlement",
    "revenue", "eps", "quarterly", "forecast", "outlook",
    "reaffirm", "withdraw", "raise guidance", "lower guidance",
    "job cuts", "layoff", "restructur",
]


def has_catalyst(headline: str) -> bool:
    h = headline.lower()
    return any(kw in h for kw in CATALYST_KEYWORDS)


def main():
    parser = argparse.ArgumentParser(description="Pick top N articles for monitor prompt")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--data-dir", required=True, help="Path to data/ directory")
    parser.add_argument("--n", type=int, default=5, help="Number of articles to return")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    ticker = args.ticker
    date = args.date

    # ── Load today's sentiment scores ─────────────────────────────────────────
    scores: dict = {}  # article_id -> record
    log_path = data_dir / ticker / "sentiment_log.jsonl"
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if rec.get("run_date") == date:
                    scores[rec["article_id"]] = rec
            except Exception:
                pass

    # ── Load news metadata (all items Finviz listed, in order) ────────────────
    news_path = data_dir / ticker / date / "finviz_news.json"
    news_order: list = []   # preserves Finviz order for recency tiebreak
    news_meta: dict = {}    # article_id -> {headline, publisher, url}
    if news_path.exists():
        for item in json.loads(news_path.read_text(encoding="utf-8")).get("items", []):
            aid = item.get("article_id")
            if aid:
                news_order.append(aid)
                news_meta[aid] = {
                    "headline": item.get("headline", ""),
                    "publisher": item.get("publisher", ""),
                    "url": item.get("url", ""),
                }

    # ── Load article text excerpts ─────────────────────────────────────────────
    article_texts: dict = {}  # article_id -> text (truncated, printable only)
    articles_dir = data_dir / ticker / date / "articles"
    if articles_dir.exists():
        for f in articles_dir.glob("*.json"):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                text = (d.get("content") or {}).get("text") or ""
                # Skip garbled/binary content:
                #   - any Unicode replacement character (U+FFFD) = failed decode
                #   - fewer than 70% ASCII-printable bytes = binary data
                if text and "�" not in text[:200]:
                    sample = text[:200]
                    ascii_ok = sum(1 for c in sample if 32 <= ord(c) <= 126 or c in "\n\t\r")
                    if ascii_ok / len(sample) >= 0.70:
                        article_texts[f.stem] = text[:1000]
            except Exception:
                pass

    # ── Build candidate pool (union of scored + all news items) ───────────────
    seen: set = set()
    candidates: list = []

    # Scored articles first (have conviction data)
    for aid, rec in scores.items():
        seen.add(aid)
        meta = news_meta.get(aid, {})
        finviz_pos = news_order.index(aid) if aid in news_order else 999
        candidates.append({
            "article_id": aid,
            "headline": rec.get("headline") or meta.get("headline", ""),
            "publisher": rec.get("publisher") or meta.get("publisher", ""),
            "url": rec.get("url") or meta.get("url", ""),
            "sentiment": rec.get("sentiment", "neutral"),
            "score": float(rec.get("score", 0.0)),
            "summary": rec.get("summary", ""),
            "text": article_texts.get(aid, ""),
            "catalyst": has_catalyst(rec.get("headline") or meta.get("headline", "")),
            "finviz_pos": finviz_pos,
        })

    # Unscored news items (workflow didn't run yet, or article fetch failed)
    for aid in news_order:
        if aid in seen:
            continue
        meta = news_meta[aid]
        candidates.append({
            "article_id": aid,
            "headline": meta["headline"],
            "publisher": meta["publisher"],
            "url": meta["url"],
            "sentiment": None,
            "score": 0.0,
            "summary": "",
            "text": article_texts.get(aid, ""),
            "catalyst": has_catalyst(meta["headline"]),
            "finviz_pos": news_order.index(aid),
        })

    if not candidates:
        print("No articles available for this ticker/date.")
        return

    # ── Rank: catalyst first, then abs(score) desc, then Finviz order ─────────
    candidates.sort(key=lambda x: (
        not x["catalyst"],       # catalyst=True sorts first
        -abs(x["score"]),        # higher abs score first
        x["finviz_pos"],         # earlier in Finviz listing first
    ))

    top = candidates[: args.n]

    # ── Format as readable text for prompt embedding ───────────────────────────
    lines = []
    for i, c in enumerate(top, 1):
        tag = " [CATALYST]" if c["catalyst"] else ""
        lines.append(f"Article {i} of {len(top)}{tag}")
        lines.append(f"Headline : {c['headline']}")
        lines.append(f"Publisher: {c['publisher']}")
        lines.append(f"URL      : {c['url']}")
        if c["sentiment"] is not None:
            score_sign = f"+{c['score']:.2f}" if c["score"] >= 0 else f"{c['score']:.2f}"
            lines.append(f"Sentiment: {c['sentiment']} ({score_sign})")
            if c["summary"]:
                lines.append(f"Summary  : {c['summary']}")
        if c["text"]:
            lines.append(f"Excerpt  : {c['text'][:500]}")
        lines.append("")

    print("\n".join(lines).rstrip())


if __name__ == "__main__":
    main()
