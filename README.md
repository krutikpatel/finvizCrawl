# finzwiz

Single-ticker CLI that scrapes Finviz, fetches linked news articles, and runs Claude-powered sentiment analysis — producing structured JSON outputs ready for LLM pipelines.

## Setup

```bash
make install          # creates .venv and installs all dependencies
```

Sentiment analysis runs via the **Claude Code CLI** — no separate Anthropic API key required (uses your Claude Code subscription). Make sure `claude` is accessible in your PATH (`which claude` should return a path).

## Commands

### Scrape

Fetches the Finviz quote page and up to 5 eligible linked news articles for one ticker:

```bash
PYTHONPATH=src .venv/bin/python -m finzwiz.cli scrape --ticker AAPL
```

| Flag | Default | Description |
|---|---|---|
| `--ticker` | required | Stock ticker, normalized to uppercase |
| `--config` | `config.yaml` | Path to config file |
| `--force` | off | Re-fetch articles even if successfully scraped within the last 15 days |

**Exit codes:** `0` success · `2` bad input/config · `10+` fatal (quote page fetch failed, no articles processed)

### Analyze

Runs Claude sentiment analysis on articles from a scrape run. Only articles not yet analyzed are processed — already-analyzed articles are skipped every time:

```bash
PYTHONPATH=src .venv/bin/python -m finzwiz.cli analyze --ticker AAPL
```

| Flag | Default | Description |
|---|---|---|
| `--ticker` | required | Stock ticker |
| `--config` | `config.yaml` | Path to config file |
| `--date` | today (Pacific) | Analyze a specific past run date, e.g. `2026-06-07` |

**Exit codes:** `0` success · `2` bad input · `10` no scrape data found for that date

### Typical daily workflow

```bash
PYTHONPATH=src .venv/bin/python -m finzwiz.cli scrape --ticker AAPL
PYTHONPATH=src .venv/bin/python -m finzwiz.cli analyze --ticker AAPL
```

## Output files

All files are written under the `data/` directory (configurable via `config.yaml`).

### Per-run outputs (under `data/<TICKER>/<YYYY-MM-DD>/`)

| File | Description |
|---|---|
| `finviz_quote.json` | Parsed Finviz quote page: company info, price, full snapshot table |
| `finviz_news.json` | All news links found on the quote page with dedup status per URL |
| `articles/<ARTICLE_ID>.json` | Extracted article text and metadata for up to `articles.max_articles_per_ticker` eligible articles; `<ARTICLE_ID>` is `sha256(url)[:24]` |
| `run_manifest.json` | Run stats, artifact paths, and any errors for this run |

### Per-ticker persistent files (under `data/<TICKER>/`)

| File | Description |
|---|---|
| `seen_urls.jsonl` | Dedup log — one record per URL, tracks fetch status and timestamps across runs |
| `sentiment_log.jsonl` | **Growing log** — one record per analyzed article, never overwritten, keyed by `article_id` |
| `sentiment_summary.json` | **Aggregated view** — regenerated each `analyze` run; shows overall and per-date sentiment |

### sentiment_log.jsonl record

Each line is a JSON object:

```json
{
  "article_id": "3f8a1b2c...",
  "ticker": "AAPL",
  "run_date": "2026-06-08",
  "analyzed_at": "2026-06-08T09:14:22-07:00",
  "headline": "Apple announces new chip...",
  "publisher": "Reuters",
  "url": "https://...",
  "sentiment": "bullish",
  "score": 0.75,
  "summary": "Apple's new chip delivers 30% performance gains, signaling strong product cycle ahead.",
  "analysis_error": null
}
```

`score` ranges from `-1.0` (very bearish) to `1.0` (very bullish).

### sentiment_summary.json

Aggregated view rebuilt after every `analyze` run:

```json
{
  "schema_version": "1.0",
  "ticker": "AAPL",
  "generated_at": "2026-06-08T09:15:00-07:00",
  "total_analyzed": 87,
  "overall_sentiment": "bullish",
  "overall_score_avg": 0.42,
  "by_date": [
    {
      "date": "2026-06-08",
      "articles_analyzed": 12,
      "sentiment": "bullish",
      "score_avg": 0.55,
      "top_headlines": [...]
    }
  ]
}
```

`by_date` is sorted newest-first. `top_headlines` contains up to 5 articles with the highest absolute score for that day.

## Automated twice-daily workflow (macOS)

`scripts/workflow.sh` runs the scrape workflow for one or more tickers. Optional article sentiment analysis is controlled by `sentiment.enabled` in `config.yaml`. It is designed to be called headlessly by the macOS `launchd` scheduler.

### How it works

1. Loops over `$FINZWIZ_TICKERS` (space-separated, default `TSLA`).
2. Runs `finzwiz scrape --ticker <TICKER>` for each ticker.
3. If `sentiment.enabled: true`, calls `claude --print` once per ticker with article data embedded directly in the prompt. If `sentiment.enabled: false`, no article text is sent to Claude/Codex.
4. Logs everything to `logs/workflow-YYYY-MM-DD.log`.

