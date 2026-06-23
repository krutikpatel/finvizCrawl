#!/usr/bin/env bash
# ============================================================================
# Stock Monitor — Daily Sentinel Runner
#
# Usage:
#   ./run-daily.sh                  # Run all tickers in WATCHLIST
#   ./run-daily.sh AAPL             # Run a single ticker
#   ./run-daily.sh AAPL NVDA        # Run specific tickers
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MONITOR_DIR="$(dirname "$SCRIPT_DIR")"
REPO_ROOT="$(dirname "$MONITOR_DIR")"

source "$MONITOR_DIR/config.env"

PROMPTS_DIR="$REPO_ROOT/$PROMPTS_DIR"
REPORTS_DIR="$REPO_ROOT/$REPORTS_DIR"
FINVIZ_DIR="$REPO_ROOT/$FINVIZ_DATA_DIR"
LEDGER_MGR="$SCRIPT_DIR/ledger_manager.py"

TODAY=$(TZ='America/Los_Angeles' date +%Y-%m-%d)

mkdir -p "$REPO_ROOT/logs"
LOG="$REPO_ROOT/logs/monitor-$TODAY.log"
log() { echo "[$(TZ='America/Los_Angeles' date '+%Y-%m-%d %H:%M:%S PT')] $*" | tee -a "$LOG"; }

if [ $# -gt 0 ]; then
    TICKERS="$*"
else
    TICKERS="$WATCHLIST"
fi

# ── Locate finviz_quote.json for a ticker ────────────────────────────────────
# This repo stores: data/<TICKER>/<YYYY-MM-DD>/finviz_quote.json

find_finviz_data() {
    local ticker="$1"

    # Today's run (preferred)
    local dated="$FINVIZ_DIR/$ticker/${TODAY}/finviz_quote.json"
    if [ -f "$dated" ]; then
        echo "$dated"
        return 0
    fi

    # Most recent date subfolder that has a finviz_quote.json
    local found
    found=$(find "$FINVIZ_DIR/$ticker" -name "finviz_quote.json" -type f 2>/dev/null | sort -r | head -1)
    if [ -n "$found" ]; then
        echo "$found"
        return 0
    fi

    return 1
}

find_latest_weekly() {
    local ticker="$1"
    local weekly_dir="$REPORTS_DIR/$ticker/weekly"

    if [ -d "$weekly_dir" ]; then
        local latest
        latest=$(ls -1 "$weekly_dir"/*.md 2>/dev/null | sort -r | head -1)
        if [ -n "$latest" ]; then
            echo "$latest"
            return 0
        fi
    fi
    return 1
}

run_sentinel() {
    local ticker="$1"
    log "[$ticker] running daily sentinel for $TODAY"

    local finviz_file
    if ! finviz_file=$(find_finviz_data "$ticker"); then
        log "[$ticker] ERROR: No finviz_quote.json found — skipping"
        return 1
    fi
    log "[$ticker] data source: $finviz_file"

    local ticker_dir="$REPORTS_DIR/$ticker"
    local daily_dir="$ticker_dir/daily"
    local ledger_file="$ticker_dir/ledger.jsonl"
    mkdir -p "$daily_dir"

    local report_file="$daily_dir/${TODAY}.md"
    if [ -f "$report_file" ]; then
        log "[$ticker] SKIP: report already exists for $TODAY"
        return 0
    fi

    local finviz_data
    finviz_data=$(cat "$finviz_file")

    local ledger_context
    ledger_context=$(python3 "$LEDGER_MGR" tail "$ledger_file" "$LEDGER_LOOKBACK" 2>/dev/null || echo "No prior ledger data available.")

    local weekly_context="No prior weekly deep analysis available."
    local weekly_file
    if weekly_file=$(find_latest_weekly "$ticker"); then
        weekly_context=$(cat "$weekly_file")
    fi

    local system_prompt
    system_prompt=$(cat "$PROMPTS_DIR/daily-sentinel.md")

    local user_message
    user_message=$(cat <<PROMPT_END
TICKER: $ticker
DATE: $TODAY

═══════════════════════════════════════════════════════════════════════════
FINVIZ DATA SNAPSHOT — TODAY (authoritative — do not override these numbers)
═══════════════════════════════════════════════════════════════════════════
$finviz_data

═══════════════════════════════════════════════════════════════════════════
METRICS LEDGER (last ${LEDGER_LOOKBACK} trading days)
═══════════════════════════════════════════════════════════════════════════
$ledger_context

═══════════════════════════════════════════════════════════════════════════
LAST WEEKLY DEEP ANALYSIS (baseline for zones and verdict)
═══════════════════════════════════════════════════════════════════════════
$weekly_context

═══════════════════════════════════════════════════════════════════════════
TASK: Run the daily sentinel analysis for $ticker as of $TODAY.
Follow all steps in your instructions. Output the LEDGER_ENTRY JSON block
first, then the full report.
═══════════════════════════════════════════════════════════════════════════
PROMPT_END
)

    log "[$ticker] running Claude analysis..."
    local tmp_output="/tmp/stock-monitor-${ticker}-${TODAY}.md"

    echo "$system_prompt

---

$user_message" | claude -p \
        --allowedTools "WebSearch(query),WebFetch(url,prompt)" \
        > "$tmp_output" 2>>"$LOG"

    if [ $? -ne 0 ] || [ ! -s "$tmp_output" ]; then
        log "[$ticker] ERROR: Claude analysis failed or produced empty output"
        rm -f "$tmp_output"
        return 1
    fi

    log "[$ticker] extracting metrics to ledger..."
    python3 "$LEDGER_MGR" extract "$tmp_output" "$ledger_file" 2>&1 | tee -a "$LOG"

    cp "$tmp_output" "$report_file"
    rm -f "$tmp_output"
    log "[$ticker] report saved: $report_file"

    if grep -qi "TRIGGER DEEP ANALYSIS" "$report_file"; then
        log "[$ticker] ⚠️  TRIGGER DEEP ANALYSIS detected — consider running run-weekly.sh $ticker"
    fi

    return 0
}

log "=== stock-monitor daily sentinel start | tickers: $TICKERS ==="

FAILED=""
for ticker in $TICKERS; do
    if ! run_sentinel "$ticker"; then
        FAILED="$FAILED $ticker"
    fi
done

if [ "$AUTO_GIT_COMMIT" = "true" ]; then
    cd "$REPO_ROOT"
    if [ -n "$(git status --porcelain "$REPORTS_DIR" 2>/dev/null)" ]; then
        git add "$REPORTS_DIR"
        git commit -m "$GIT_MSG_PREFIX Daily sentinel $TODAY — $TICKERS" --quiet
        log "git: committed report changes"
    fi
fi

if [ -n "$FAILED" ]; then
    log "=== done — FAILED tickers:$FAILED ==="
    exit 1
else
    log "=== done — all tickers OK ==="
fi
