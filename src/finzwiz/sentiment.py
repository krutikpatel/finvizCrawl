from __future__ import annotations

import json
import os
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import anthropic

from .config import ConfigError, load_config
from .storage import read_jsonl, write_json_atomic, write_jsonl_atomic

PACIFIC_TZ = ZoneInfo("America/Los_Angeles")


class SentimentLog:
    """Tracks which article_ids have already been analyzed, backed by a JSONL file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._records: list[dict[str, Any]] = []
        self._analyzed_ids: set[str] = set()
        self._load()

    def _load(self) -> None:
        for row in read_jsonl(self.path):
            aid = row.get("article_id")
            if aid:
                self._analyzed_ids.add(aid)
                self._records.append(row)

    def is_analyzed(self, article_id: str) -> bool:
        return article_id in self._analyzed_ids

    def add(self, record: dict[str, Any]) -> None:
        aid = record.get("article_id")
        if aid:
            self._analyzed_ids.add(aid)
        self._records.append(record)

    def flush(self) -> None:
        write_jsonl_atomic(self.path, self._records)

    @property
    def all_records(self) -> list[dict[str, Any]]:
        return list(self._records)


def run_sentiment(*, ticker: str, config_path: str, run_date: str | None) -> int:
    ticker = ticker.upper().strip()

    try:
        config = load_config(config_path)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ANTHROPIC_API_KEY environment variable is not set", file=sys.stderr)
        return 2

    now = datetime.now(PACIFIC_TZ)
    date_str = run_date or now.date().isoformat()

    data_root = Path(config.output.data_dir)
    articles_dir = data_root / ticker / date_str / "articles"
    news_path = data_root / ticker / date_str / "finviz_news.json"
    log_path = data_root / ticker / config.sentiment.log_filename
    summary_path = data_root / ticker / config.sentiment.summary_filename

    if not articles_dir.exists():
        print(
            f"No articles directory for {ticker} on {date_str} — run 'finzwiz scrape' first",
            file=sys.stderr,
        )
        return 10

    # Build headline/publisher/url lookup from finviz_news.json
    headline_map: dict[str, str] = {}
    publisher_map: dict[str, str] = {}
    url_map: dict[str, str] = {}
    if news_path.exists():
        with news_path.open("r", encoding="utf-8") as fh:
            news_data = json.load(fh)
        for item in news_data.get("items", []):
            aid = item.get("article_id")
            if aid:
                headline_map[aid] = item.get("headline") or ""
                publisher_map[aid] = item.get("publisher") or ""
                url_map[aid] = item.get("url") or ""

    log = SentimentLog(log_path)

    # Separate already-done from new
    already_done = 0
    to_analyze: list[dict[str, Any]] = []
    for article_path in sorted(articles_dir.glob("*.json")):
        aid = article_path.stem
        if log.is_analyzed(aid):
            already_done += 1
            continue
        with article_path.open("r", encoding="utf-8") as fh:
            article_data = json.load(fh)
        text = (article_data.get("content") or {}).get("text") or ""
        if not text:
            continue
        to_analyze.append({
            "article_id": aid,
            "headline": headline_map.get(aid, ""),
            "publisher": publisher_map.get(aid, ""),
            "url": url_map.get(aid, (article_data.get("source") or {}).get("url", "")),
            "text": text,
        })

    if not to_analyze:
        print(f"{ticker} {date_str}: 0 new articles to analyze ({already_done} already done)")
        _write_summary(summary_path, ticker, config, log)
        return 0

    client = anthropic.Anthropic(api_key=api_key)
    analyzed_ok = 0
    analyzed_failed = 0
    batch_size = config.sentiment.max_articles_per_batch

    for i in range(0, len(to_analyze), batch_size):
        batch = to_analyze[i : i + batch_size]
        results = _analyze_batch(client, ticker, batch, config.sentiment.model)
        analyzed_at = datetime.now(PACIFIC_TZ).isoformat()
        for article in batch:
            aid = article["article_id"]
            result = results.get(aid, {})
            has_error = bool(result.get("error"))
            log.add({
                "article_id": aid,
                "ticker": ticker,
                "run_date": date_str,
                "analyzed_at": analyzed_at,
                "headline": article["headline"],
                "publisher": article["publisher"],
                "url": article["url"],
                "sentiment": result.get("sentiment", "neutral"),
                "score": result.get("score", 0.0),
                "summary": result.get("summary", ""),
                "analysis_error": result.get("error"),
            })
            if has_error:
                analyzed_failed += 1
            else:
                analyzed_ok += 1

    log.flush()
    _write_summary(summary_path, ticker, config, log)

    print(
        f"{ticker} {date_str}: {analyzed_ok} analyzed, "
        f"{analyzed_failed} failed, {already_done} skipped (already done)"
    )
    return 0


def _analyze_batch(
    client: anthropic.Anthropic,
    ticker: str,
    articles: list[dict[str, Any]],
    model: str,
) -> dict[str, dict[str, Any]]:
    articles_block = ""
    for a in articles:
        articles_block += (
            f"\n---\n"
            f"ARTICLE_ID: {a['article_id']}\n"
            f"HEADLINE: {a['headline']}\n"
            f"PUBLISHER: {a['publisher']}\n\n"
            f"{a['text'][:3000]}\n"
        )

    prompt = (
        f"You are a financial analyst. Analyze the sentiment of the following news articles about {ticker}.\n\n"
        "For each article return a JSON object with exactly these fields:\n"
        '- "article_id": the ARTICLE_ID string (copy exactly as given)\n'
        '- "sentiment": one of "bullish", "bearish", or "neutral"\n'
        '- "score": float from -1.0 (very bearish) to 1.0 (very bullish)\n'
        '- "summary": one sentence on the key point and its market implication\n\n'
        "Return a JSON array with one object per article. Output only the JSON array, no prose.\n\n"
        f"ARTICLES:{articles_block}"
    )

    try:
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        # Strip markdown code fences if model wraps output
        if raw.startswith("```"):
            lines = raw.split("\n")
            end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
            raw = "\n".join(lines[1:end])
        parsed: list[dict[str, Any]] = json.loads(raw)
        return {item["article_id"]: item for item in parsed if "article_id" in item}
    except Exception as exc:
        return {a["article_id"]: {"error": str(exc)} for a in articles}


def _write_summary(
    summary_path: Path,
    ticker: str,
    config: Any,
    log: SentimentLog,
) -> None:
    records = [r for r in log.all_records if not r.get("analysis_error")]

    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        by_date[r.get("run_date", "unknown")].append(r)

    date_rows = []
    all_scores: list[float] = []
    for date in sorted(by_date.keys(), reverse=True):
        day_records = by_date[date]
        scores = [r["score"] for r in day_records if isinstance(r.get("score"), (int, float))]
        avg = round(statistics.mean(scores), 3) if scores else 0.0
        all_scores.extend(scores)
        counts = Counter(r.get("sentiment", "neutral") for r in day_records)
        dominant = counts.most_common(1)[0][0]
        top = sorted(day_records, key=lambda x: abs(x.get("score") or 0), reverse=True)[:5]
        date_rows.append({
            "date": date,
            "articles_analyzed": len(day_records),
            "sentiment": dominant,
            "score_avg": avg,
            "top_headlines": [
                {
                    "headline": r.get("headline", ""),
                    "sentiment": r.get("sentiment", "neutral"),
                    "score": r.get("score", 0.0),
                    "summary": r.get("summary", ""),
                }
                for r in top
            ],
        })

    overall_avg = round(statistics.mean(all_scores), 3) if all_scores else 0.0
    if overall_avg > 0.1:
        overall_sentiment = "bullish"
    elif overall_avg < -0.1:
        overall_sentiment = "bearish"
    else:
        overall_sentiment = "neutral"

    write_json_atomic(
        summary_path,
        {
            "schema_version": config.project.schema_version,
            "ticker": ticker,
            "generated_at": datetime.now(PACIFIC_TZ).isoformat(),
            "total_analyzed": len(records),
            "overall_sentiment": overall_sentiment,
            "overall_score_avg": overall_avg,
            "by_date": date_rows,
        },
        pretty=config.output.pretty_json,
    )