When enabled, the analysis step uses the `claude` CLI at `/opt/homebrew/bin/claude` with `--model` set from `sentiment.model` in `config.yaml` — **no `ANTHROPIC_API_KEY` required**.

### Management commands

```bash
make workflow-install     # register the launchd job (runs at 8 AM + 4 PM local time)
make workflow-uninstall   # remove the launchd job
make workflow-status      # check whether the job is currently registered
make workflow-logs        # tail today's workflow log
make run-workflow         # run the full workflow right now (foreground, for testing)
```

Or use the helper script directly:

```bash
./scripts/manage_workflow.sh install
./scripts/manage_workflow.sh uninstall
./scripts/manage_workflow.sh run
./scripts/manage_workflow.sh status
./scripts/manage_workflow.sh logs
```

### Schedule

The launchd plist (`scripts/com.finzwiz.workflow.plist`) fires at **8:00 AM and 4:00 PM system local time**. It is installed to `~/Library/LaunchAgents/com.finzwiz.workflow.plist`.

If the Mac is asleep at a scheduled time, launchd **will not** run missed jobs automatically — the next scheduled slot will trigger instead. To run a missed execution manually: `make run-workflow`.

### Adding tickers

Edit the `FINZWIZ_TICKERS` value in `scripts/com.finzwiz.workflow.plist`:

```xml
<key>FINZWIZ_TICKERS</key>
<string>TSLA AAPL META MU ENPH HOOD ORCL GOOG MSFT</string>
```

Then reload: `make workflow-install`.

Alternatively, pass the env var for a one-off run:

```bash
FINZWIZ_TICKERS="TSLA NVDA" make run-workflow
```

### Log files

| File | Contents |
|---|---|
| `logs/workflow-YYYY-MM-DD.log` | Timestamped per-run output — scrape results + Claude analysis summary |
| `logs/launchd.log` | Raw stdout/stderr captured by launchd for the scheduled executions |

### Email summary (optional)

After each run the workflow can email you a plain-text summary — overall sentiment, score, article counts, and top headlines per ticker.

**One-time setup (requires Gmail + 2FA):**

1. Create a Gmail App Password at <https://myaccount.google.com/apppasswords>.
2. Store it in macOS Keychain:

```bash
make setup-email EMAIL=you@gmail.com
# or manually:
security add-generic-password -a "you@gmail.com" -s "finzwiz-smtp" -w "<app-password>"
```

3. Enable email delivery by uncommenting `FINZWIZ_EMAIL` in the plist:

```xml
<!-- scripts/com.finzwiz.workflow.plist -->
<key>FINZWIZ_EMAIL</key>
<string>you@gmail.com</string>
```

Then reload: `make workflow-install`.

For a one-off test:

```bash
FINZWIZ_EMAIL=you@gmail.com make run-workflow
# or call the script directly:
.venv/bin/python scripts/send_summary_email.py \
    --to you@gmail.com \
    --tickers "TSLA AAPL" \
    --date 2026-06-08 \
    --data-dir data
```

The email is skipped silently when `FINZWIZ_EMAIL` is unset.

## Stock monitor system (`monitor/`)

A complete, self-contained investment monitoring system that sits on top of the scraper. Where the workflow above tracks article-level sentiment, the monitor tracks the **stock itself** over time — building a persistent ledger of daily metrics, maintaining concrete buy/hold/trim price zones, and running progressively deeper analysis on a weekly cadence.

All files live under `monitor/`. The system is independent: it reads the scraper's `finviz_quote.json` outputs but has its own config, prompts, scripts, reports, and launchd job.

### Two analysis tiers

**Daily sentinel** (`monitor/scripts/run-daily.sh`) — runs every weekday at 9 AM:

1. Reads the latest `data/<TICKER>/<YYYY-MM-DD>/finviz_quote.json` for each ticker.
2. Loads the last 10 days from `monitor/reports/<TICKER>/ledger.jsonl` for trend context, plus the most recent weekly deep analysis as the baseline.
3. Calls `claude -p` with the sentinel prompt, which outputs:
   - A machine-readable `LEDGER_ENTRY` JSON block (price, ~40 metrics, action zones, sentiment score, verdict).
   - A scannable brief: metric trend tables, action zone positioning, 24-hour news scan, and a zone-relative verdict.
4. `ledger_manager.py` extracts the JSON and appends it to `ledger.jsonl` (duplicate-date safe).
5. Report saved to `monitor/reports/<TICKER>/daily/YYYY-MM-DD.md`.
6. If Claude flags `TRIGGER DEEP ANALYSIS` (earnings surprise, guidance change, technical breakdown, etc.), the log surfaces it and prompts a manual weekly run before the next scheduled one.

**Weekly deep panel** (`monitor/scripts/run-weekly.sh`) — run manually or on a trigger:

