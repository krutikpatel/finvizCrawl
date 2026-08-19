#!/usr/bin/env bash
# ============================================================================
# Stock Monitor — Daily Sentinel Runner
#
# Usage:
#   ./run-daily.sh                  # Run all tickers from config.yaml
#   ./run-daily.sh AAPL             # Run a single ticker
#   ./run-daily.sh AAPL NVDA        # Run specific tickers
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
        log "ERROR: configured $name path is not executable: $override"
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
    log "ERROR: $name CLI not found. Set $config_var in monitor/config.env or add $name to PATH."
    return 1
}

run_ai() {
    local prompt_file="$1"
    local output_file="$2"
    local use_websearch="${3:-true}"   # "false" when WEBSEARCH_OFF=true
    local provider="${MONITOR_AI_PROVIDER:-claude}"

    case "$provider" in
        claude)
            local args=(-p)
            if [ "$use_websearch" = "true" ]; then
                args+=(--allowedTools "WebSearch(query),WebFetch(url,prompt)")
            fi
            if [ -n "${MONITOR_CLAUDE_MODEL:-}" ]; then
                args=(--model "$MONITOR_CLAUDE_MODEL" "${args[@]}")
            fi
            local claude_bin
            claude_bin=$(resolve_cli "${MONITOR_CLAUDE_BIN:-}" claude) || return 1
            "$claude_bin" "${args[@]}" < "$prompt_file" > "$output_file" 2>>"$LOG"
            ;;
        codex)
            local args=(--search exec -C "$REPO_ROOT" --sandbox read-only --output-last-message "$output_file")
            if [ -n "${MONITOR_CODEX_MODEL:-}" ]; then
                args=(-m "$MONITOR_CODEX_MODEL" "${args[@]}")
            fi
            local codex_bin
            codex_bin=$(resolve_cli "${MONITOR_CODEX_BIN:-}" codex) || return 1
            "$codex_bin" "${args[@]}" - < "$prompt_file" >> "$LOG" 2>&1
            ;;
        *)
            log "ERROR: unsupported MONITOR_AI_PROVIDER=$provider (expected claude or codex)"
            return 2
            ;;
    esac
}

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
    TICKERS="$(load_tickers_from_config)"
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

    # ── Build optional scraped-articles section (WEBSEARCH_OFF mode) ────────────
    local articles_section=""
    local use_websearch="true"
    if [ "${WEBSEARCH_OFF:-false}" = "true" ]; then
        use_websearch="false"
        log "[$ticker] webSearchOff=true — picking top articles from scraped data..."
        local articles_text
        articles_text=$("$PYTHON" "$SCRIPT_DIR/pick_articles.py" \
            --ticker "$ticker" \
            --date "$TODAY" \
            --data-dir "$FINVIZ_DIR" \
            --n 5 2>>"$LOG" || echo "No articles available.")
        articles_section="
═══════════════════════════════════════════════════════════════════════════
RECENT NEWS ARTICLES — top 5 ranked from today's scrape (replaces Step 4 web search)
═══════════════════════════════════════════════════════════════════════════
${articles_text}

NOTE: Web search is disabled (WEBSEARCH_OFF=true). For Step 4 of your
instructions, use ONLY the articles above — do NOT call WebSearch or WebFetch."
    fi

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
$articles_section

═══════════════════════════════════════════════════════════════════════════
TASK: Run the daily sentinel analysis for $ticker as of $TODAY.
Follow all steps in your instructions. Output the LEDGER_ENTRY JSON block
first, then the full report.
═══════════════════════════════════════════════════════════════════════════
PROMPT_END
)

    log "[$ticker] running ${MONITOR_AI_PROVIDER:-claude} analysis..."
    local tmp_output="/tmp/stock-monitor-${ticker}-${TODAY}.md"
    local tmp_prompt="/tmp/stock-monitor-${ticker}-${TODAY}.prompt"

    printf '%s\n\n---\n\n%s\n' "$system_prompt" "$user_message" > "$tmp_prompt"

    set +e
    run_ai "$tmp_prompt" "$tmp_output" "$use_websearch"
    local ai_exit=$?
    set -e
    rm -f "$tmp_prompt"

    if [ "$ai_exit" -ne 0 ] || [ ! -s "$tmp_output" ]; then
        log "[$ticker] ERROR: ${MONITOR_AI_PROVIDER:-claude} analysis failed or produced empty output"
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

# Refresh the dashboard after monitor reports are available so it reflects
# today's verdicts instead of only the earlier workflow scrape.
if [ -f "$REPO_ROOT/scripts/generate_dashboard.py" ]; then
    log "generating dashboard.html from today's monitor reports..."
    if "$PYTHON" "$REPO_ROOT/scripts/generate_dashboard.py" \
        --tickers "$TICKERS" \
        --date "$TODAY" \
        --data-dir "$REPO_ROOT/data" \
        --reports-dir "$REPORTS_DIR" \
        --output "$REPO_ROOT/dashboard.html" >> "$LOG" 2>&1; then
        log "dashboard OK"
    else
        log "dashboard generation failed"
    fi
fi

if [ "$AUTO_GIT_COMMIT" = "true" ]; then
    cd "$REPO_ROOT"
    if [ -n "$(git status --porcelain "$REPORTS_DIR" dashboard.html 2>/dev/null)" ]; then
        git add "$REPORTS_DIR" dashboard.html
        git commit -m "$GIT_MSG_PREFIX Daily sentinel $TODAY — $TICKERS" --quiet
        log "git: committed report changes"
        if git push >> "$LOG" 2>&1; then
            log "git: pushed report changes"
        else
            log "git: push failed"
        fi
    fi
fi

if [ -n "$FAILED" ]; then
    log "=== done — FAILED tickers:$FAILED ==="
    exit 1
else
    log "=== done — all tickers OK ==="
fi
