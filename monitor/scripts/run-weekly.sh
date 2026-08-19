#!/usr/bin/env bash
# ============================================================================
# Stock Monitor — Weekly Deep Panel Runner
#
# Usage:
#   ./run-weekly.sh                 # Run all tickers from config.yaml
#   ./run-weekly.sh AAPL            # Run a single ticker
#   ./run-weekly.sh AAPL NVDA       # Run specific tickers
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MONITOR_DIR="$(dirname "$SCRIPT_DIR")"
REPO_ROOT="$(dirname "$MONITOR_DIR")"

source "$MONITOR_DIR/config.env"
PYTHON="$REPO_ROOT/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    PYTHON=python3
fi

load_tickers_from_config() {
    "$PYTHON" - "$REPO_ROOT/config.yaml" <<'PY'
import sys
import yaml

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    config = yaml.safe_load(handle) or {}
tickers = config.get("tickers", "")
if isinstance(tickers, list):
    print(" ".join(str(ticker).upper() for ticker in tickers))
else:
    print(str(tickers).upper())
PY
}

resolve_cli() {
    local override="$1"
    local name="$2"
    shift 2

    if [ -n "$override" ]; then
        if [ -x "$override" ]; then
            echo "$override"
            return 0
        fi
        echo "  ERROR: configured $name path is not executable: $override"
        return 1
    fi

    if command -v "$name" >/dev/null 2>&1; then
        command -v "$name"
        return 0
    fi

    local candidate
    for candidate in "$@"; do
        if [ -x "$candidate" ]; then
            echo "$candidate"
            return 0
        fi
    done

    local config_var
    case "$name" in
        claude) config_var="MONITOR_CLAUDE_BIN" ;;
        codex) config_var="MONITOR_CODEX_BIN" ;;
        *) config_var="the corresponding MONITOR_*_BIN setting" ;;
    esac
    echo "  ERROR: $name CLI not found. Set $config_var in monitor/config.env or add $name to PATH."
    return 1
}

run_ai() {
    local prompt_file="$1"
    local output_file="$2"
    local provider="${MONITOR_AI_PROVIDER:-claude}"

    case "$provider" in
        claude)
            local args=(-p --allowedTools "WebSearch(query),WebFetch(url,prompt)")
            if [ -n "${MONITOR_CLAUDE_MODEL:-}" ]; then
                args=(--model "$MONITOR_CLAUDE_MODEL" "${args[@]}")
            fi
            local claude_bin
            claude_bin=$(resolve_cli "${MONITOR_CLAUDE_BIN:-}" claude) || return 1
            "$claude_bin" "${args[@]}" < "$prompt_file" > "$output_file" 2>/dev/null
            ;;
        codex)
            local args=(--search exec -C "$REPO_ROOT" --sandbox read-only --output-last-message "$output_file")
            if [ -n "${MONITOR_CODEX_MODEL:-}" ]; then
                args=(-m "$MONITOR_CODEX_MODEL" "${args[@]}")
            fi
            local codex_bin
            codex_bin=$(resolve_cli "${MONITOR_CODEX_BIN:-}" codex) || return 1
            "$codex_bin" "${args[@]}" - < "$prompt_file" >/dev/null 2>&1
            ;;
        *)
            echo "  ERROR: unsupported MONITOR_AI_PROVIDER=$provider (expected claude or codex)"
            return 2
            ;;
    esac
}

PROMPTS_DIR="$REPO_ROOT/$PROMPTS_DIR"
REPORTS_DIR="$REPO_ROOT/$REPORTS_DIR"
FINVIZ_DIR="$REPO_ROOT/$FINVIZ_DATA_DIR"
LEDGER_MGR="$SCRIPT_DIR/ledger_manager.py"

TODAY=$(date +%Y-%m-%d)

