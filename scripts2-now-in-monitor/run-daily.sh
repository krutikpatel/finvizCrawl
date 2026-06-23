#!/usr/bin/env bash
# ============================================================================
# Stock Monitor — Daily Sentinel Runner
#
# Runs the daily sentinel analysis for each ticker in the watchlist.
# Intended to be called by cron, Claude Code schedule, or manually.
#
# Usage:
#   ./run-daily.sh                  # Run all tickers in WATCHLIST
#   ./run-daily.sh AAPL             # Run a single ticker
#   ./run-daily.sh AAPL NVDA        # Run specific tickers
# ============================================================================

set -euo pipefail

# ── Resolve paths ────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MONITOR_DIR="$(dirname "$SCRIPT_DIR")"
REPO_ROOT="$(dirname "$MONITOR_DIR")"

# Load config
source "$MONITOR_DIR/config.env"

PROMPTS_DIR="$REPO_ROOT/$PROMPTS_DIR"
REPORTS_DIR="$REPO_ROOT/$REPORTS_DIR"
FINVIZ_DIR="$REPO_ROOT/$FINVIZ_DATA_DIR"
LEDGER_MGR="$SCRIPT_DIR/ledger_manager.py"

TODAY=$(date +%Y-%m-%d)

# ── Determine tickers ───────────────────────────────────────────────────────

if [ $# -gt 0 ]; then
    TICKERS="$*"
else
    TICKERS="$WATCHLIST"
fi

# ── Locate Finviz data for a ticker ─────────────────────────────────────────

find_finviz_data() {
    local ticker="$1"

    # ── Adapt these patterns to your actual scrape output structure ──
    # Pattern 1: data/<TICKER>/<date>.csv (date-stamped in subfolder)
    local dated_file="$FINVIZ_DIR/$ticker/${TODAY}.csv"
    if [ -f "$dated_file" ]; then
        echo "$dated_file"
        return 0
    fi

    # Pattern 2: data/<TICKER>/latest.csv (overwritten daily)
    local latest_file="$FINVIZ_DIR/$ticker/latest.csv"
    if [ -f "$latest_file" ]; then
        echo "$latest_file"
        return 0
    fi

    # Pattern 3: data/<TICKER>.csv (single file per ticker)
    local flat_file="$FINVIZ_DIR/${ticker}.csv"
    if [ -f "$flat_file" ]; then
        echo "$flat_file"
        return 0
    fi

    # Pattern 4: data/<ticker_lowercase>.csv
    local lower_ticker=$(echo "$ticker" | tr '[:upper:]' '[:lower:]')
    local lower_file="$FINVIZ_DIR/${lower_ticker}.csv"
    if [ -f "$lower_file" ]; then
        echo "$lower_file"
        return 0
    fi

    # Pattern 5: find most recent file matching ticker
    local found
    found=$(find "$FINVIZ_DIR" -name "${ticker}*" -type f 2>/dev/null | sort -r | head -1)
    if [ -n "$found" ]; then
        echo "$found"
        return 0
    fi

    return 1
}

# ── Find the latest weekly analysis ─────────────────────────────────────────

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

# ── Run sentinel for one ticker ─────────────────────────────────────────────

run_sentinel() {
    local ticker="$1"
    echo "━━━ [$ticker] Running daily sentinel for $TODAY ━━━"

    # 1. Find Finviz data
    local finviz_file
    if ! finviz_file=$(find_finviz_data "$ticker"); then
        echo "  ERROR: No Finviz data found for $ticker. Skipping."
        return 1
    fi
    echo "  Data source: $finviz_file"

    # 2. Ensure report directories exist
    local ticker_dir="$REPORTS_DIR/$ticker"
    local daily_dir="$ticker_dir/daily"
    local ledger_file="$ticker_dir/ledger.jsonl"
    mkdir -p "$daily_dir"

    # 3. Check if today's report already exists
    local report_file="$daily_dir/${TODAY}.md"
    if [ -f "$report_file" ]; then
        echo "  SKIP: Report already exists for $TODAY"
        return 0
    fi

    # 4. Gather context
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

    # 5. Build the user message
    local user_message
    user_message=$(cat <<PROMPT_END
TICKER: $ticker
DATE: $TODAY

═══════════════════════════════════════════════════════════════════════════
TODAY'S FINVIZ DATA SNAPSHOT (authoritative — do not override these numbers)
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

    # 6. Run Claude
    echo "  Running Claude analysis..."
    local tmp_output="/tmp/stock-monitor-${ticker}-${TODAY}.md"

    # Using claude -p (Claude Code CLI headless mode)
    # Adjust --model and --allowedTools as needed
    echo "$system_prompt

---

$user_message" | claude -p \
        --allowedTools "WebSearch(query),WebFetch(url,prompt)" \
        > "$tmp_output" 2>/dev/null

    if [ $? -ne 0 ] || [ ! -s "$tmp_output" ]; then
        echo "  ERROR: Claude analysis failed or produced empty output."
        rm -f "$tmp_output"
        return 1
    fi

    # 7. Extract JSON and append to ledger
    echo "  Extracting metrics to ledger..."
    python3 "$LEDGER_MGR" extract "$tmp_output" "$ledger_file" 2>&1 | sed 's/^/  /'

    # 8. Save the report
    cp "$tmp_output" "$report_file"
    rm -f "$tmp_output"
    echo "  Report saved: $report_file"

    # 9. Check for trigger alerts
    if grep -qi "TRIGGER DEEP ANALYSIS" "$report_file"; then
        echo ""
        echo "  ⚠️  TRIGGER DEEP ANALYSIS detected for $ticker!"
        echo "  Consider running: ./run-weekly.sh $ticker"
        echo ""
    fi

    return 0
}

# ── Main ─────────────────────────────────────────────────────────────────────

echo "Stock Monitor — Daily Sentinel Run"
echo "Date: $TODAY"
echo "Tickers: $TICKERS"
echo ""

FAILED=""
for ticker in $TICKERS; do
    if ! run_sentinel "$ticker"; then
        FAILED="$FAILED $ticker"
    fi
    echo ""
done

# ── Git commit ───────────────────────────────────────────────────────────────

if [ "$AUTO_GIT_COMMIT" = "true" ]; then
    cd "$REPO_ROOT"
    if [ -n "$(git status --porcelain "$REPORTS_DIR" 2>/dev/null)" ]; then
        git add "$REPORTS_DIR"
        git commit -m "$GIT_MSG_PREFIX Daily sentinel $TODAY — $TICKERS" --quiet
        echo "Git: Committed report changes."
    fi
fi

# ── Summary ──────────────────────────────────────────────────────────────────

if [ -n "$FAILED" ]; then
    echo "⚠️  Failed tickers:$FAILED"
    exit 1
else
    echo "✓ All tickers processed successfully."
fi
