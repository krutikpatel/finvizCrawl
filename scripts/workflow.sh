#!/usr/bin/env bash
# Daily finzwiz workflow — four phases:
#   1. Scrape all tickers
#   2. Python pre-filter — write analysis_input.json per ticker (new articles only, text ≤ 2000 chars)
#   3. Single claude --print call covering all tickers with new articles
#   4. Python rebuild-summary per ticker — aggregates sentiment_log.jsonl into sentiment_summary.json
# Tickers: space-separated in FINZWIZ_TICKERS env var, default TSLA.
# Logs: logs/workflow-YYYY-MM-DD.log

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PYTHON="$PROJECT_DIR/.venv/bin/python"
CLAUDE=/opt/homebrew/bin/claude
# Tickers: env var overrides config.yaml, config.yaml overrides hardcoded fallback
TICKERS="${FINZWIZ_TICKERS:-$("$PYTHON" -c "
import yaml, sys
try:
    print(yaml.safe_load(open('$PROJECT_DIR/config.yaml'))['tickers'])
except Exception:
    print('TSLA')
" 2>/dev/null || echo "TSLA")}"
DATE="$(TZ='America/Los_Angeles' date +%Y-%m-%d)"
TIME="$(TZ='America/Los_Angeles' date '+%H:%M')"

mkdir -p "$PROJECT_DIR/logs"
LOG="$PROJECT_DIR/logs/workflow-$DATE.log"

log() { echo "[$(TZ='America/Los_Angeles' date '+%Y-%m-%d %H:%M:%S PT')] $*" | tee -a "$LOG"; }

log "=== finzwiz workflow start | tickers: $TICKERS ==="

ANYTHING_STAGED=false
ANALYZE_TICKERS=""  # scraped OK + has new articles
SKIPPED_TICKERS=""  # scraped OK + all articles already analyzed
FAILED_TICKERS=""   # scrape failed

# ── Phase 1 + 2: scrape then pre-filter each ticker ───────────────────────────
for TICKER in $TICKERS; do
    log "[$TICKER] scraping..."
    cd "$PROJECT_DIR"
    if ! PYTHONPATH=src "$PYTHON" -m finzwiz.cli scrape --ticker "$TICKER" >> "$LOG" 2>&1; then
        log "[$TICKER] scrape FAILED"
        FAILED_TICKERS="$FAILED_TICKERS $TICKER"
        continue
    fi
    log "[$TICKER] scrape OK"
    git -C "$PROJECT_DIR" add \
        "data/$TICKER/$DATE/" \
        "data/$TICKER/seen_urls.jsonl" \
        2>/dev/null || true
    ANYTHING_STAGED=true

    # Pre-filter: dedup against sentiment_log.jsonl, extract compact fields, truncate text to 2000 chars.
    # Writes data/$TICKER/$DATE/analysis_input.json and prints the count of new articles.
    NEW_COUNT=$("$PYTHON" - 2>>"$LOG" <<PYEOF || echo "0"
import json
from pathlib import Path

project_dir = Path("$PROJECT_DIR")
ticker      = "$TICKER"
date        = "$DATE"

articles_dir = project_dir / "data" / ticker / date / "articles"
news_path    = project_dir / "data" / ticker / date / "finviz_news.json"
log_path     = project_dir / "data" / ticker / "sentiment_log.jsonl"
out_path     = project_dir / "data" / ticker / date / "analysis_input.json"

known_ids = set()
if log_path.exists():
    for line in log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                known_ids.add(json.loads(line)["article_id"])
            except Exception:
                pass

news_lookup = {}
if news_path.exists():
    for item in json.loads(news_path.read_text(encoding="utf-8")).get("items", []):
        aid = item.get("article_id")
        if aid:
            news_lookup[aid] = {
                "headline": item.get("headline", ""),
                "publisher": item.get("publisher", ""),
                "url": item.get("url", ""),
            }

new_articles = []
if articles_dir.exists():
    for f in sorted(articles_dir.glob("*.json")):
        aid = f.stem
        if aid in known_ids:
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            text = (data.get("content") or {}).get("text") or ""
            if not text:
                continue
            meta = news_lookup.get(aid, {})
            new_articles.append({
                "article_id": aid,
                "headline": meta.get("headline", ""),
                "publisher": meta.get("publisher", ""),
                "url": meta.get("url", (data.get("source") or {}).get("url", "")),
                "text": text[:2000],
            })
        except Exception:
            pass

out_path.write_text(
    json.dumps({"ticker": ticker, "run_date": date, "articles": new_articles}, indent=2),
    encoding="utf-8",
)
print(len(new_articles))
PYEOF
)

    if [ "${NEW_COUNT:-0}" -gt 0 ] 2>/dev/null; then
        log "[$TICKER] $NEW_COUNT new articles queued for analysis"
        ANALYZE_TICKERS="$ANALYZE_TICKERS $TICKER"
    else
        log "[$TICKER] no new articles to analyze"
        SKIPPED_TICKERS="$SKIPPED_TICKERS $TICKER"
    fi
done

ANALYZE_TICKERS="${ANALYZE_TICKERS# }"

# ── Phase 3: single batched Claude analysis ───────────────────────────────────
if [ -n "$ANALYZE_TICKERS" ]; then
    log "running single-pass analysis for: $ANALYZE_TICKERS"

    TICKER_BLOCKS=""
    for TICKER in $ANALYZE_TICKERS; do
        TICKER_BLOCKS="$TICKER_BLOCKS
=== $TICKER ===
  input:  data/$TICKER/$DATE/analysis_input.json
  append: data/$TICKER/sentiment_log.jsonl