1. Feeds the full 30-day ledger, auto-generated trend summary, prior weekly analysis, and any trigger alerts into a 5-SME panel prompt.
2. Each expert reasons independently from their domain lens with stated confidence:
   - **Value Investor** — moat, margin of safety, intrinsic value estimate
   - **Growth / Momentum Analyst** — earnings trajectory, price action, institutional flows
   - **Quant / Technical Analyst** — RSI, SMA structure, risk/reward ratio at current zones
   - **Risk Manager** — downside scenarios, balance-sheet fragility, thesis-breaking risks
   - **Sector / Macro Specialist** — uses web search for current sector dynamics, macro context, peer comparison
3. A structured debate round surfaces the 2–3 sharpest SME disagreements and what data would resolve them.
4. Action zones are formally recalibrated with derivation shown (which multiple × which estimate = which price).
5. Lead analyst synthesizes a weighted verdict with upgrade/downgrade triggers for the coming week.
6. Report saved to `monitor/reports/<TICKER>/weekly/YYYY-MM-DD.md`.

The two tiers build on each other: the daily sentinel carries the weekly zones forward and flags when they need revisiting; the weekly panel uses the daily ledger as its trend backbone.

### Getting started

```bash
make monitor-install          # register the daily launchd job (9 AM weekdays)
./monitor/scripts/run-daily.sh AAPL    # test a single ticker now
./monitor/scripts/run-weekly.sh AAPL   # run the first weekly deep panel
```

### Management commands

```bash
make monitor-install      # register and enable the launchd job
make monitor-uninstall    # stop and remove the launchd job
make monitor-status       # check whether the job is loaded
make monitor-logs         # tail today's sentinel log
make run-monitor          # run the daily sentinel right now (foreground)
```

Or call the helper directly:

```bash
./monitor/manage_monitor.sh install | uninstall | run | status | logs
```

### Schedule

| Job | Schedule | plist |
|---|---|---|
| Daily sentinel | 9:00 AM local time, Mon–Fri | `monitor/com.finzwiz.monitor.plist` → `~/Library/LaunchAgents/` |
| Weekly deep panel | Manual, or triggered by sentinel | `./monitor/scripts/run-weekly.sh` |

The 9 AM daily time is intentionally one hour after the 8 AM scrape so `finviz_quote.json` is always ready. Missed runs are not retried automatically — use `make run-monitor` to catch up.

### Configuration

Edit `monitor/config.env`:

| Field | Default | Description |
|---|---|---|
| `WATCHLIST` | all 9 tickers | Space-separated tickers to monitor |
| `LEDGER_LOOKBACK` | `10` | Days of ledger history fed into daily context |
| `WEEKLY_LEDGER_LOOKBACK` | `30` | Days of ledger history fed into weekly context |
| `AUTO_GIT_COMMIT` | `true` | Auto-commit reports to git after each run |

To add or remove tickers, edit `WATCHLIST` in `monitor/config.env` — no plist reload needed.

### Output files

All outputs land under `monitor/reports/<TICKER>/`:

| File | Description |
|---|---|
| `daily/YYYY-MM-DD.md` | Daily sentinel report — metric trends, action zones, news scan, verdict |
| `weekly/YYYY-MM-DD.md` | Weekly deep panel — SME debate, zone recalibration, weighted synthesis |
| `ledger.jsonl` | Persistent metrics ledger — one JSON record per trading day, ~40 fields |

### Log files

| File | Contents |
|---|---|
| `logs/monitor-YYYY-MM-DD.log` | Timestamped per-run output (tailed by `make monitor-logs`) |
| `logs/monitor-launchd.log` | Raw stdout/stderr captured by launchd |

## Configuration

Key fields in `config.yaml`:

| Field | Default | Description |
|---|---|---|
| `dedup.retention_days` | `15` | Skip re-fetching articles seen successfully within this window |
| `scraping.max_concurrency` | `5` | Parallel article fetch threads |
| `scraping.delay_seconds` | `1` | Per-thread delay before each article fetch |
| `scraping.user_agent` | Chrome UA | Browser UA string sent with every request |
| `articles.max_articles_per_ticker` | `5` | Maximum article bodies fetched per ticker per scrape run |
| `articles.max_text_chars` | `0` (no limit) | Truncate extracted article text to this length |
| `sentiment.enabled` | `false` | Send new article excerpts to Claude for workflow sentiment scoring |
| `sentiment.model` | `claude-haiku-4-5-20251001` | Claude model used for analysis |
| `sentiment.max_articles_per_batch` | `20` | Articles sent per Claude API call |

## Dedup and retry behavior

- Successful articles (fetched within 15 days): **skipped** unless `--force`
- Failed articles (fetched within 15 days): **retried** automatically
- Older than 15 days: always re-fetched
- Sentiment analysis: once an `article_id` appears in `sentiment_log.jsonl` it is **never re-analyzed**, regardless of `--force` or `--date`
