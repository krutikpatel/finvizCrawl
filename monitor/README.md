# Stock Monitor — Continuous Equity Research System

A two-tier AI-powered stock monitoring system that produces daily sentinel reports and weekly deep multi-persona analyses, with a structured ledger that tracks metrics, action zones, and verdicts over time.

## Architecture

```
Finviz Scrape → Daily Sentinel → Ledger (append) → Weekly Deep Panel
     ↑               ↓                                    ↓
  your cron      daily/*.md                          weekly/*.md
                     ↓                                    ↓
               TRIGGER DEEP ANALYSIS ──────→ (auto or manual weekly run)
```

### Two Tiers

**Tier 1 — Daily Sentinel** (runs Mon–Fri)
- Lightweight, 30-second-read report
- Extracts structured metrics → appends to `ledger.jsonl`
- Computes and tracks action zones (Buy/Accumulate/Hold/Trim/Avoid price ranges)
- Produces metric direction + zone drift tables
- Scans last 24h news via web search
- Fires `TRIGGER DEEP ANALYSIS` on material events

**Tier 2 — Weekly Deep Panel** (runs Saturday, or on trigger)
- Full multi-persona SME analysis (5 expert lenses)
- References the accumulated ledger for trend context
- Compares against prior week's verdict and zones
- Structured debate round to surface disagreements
- Recalibrates action zones with stated rationale
- Produces falsifiable upgrade/downgrade triggers

### The Ledger

The `ledger.jsonl` file is the backbone. Each daily run appends one JSON line containing ~35 metrics + action zones + verdict. This enables:
- Tracking any metric's trajectory over weeks/months
- Spotting divergences (e.g., zones rising while price is flat)
- Feeding trend context into both daily and weekly analyses
- Comparing verdict history to actual outcomes

## Directory Structure

```
finvizCrawl/                     ← your repo root
├── data/                        ← existing Finviz scraped data
│   ├── AAPL/
│   │   ├── 2026-06-22.csv       ← (or latest.csv, or AAPL.csv — see config)
│   │   └── ...
│   └── NVDA/
│       └── ...
├── monitor/
│   ├── config.env               ← monitor paths and settings
│   ├── prompts/
│   │   ├── daily-sentinel.md    ← daily system prompt
│   │   └── weekly-deep-panel.md ← weekly system prompt
│   ├── scripts/
│   │   ├── run-daily.sh         ← daily orchestrator
│   │   ├── run-weekly.sh        ← weekly orchestrator
│   │   └── ledger_manager.py    ← JSON extraction, ledger I/O, trend summary
│   ├── reports/                 ← generated (committed to git)
│   │   └── AAPL/
│   │       ├── ledger.jsonl     ← append-only metrics time series
│   │       ├── daily/
│   │       │   ├── 2026-06-22.md
│   │       │   └── 2026-06-23.md
│   │       └── weekly/
│   │           └── 2026-06-22.md
│   └── README.md                ← this file
```

## Setup

### 1. Prerequisites

- Claude Code CLI installed and authenticated (`ANTHROPIC_API_KEY` set)
- Python 3.10+
- Your Finviz scraper already populating `data/`

### 2. Configure

Ticker coverage is read from the root `config.yaml` `tickers` field so the scraper and monitor stay in sync:

```yaml
tickers: "AAPL NVDA IONQ"
```

Edit `monitor/config.env` for monitor-specific settings:

```bash
# Where your Finviz scraper puts data (relative to repo root)
FINVIZ_DATA_DIR="data"

# Auto-commit reports to git after each run
AUTO_GIT_COMMIT=true
```

The scripts look for Finviz data in this order:
1. `data/<TICKER>/<YYYY-MM-DD>.csv`  (date-stamped subfolder)
2. `data/<TICKER>/latest.csv`         (overwritten daily)
3. `data/<TICKER>.csv`                (flat file per ticker)
4. Any file matching `<TICKER>*` under `data/`

If your layout differs, edit `find_finviz_data()` in the run scripts.

### 3. Make scripts executable

```bash
chmod +x monitor/scripts/run-daily.sh
chmod +x monitor/scripts/run-weekly.sh
```

### 4. Test manually

```bash
# Single ticker, daily
./monitor/scripts/run-daily.sh AAPL

# Single ticker, weekly deep dive
./monitor/scripts/run-weekly.sh AAPL
```

### 5. Schedule

**Option A — cron (runs on your machine)**

```bash
crontab -e

# Daily sentinel at 7:30 AM PT, Mon-Fri (after market data is fresh)
30 7 * * 1-5 cd /path/to/finvizCrawl && ./monitor/scripts/run-daily.sh >> /var/log/stock-monitor.log 2>&1

# Weekly deep analysis Saturday 9 AM
0 9 * * 6 cd /path/to/finvizCrawl && ./monitor/scripts/run-weekly.sh >> /var/log/stock-monitor.log 2>&1
```

Make sure `ANTHROPIC_API_KEY` is available to cron. Add it to the crontab:
```bash
ANTHROPIC_API_KEY=sk-ant-...
```

**Option B — Claude Code Cloud Routines**

