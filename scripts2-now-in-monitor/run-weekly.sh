#!/usr/bin/env bash
# ============================================================================
# Stock Monitor — Weekly Deep Panel Runner
#
# Runs the full multi-persona SME deep analysis for each ticker.
# Intended to run weekly (Saturday/Sunday) via cron or Claude Code schedule,
# or on-demand when a daily sentinel triggers TRIGGER DEEP ANALYSIS.
#
# Usage:
#   ./run-weekly.sh                 # Run all tickers in WATCHLIST
#   ./run-weekly.sh AAPL            # Run a single ticker
#   ./run-weekly.sh AAPL NVDA       # Run specific tickers
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

# ── Locate Finviz data (same logic as daily) ────────────────────────────────

find_finviz_data() {
    local ticker="$1"

    local dated_file="$FINVIZ_DIR/$ticker/${TODAY}.csv"
    [ -f "$dated_file" ] && { echo "$dated_file"; return 0; }

    local latest_file="$FINVIZ_DIR/$ticker/latest.csv"
    [ -f "$latest_file" ] && { echo "$latest_file"; return 0; }

    local flat_file="$FINVIZ_DIR/${ticker}.csv"
    [ -f "$flat_file" ] && { echo "$flat_file"; return 0; }

    local lower_ticker=$(echo "$ticker" | tr '[:upper:]' '[:lower:]')
    local lower_file="$FINVIZ_DIR/${lower_ticker}.csv"
    [ -f "$lower_file" ] && { echo "$lower_file"; return 0; }

    local found
    found=$(find "$FINVIZ_DIR" -name "${ticker}*" -type f 2>/dev/null | sort -r | head -1)
    [ -n "$found" ] && { echo "$found"; return 0; }

    return 1
}

# ── Find prior weekly analysis ──────────────────────────────────────────────

find_prior_weekly() {
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

# ── Find last weekly date for trigger scanning ──────────────────────────────

find_prior_weekly_date() {
    local ticker="$1"
    local weekly_file
    if weekly_file=$(find_prior_weekly "$ticker"); then
        # Extract date from filename (YYYY-MM-DD.md)
        basename "$weekly_file" .md
        return 0
    fi
    # Default: 7 days ago
    date -d "7 days ago" +%Y-%m-%d 2>/dev/null || date -v-7d +%Y-%m-%d
}

# ── Run deep analysis for one ticker ────────────────────────────────────────

run_deep_analysis() {
    local ticker="$1"
    echo "━━━ [$ticker] Running weekly deep panel analysis for $TODAY ━━━"

    # 1. Find Finviz data
    local finviz_file
    if ! finviz_file=$(find_finviz_data "$ticker"); then
        echo "  ERROR: No Finviz data found for $ticker. Skipping."
        return 1
    fi
    echo "  Data source: $finviz_file"

    # 2. Ensure directories exist
    local ticker_dir="$REPORTS_DIR/$ticker"
    local weekly_dir="$ticker_dir/weekly"
    local ledger_file="$ticker_dir/ledger.jsonl"
    mkdir -p "$weekly_dir"

    # 3. Check if already run today
    local report_file="$weekly_dir/${TODAY}.md"
    if [ -f "$report_file" ]; then
        echo "  SKIP: Weekly report already exists for $TODAY"
        return 0
    fi

    # 4. Gather all context
    local finviz_data
    finviz_data=$(cat "$finviz_file")

    # Full ledger for weekly (more lookback than daily)
    local ledger_context
    ledger_context=$(python3 "$LEDGER_MGR" tail "$ledger_file" "$WEEKLY_LEDGER_LOOKBACK" 2>/dev/null || echo "No prior ledger data available.")

    # Trend summary
    local trend_summary
    trend_summary=$(python3 "$LEDGER_MGR" summary "$ledger_file" "$WEEKLY_LEDGER_LOOKBACK" 2>/dev/null || echo "No trend data available yet.")

    # Prior weekly analysis
    local prior_weekly="No prior weekly deep analysis available. This is the first run."
    local prior_file
    if prior_file=$(find_prior_weekly "$ticker"); then
        prior_weekly=$(cat "$prior_file")
        echo "  Prior weekly: $prior_file"
    fi

    # Trigger alerts since last weekly
    local since_date
    since_date=$(find_prior_weekly_date "$ticker")
    local trigger_alerts
    trigger_alerts=$(python3 "$LEDGER_MGR" triggers "$ticker_dir" "$since_date" 2>/dev/null || echo "No trigger alerts.")

    local system_prompt
    system_prompt=$(cat "$PROMPTS_DIR/weekly-deep-panel.md")

    # 5. Build the user message
    local user_message
    user_message=$(cat <<PROMPT_END
TICKER: $ticker
DATE: $TODAY
ANALYSIS TYPE: Weekly Deep Panel

═══════════════════════════════════════════════════════════════════════════
THIS WEEK'S FINVIZ DATA SNAPSHOT (authoritative)
═══════════════════════════════════════════════════════════════════════════
$finviz_data

═══════════════════════════════════════════════════════════════════════════
FULL METRICS LEDGER (last ${WEEKLY_LEDGER_LOOKBACK} trading days)
═══════════════════════════════════════════════════════════════════════════
$ledger_context

═══════════════════════════════════════════════════════════════════════════
AUTO-GENERATED TREND SUMMARY
═══════════════════════════════════════════════════════════════════════════
$trend_summary

═══════════════════════════════════════════════════════════════════════════
LAST WEEKLY DEEP ANALYSIS (your prior verdict and zones — compare against)
═══════════════════════════════════════════════════════════════════════════
$prior_weekly

═══════════════════════════════════════════════════════════════════════════
SENTINEL TRIGGER ALERTS SINCE LAST WEEKLY
═══════════════════════════════════════════════════════════════════════════
$trigger_alerts

═══════════════════════════════════════════════════════════════════════════
TASK: Run the full multi-persona deep panel analysis for $ticker as of
$TODAY. Follow all steps in your instructions. Be thorough — this is the
weekly deep dive, not the daily sentinel.
═══════════════════════════════════════════════════════════════════════════
PROMPT_END
)

    # 6. Run Claude
    echo "  Running Claude deep analysis (this takes longer)..."
    local tmp_output="/tmp/stock-monitor-weekly-${ticker}-${TODAY}.md"

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

    # 7. Save the report
    cp "$tmp_output" "$report_file"
    rm -f "$tmp_output"
    echo "  Report saved: $report_file"

    return 0
}

# ── Main ─────────────────────────────────────────────────────────────────────

echo "Stock Monitor — Weekly Deep Panel Analysis"
echo "Date: $TODAY"
echo "Tickers: $TICKERS"
echo ""

FAILED=""
for ticker in $TICKERS; do
    if ! run_deep_analysis "$ticker"; then
        FAILED="$FAILED $ticker"
    fi
    echo ""
done

# ── Git commit ───────────────────────────────────────────────────────────────

if [ "$AUTO_GIT_COMMIT" = "true" ]; then
    cd "$REPO_ROOT"
    if [ -n "$(git status --porcelain "$REPORTS_DIR" 2>/dev/null)" ]; then
        git add "$REPORTS_DIR"
        git commit -m "$GIT_MSG_PREFIX Weekly deep analysis $TODAY — $TICKERS" --quiet
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