if [ $# -gt 0 ]; then
    TICKERS="$*"
else
    TICKERS="$(load_tickers_from_config)"
fi

# ── Locate finviz_quote.json for a ticker ────────────────────────────────────

find_finviz_data() {
    local ticker="$1"

    local dated="$FINVIZ_DIR/$ticker/${TODAY}/finviz_quote.json"
    [ -f "$dated" ] && { echo "$dated"; return 0; }

    local found
    found=$(find "$FINVIZ_DIR/$ticker" -name "finviz_quote.json" -type f 2>/dev/null | sort -r | head -1)
    [ -n "$found" ] && { echo "$found"; return 0; }

    return 1
}

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

find_prior_weekly_date() {
    local ticker="$1"
    local weekly_file
    if weekly_file=$(find_prior_weekly "$ticker"); then
        basename "$weekly_file" .md
        return 0
    fi
    date -v-7d +%Y-%m-%d
}

run_deep_analysis() {
    local ticker="$1"
    echo "━━━ [$ticker] Running weekly deep panel analysis for $TODAY ━━━"

    local finviz_file
    if ! finviz_file=$(find_finviz_data "$ticker"); then
        echo "  ERROR: No finviz_quote.json found for $ticker. Skipping."
        return 1
    fi
    echo "  Data source: $finviz_file"

    local ticker_dir="$REPORTS_DIR/$ticker"
    local weekly_dir="$ticker_dir/weekly"
    local ledger_file="$ticker_dir/ledger.jsonl"
    mkdir -p "$weekly_dir"

    local report_file="$weekly_dir/${TODAY}.md"
    if [ -f "$report_file" ]; then
        echo "  SKIP: Weekly report already exists for $TODAY"
        return 0
    fi

    local finviz_data
    finviz_data=$(cat "$finviz_file")

    local ledger_context
    ledger_context=$(python3 "$LEDGER_MGR" tail "$ledger_file" "$WEEKLY_LEDGER_LOOKBACK" 2>/dev/null || echo "No prior ledger data available.")

    local trend_summary
    trend_summary=$(python3 "$LEDGER_MGR" summary "$ledger_file" "$WEEKLY_LEDGER_LOOKBACK" 2>/dev/null || echo "No trend data available yet.")

    local prior_weekly="No prior weekly deep analysis available. This is the first run."
    local prior_file
    if prior_file=$(find_prior_weekly "$ticker"); then
        prior_weekly=$(cat "$prior_file")
        echo "  Prior weekly: $prior_file"
    fi

    local since_date
    since_date=$(find_prior_weekly_date "$ticker")
    local trigger_alerts
    trigger_alerts=$(python3 "$LEDGER_MGR" triggers "$ticker_dir" "$since_date" 2>/dev/null || echo "No trigger alerts.")

    local system_prompt
    system_prompt=$(cat "$PROMPTS_DIR/weekly-deep-panel.md")

    local user_message
    user_message=$(cat <<PROMPT_END
TICKER: $ticker
DATE: $TODAY
ANALYSIS TYPE: Weekly Deep Panel

═══════════════════════════════════════════════════════════════════════════
FINVIZ DATA SNAPSHOT — THIS WEEK (authoritative)
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
PRIOR WEEKLY DEEP ANALYSIS (your prior verdict and zones — compare against)
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

    echo "  Running ${MONITOR_AI_PROVIDER:-claude} deep analysis (this takes longer)..."
    local tmp_output="/tmp/stock-monitor-weekly-${ticker}-${TODAY}.md"
    local tmp_prompt="/tmp/stock-monitor-weekly-${ticker}-${TODAY}.prompt"

    printf '%s\n\n---\n\n%s\n' "$system_prompt" "$user_message" > "$tmp_prompt"

    set +e
    run_ai "$tmp_prompt" "$tmp_output"
    local ai_exit=$?
    set -e
    rm -f "$tmp_prompt"

    if [ "$ai_exit" -ne 0 ] || [ ! -s "$tmp_output" ]; then
        echo "  ERROR: ${MONITOR_AI_PROVIDER:-claude} analysis failed or produced empty output."
        rm -f "$tmp_output"
        return 1
    fi

    cp "$tmp_output" "$report_file"
    rm -f "$tmp_output"
    echo "  Report saved: $report_file"

    return 0
}

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

if [ "$AUTO_GIT_COMMIT" = "true" ]; then
    cd "$REPO_ROOT"
    if [ -n "$(git status --porcelain "$REPORTS_DIR" 2>/dev/null)" ]; then
        git add "$REPORTS_DIR"
        git commit -m "$GIT_MSG_PREFIX Weekly deep analysis $TODAY — $TICKERS" --quiet
        echo "Git: Committed report changes."
    fi
fi

if [ -n "$FAILED" ]; then
    echo "⚠️  Failed tickers:$FAILED"
    exit 1
else
    echo "✓ All tickers processed successfully."
fi