```bash
# In Claude Code:
/schedule "cd /path/to/finvizCrawl && ./monitor/scripts/run-daily.sh" daily at 7:30am
/schedule "cd /path/to/finvizCrawl && ./monitor/scripts/run-weekly.sh" weekly on saturday at 9am
```

**Option C — Claude Desktop / Cowork Scheduled Tasks**

Use `/schedule` in the Cowork tab. Note: requires Mac to be awake and app open.

## Usage

### Daily workflow

Most days, the daily report will say "no material changes, thesis intact" — this is by design. You scan it in 30 seconds and move on. When something matters, the report will be longer and may fire a TRIGGER.

### On-demand deep analysis

If a daily sentinel fires `TRIGGER DEEP ANALYSIS`, or you want a fresh deep dive for any reason:

```bash
./monitor/scripts/run-weekly.sh AAPL
```

This works any day of the week — it's not restricted to weekends.

### Reading the ledger

```bash
# Last 10 days of metrics
python3 monitor/scripts/ledger_manager.py tail monitor/reports/AAPL/ledger.jsonl 10

# Trend summary
python3 monitor/scripts/ledger_manager.py summary monitor/reports/AAPL/ledger.jsonl 30

# Find trigger alerts from last week
python3 monitor/scripts/ledger_manager.py triggers monitor/reports/AAPL/ 2026-06-15
```

### Querying the ledger with jq

```bash
# Price trajectory
cat monitor/reports/AAPL/ledger.jsonl | jq -r '[.date, .price, .verdict] | @tsv'

# Days where verdict changed
cat monitor/reports/AAPL/ledger.jsonl | jq -s '
  [range(1; length)] |
  map(select(.[.] as $curr | .[. - 1] as $prev |
    ($curr.verdict != $prev.verdict)))
' < monitor/reports/AAPL/ledger.jsonl

# Action zone drift over time
cat monitor/reports/AAPL/ledger.jsonl | jq -r '[.date, .action_zones.buy_below, .action_zones.trim_above, .price] | @tsv'

# All days stock was in accumulate zone
cat monitor/reports/AAPL/ledger.jsonl | jq -r 'select(.price < .action_zones.accumulate_range[1]) | [.date, .price, .action_zones.accumulate_range[1]] | @tsv'

# Sentiment trajectory
cat monitor/reports/AAPL/ledger.jsonl | jq -r '[.date, .sentiment] | @tsv'
```

### Plotting (quick matplotlib)

```python
import json
import matplotlib.pyplot as plt

entries = []
with open("monitor/reports/AAPL/ledger.jsonl") as f:
    for line in f:
        entries.append(json.loads(line))

dates = [e["date"] for e in entries]
prices = [e["price"] for e in entries]
buy_below = [e["action_zones"]["buy_below"] for e in entries]
trim_above = [e["action_zones"]["trim_above"] for e in entries]
acc_low = [e["action_zones"]["accumulate_range"][0] for e in entries]
acc_high = [e["action_zones"]["accumulate_range"][1] for e in entries]

plt.figure(figsize=(14, 7))
plt.fill_between(dates, buy_below, acc_high, alpha=0.15, color="green", label="Accumulate zone")
plt.fill_between(dates, acc_high, trim_above, alpha=0.1, color="gray", label="Hold zone")
plt.plot(dates, prices, "k-", linewidth=2, label="Price")
plt.plot(dates, buy_below, "g--", alpha=0.5, label="Buy Below")
plt.plot(dates, trim_above, "r--", alpha=0.5, label="Trim Above")
plt.xticks(rotation=45)
plt.legend()
plt.title("AAPL — Price vs Action Zones Over Time")
plt.tight_layout()
plt.savefig("monitor/reports/AAPL/zone-chart.png")
```

## Customization

### Adding/removing SME panelists

Edit `prompts/weekly-deep-panel.md`, section "STEP 3 — SME PANEL". Add or remove expert definitions. Keep the rules section intact.

For a faster weekly run, reduce to 3 SMEs: Value Investor, Momentum Analyst, Risk Manager.

### Changing action zone methodology

Edit `prompts/daily-sentinel.md`, section "STEP 2 — ACTION ZONE PRICING". The current derivation uses P/E × EPS, P/B, and analyst targets. Swap in DCF, relative valuation, or whatever method suits your style.

### Ad hoc ticker runs

By default the monitor reads tickers from root `config.yaml`. For one-off runs, pass tickers directly:

```bash
./monitor/scripts/run-daily.sh AAPL NVDA IONQ PLTR
```

### Adjusting trigger sensitivity

In `prompts/daily-sentinel.md`, the trigger fires on big moves, volume spikes, etc. Tune the thresholds (currently >3% price move, >2x volume) in the STEP 4 / STEP 5 sections of the prompt.

## What this is NOT

- **Not financial advice.** Every report includes this disclaimer. The system is a research tool.
- **Not real-time.** It runs on scraped daily data. Don't use it for intraday decisions.
- **Not a trading bot.** It produces thesis and analysis, not trade orders.

## Costs

Each daily sentinel run: ~1 API call per ticker (moderate token usage + 1-3 web searches).
Each weekly deep analysis: ~1 API call per ticker (heavier token usage + 5-10 web searches).
Rough estimate: monitoring 3 tickers daily + weekly ≈ 20-25 API calls/week.
