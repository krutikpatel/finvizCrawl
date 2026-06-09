#!/usr/bin/env bash
# Daily finzwiz workflow: scrape → sentiment analysis → git commit.
# Tickers: space-separated in FINZWIZ_TICKERS env var, default TSLA.
# Logs: logs/workflow-YYYY-MM-DD.log

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PYTHON="$PROJECT_DIR/.venv/bin/python"
CLAUDE=/opt/homebrew/bin/claude
TICKERS="${FINZWIZ_TICKERS:-TSLA}"
DATE="$(TZ='America/Los_Angeles' date +%Y-%m-%d)"
TIME="$(TZ='America/Los_Angeles' date '+%H:%M')"

mkdir -p "$PROJECT_DIR/logs"
LOG="$PROJECT_DIR/logs/workflow-$DATE.log"

log() { echo "[$(TZ='America/Los_Angeles' date '+%Y-%m-%d %H:%M:%S PT')] $*" | tee -a "$LOG"; }

log "=== finzwiz workflow start | tickers: $TICKERS ==="

# Accumulate per-ticker summary lines for the commit message
COMMIT_LINES=""
ANYTHING_STAGED=false

for TICKER in $TICKERS; do
    # ── Scrape ───────────────────────────────────────────────────────────────
    log "[$TICKER] scraping..."
    cd "$PROJECT_DIR"
    if PYTHONPATH=src "$PYTHON" -m finzwiz.cli scrape --ticker "$TICKER" >> "$LOG" 2>&1; then
        log "[$TICKER] scrape OK"
    else
        log "[$TICKER] scrape FAILED — skipping analysis and commit for this ticker"
        COMMIT_LINES="$COMMIT_LINES  $(printf '%-6s' "$TICKER")  scrape failed\n"
        continue
    fi

    # Stage this ticker's scrape outputs (surgical — only this ticker/date)
    git -C "$PROJECT_DIR" add \
        "data/$TICKER/$DATE/" \
        "data/$TICKER/seen_urls.jsonl" \
        2>/dev/null || true
    ANYTHING_STAGED=true

    # ── Sentiment analysis via Claude Code ───────────────────────────────────
    ARTICLES_DIR="$PROJECT_DIR/data/$TICKER/$DATE/articles"
    if [ ! -d "$ARTICLES_DIR" ] || [ -z "$(ls -A "$ARTICLES_DIR" 2>/dev/null)" ]; then
        log "[$TICKER] no articles found, skipping analysis"
        COMMIT_LINES="$COMMIT_LINES  $(printf '%-6s' "$TICKER")  scraped (no articles)\n"
        continue
    fi

    log "[$TICKER] analyzing sentiment..."
    PROMPT="Analyze stock sentiment for $TICKER from today's ($DATE) scraped news articles.

Working directory: $PROJECT_DIR
Articles:      data/$TICKER/$DATE/articles/*.json
News metadata: data/$TICKER/$DATE/finviz_news.json
Existing log:  data/$TICKER/sentiment_log.jsonl
Summary file:  data/$TICKER/sentiment_summary.json

Steps:
1. Read data/$TICKER/sentiment_log.jsonl — collect all existing article_ids to skip.
2. For each .json file in data/$TICKER/$DATE/articles/:
   - Skip if its stem (article_id) is already in the log.
   - Skip if content.text is null or empty.
3. For each new article, find the matching entry in finviz_news.json by article_id to get headline, publisher, url.
4. Assign: sentiment (bullish/bearish/neutral), score (-1.0 to 1.0), one-sentence summary of market implication for $TICKER.
5. Append each new record as a JSON line to data/$TICKER/sentiment_log.jsonl with fields:
   article_id, ticker (\"$TICKER\"), run_date (\"$DATE\"), analyzed_at (current Pacific ISO timestamp),
   headline, publisher, url, sentiment, score, summary, analysis_error (null).
6. Regenerate data/$TICKER/sentiment_summary.json with:
   schema_version (\"1.0\"), ticker, generated_at, total_analyzed, overall_sentiment,
   overall_score_avg, sentiment_distribution (dict of counts), by_date array (newest first,
   each entry: date, articles_analyzed, sentiment, score_avg, top_headlines list of up to 5
   by abs(score) with headline/publisher/sentiment/score/summary).
7. Print one line: \"$TICKER $DATE: N new analyzed, N skipped, overall=<sentiment> (<score>)\"."

    if "$CLAUDE" --print "$PROMPT" >> "$LOG" 2>&1; then
        log "[$TICKER] analysis OK"
        git -C "$PROJECT_DIR" add \
            "data/$TICKER/sentiment_log.jsonl" \
            "data/$TICKER/sentiment_summary.json" \
            2>/dev/null || true
    else
        log "[$TICKER] analysis failed (exit $?)"
    fi

    # Extract sentiment summary for commit message
    SUMMARY=$("$PYTHON" - <<PYEOF 2>/dev/null || echo "unknown"
import json, sys
try:
    d = json.load(open("$PROJECT_DIR/data/$TICKER/sentiment_summary.json"))
    s = d.get("overall_sentiment", "?")
    v = d.get("overall_score_avg", 0.0)
    n = d.get("total_analyzed", 0)
    print(f"{s} {v:+.2f}  ({n} articles)")
except Exception as e:
    print("analysis unavailable")
PYEOF
)
    COMMIT_LINES="$COMMIT_LINES  $(printf '%-6s' "$TICKER")  $SUMMARY\n"
done

# ── Git commit ────────────────────────────────────────────────────────────────
cd "$PROJECT_DIR"

if [ "$ANYTHING_STAGED" = false ]; then
    log "nothing staged — skipping commit"
else
    # Check if there is actually anything new staged
    if git diff --cached --quiet 2>/dev/null; then
        log "no changes in staged files — skipping commit"
    else
        TICKER_COUNT=$(echo "$TICKERS" | wc -w | tr -d ' ')
        COMMIT_SUBJECT="finzwiz $DATE $TIME PT — $TICKER_COUNT tickers"
        COMMIT_BODY="$(printf '%b' "$COMMIT_LINES")"

        git commit -m "$COMMIT_SUBJECT" -m "$COMMIT_BODY" >> "$LOG" 2>&1
        log "git commit OK: $COMMIT_SUBJECT"
    fi
fi

log "=== finzwiz workflow complete ==="