"
    done

    PROMPT="Analyze stock sentiment for multiple tickers. Each ticker's input file contains ONLY new articles (pre-filtered by Python — do NOT check for duplicates).

Important token rule: read ONLY the listed analysis_input.json files. Do NOT read, inspect, grep, count, or verify sentiment_log.jsonl files; they are append targets only. Do NOT inspect prior runs or historical data.

Working directory: $PROJECT_DIR

$TICKER_BLOCKS

For EACH ticker above:
1. Read that ticker's analysis_input.json. The \"articles\" array lists every article to analyze.
2. For each article, assign:
   - sentiment: \"bullish\", \"bearish\", or \"neutral\"
   - score: float -1.0 (very bearish) to 1.0 (very bullish)
   - summary: one sentence on the key market implication for that ticker
3. Append one JSON line per article to that ticker's sentiment_log.jsonl without reading the existing file:
   {\"article_id\": \"...\", \"ticker\": \"$TICKER\", \"run_date\": \"$DATE\", \"analyzed_at\": \"<Pacific ISO>\", \"headline\": \"...\", \"publisher\": \"...\", \"url\": \"...\", \"sentiment\": \"...\", \"score\": 0.0, \"summary\": \"...\", \"analysis_error\": null}
4. Do NOT write sentiment_summary.json — Python rebuilds that after this step.
5. Print one line: \"<TICKER> $DATE: N analyzed\"

Process all tickers. After finishing all, print: \"BATCH COMPLETE: N tickers\""

    if "$CLAUDE" --print "$PROMPT" >> "$LOG" 2>&1; then
        log "batch analysis OK"
    else
        log "batch analysis failed (exit $?) — summaries will still be rebuilt from whatever was written"
    fi
fi

# ── Phase 4: Python rebuilds sentiment_summary.json for each analyzed ticker ──
for TICKER in $ANALYZE_TICKERS; do
    if PYTHONPATH=src "$PYTHON" -m finzwiz.cli rebuild-summary \
            --ticker "$TICKER" >> "$LOG" 2>&1; then
        log "[$TICKER] summary rebuilt"
        git -C "$PROJECT_DIR" add \
            "data/$TICKER/sentiment_log.jsonl" \
            "data/$TICKER/sentiment_summary.json" \
            2>/dev/null || true
    else
        log "[$TICKER] summary rebuild failed"
    fi
done

# ── Generate dashboard ───────────────────────────────────────────────────────
if [ "$ANYTHING_STAGED" = true ]; then
    log "generating dashboard.html..."
    if "$PYTHON" "$SCRIPT_DIR/generate_dashboard.py" \
        --tickers "$TICKERS" \
        --date "$DATE" \
        --data-dir "$PROJECT_DIR/data" \
        --output "$PROJECT_DIR/dashboard.html" >> "$LOG" 2>&1; then
        log "dashboard OK"
        git -C "$PROJECT_DIR" add "$PROJECT_DIR/dashboard.html" 2>/dev/null || true
    else
        log "dashboard generation failed"
    fi
fi

# ── Build commit message body ─────────────────────────────────────────────────
COMMIT_LINES=""
for TICKER in $TICKERS; do
    case " $FAILED_TICKERS " in
        *" $TICKER "*) COMMIT_LINES="$COMMIT_LINES  $(printf '%-6s' "$TICKER")  scrape failed\n"; continue ;;
    esac
    case " $SKIPPED_TICKERS " in
        *" $TICKER "*) COMMIT_LINES="$COMMIT_LINES  $(printf '%-6s' "$TICKER")  no new articles\n"; continue ;;
    esac

    SUMMARY=$("$PYTHON" - 2>/dev/null <<PYEOF || echo "analysis unavailable"
import json
try:
    d = json.load(open("$PROJECT_DIR/data/$TICKER/sentiment_summary.json"))
    s = d.get("overall_sentiment", "?")
    v = d.get("overall_score_avg", 0.0)
    n = d.get("total_analyzed", 0)
    print(f"{s} {v:+.2f}  ({n} articles)")
except Exception:
    print("analysis unavailable")
PYEOF
)
    COMMIT_LINES="$COMMIT_LINES  $(printf '%-6s' "$TICKER")  $SUMMARY\n"
done

# ── Git commit ────────────────────────────────────────────────────────────────
cd "$PROJECT_DIR"

if [ "$ANYTHING_STAGED" = false ]; then
    log "nothing staged — skipping commit"
elif git diff --cached --quiet 2>/dev/null; then
    log "no changes in staged files — skipping commit"
else
    TICKER_COUNT=$(echo "$TICKERS" | wc -w | tr -d ' ')
    COMMIT_SUBJECT="finzwiz $DATE $TIME PT — $TICKER_COUNT tickers"
    COMMIT_BODY="$(printf '%b' "$COMMIT_LINES")"

    git commit -m "$COMMIT_SUBJECT" -m "$COMMIT_BODY" >> "$LOG" 2>&1
    log "git commit OK: $COMMIT_SUBJECT"
    if git push >> "$LOG" 2>&1; then
        log "git push OK"
    else
        log "git push failed"
    fi
fi

# ── Email summary ─────────────────────────────────────────────────────────────
if [ -n "${FINZWIZ_EMAIL:-}" ]; then
    log "sending summary email to $FINZWIZ_EMAIL..."
    if "$PYTHON" "$SCRIPT_DIR/send_summary_email.py" \
        --to "$FINZWIZ_EMAIL" \
        --tickers "$TICKERS" \
        --date "$DATE" \
        --data-dir "$PROJECT_DIR/data" >> "$LOG" 2>&1; then
        log "email sent OK"
    else
        log "email failed — check Keychain (run: make setup-email)"
    fi
fi

log "=== finzwiz workflow complete ==="
