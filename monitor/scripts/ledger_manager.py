#!/usr/bin/env python3
"""
Stock Monitor — Ledger Manager

Handles:
  - Extracting JSON metrics from daily sentinel reports
  - Appending to / reading from the per-ticker ledger.jsonl
  - Finding trigger alerts for weekly analysis
  - Generating trend summaries for prompt context

Usage:
  python3 ledger_manager.py extract  <report_file> <ledger_file>
  python3 ledger_manager.py tail     <ledger_file> [N]
  python3 ledger_manager.py triggers <reports_dir> [since_date]
  python3 ledger_manager.py summary  <ledger_file> [N]
"""

import json
import re
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path


def extract_ledger_json(report_text: str) -> dict | None:
    """
    Extract the LEDGER_ENTRY JSON block from a daily sentinel report.
    Looks for ```json LEDGER_ENTRY ... ``` or ```json\n{ ... }```
    """
    # Try labeled block first
    pattern = r'```json\s*LEDGER_ENTRY\s*\n(.*?)```'
    match = re.search(pattern, report_text, re.DOTALL)

    if not match:
        # Fall back to first JSON block that looks like a ledger entry
        pattern = r'```json\s*\n(\{.*?\})\s*```'
        match = re.search(pattern, report_text, re.DOTALL)

    if not match:
        # Last resort: find the first { ... } that contains "date" and "price"
        pattern = r'(\{[^{}]*"date"[^{}]*"price"[^{}]*\})'
        match = re.search(pattern, report_text, re.DOTALL)

    if not match:
        return None

    raw = match.group(1).strip()

    # Clean common issues
    raw = re.sub(r',\s*}', '}', raw)     # trailing commas
    raw = re.sub(r',\s*]', ']', raw)     # trailing commas in arrays
    raw = re.sub(r'//.*$', '', raw, flags=re.MULTILINE)  # line comments

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"ERROR: Failed to parse JSON: {e}", file=sys.stderr)
        print(f"Raw block:\n{raw[:500]}", file=sys.stderr)
        return None

    # Validate required fields
    required = ["date", "price", "verdict"]
    missing = [f for f in required if f not in data]
    if missing:
        print(f"WARNING: Missing required fields: {missing}", file=sys.stderr)

    return data


def append_to_ledger(entry: dict, ledger_path: str) -> bool:
    """Append a JSON entry to the ledger file. Prevents duplicate dates."""
    ledger = Path(ledger_path)
    ledger.parent.mkdir(parents=True, exist_ok=True)

    # Check for duplicate date
    if ledger.exists():
        existing_dates = set()
        with open(ledger, 'r') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        existing = json.loads(line)
                        existing_dates.add(existing.get("date"))
                    except json.JSONDecodeError:
                        continue

        if entry.get("date") in existing_dates:
            print(f"SKIP: Entry for {entry['date']} already exists in ledger",
                  file=sys.stderr)
            return False

    with open(ledger, 'a') as f:
        f.write(json.dumps(entry, separators=(',', ':')) + '\n')

    print(f"OK: Appended {entry['date']} to {ledger_path}")
    return True


def read_ledger_tail(ledger_path: str, n: int = 10) -> list[dict]:
    """Read last N entries from the ledger."""
    ledger = Path(ledger_path)
    if not ledger.exists():
        return []

    entries = []
    with open(ledger, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    return entries[-n:]


def format_ledger_for_prompt(entries: list[dict]) -> str:
    """Format ledger entries as readable context for the prompt."""
    if not entries:
        return "No prior ledger data available. This is the first run."

    lines = []
    lines.append(f"METRICS LEDGER — last {len(entries)} trading days:")
    lines.append("")

    for entry in entries:
        lines.append(json.dumps(entry, indent=None, separators=(',', ': ')))

    return '\n'.join(lines)


def find_trigger_alerts(reports_dir: str, since_date: str = None) -> list[dict]:
    """
    Scan daily reports for TRIGGER DEEP ANALYSIS alerts.
    Returns list of {date, file, excerpt}.
    """
    rdir = Path(reports_dir)
    if not rdir.exists():
        return []

    if since_date:
        cutoff = datetime.strptime(since_date, "%Y-%m-%d")
    else:
        cutoff = datetime.now() - timedelta(days=7)

    triggers = []
    daily_dir = rdir / "daily"
    if not daily_dir.exists():
        return []

    for f in sorted(daily_dir.glob("*.md")):
        # Extract date from filename (YYYY-MM-DD.md)
        try:
            file_date = datetime.strptime(f.stem, "%Y-%m-%d")
        except ValueError:
            continue

        if file_date < cutoff:
            continue

        content = f.read_text()
        if "TRIGGER DEEP ANALYSIS" in content.upper():
            # Extract the context around the trigger
            for line in content.split('\n'):
                if "TRIGGER" in line.upper():
                    triggers.append({
                        "date": f.stem,
                        "file": str(f),
                        "excerpt": line.strip()
                    })
                    break

    return triggers


def generate_trend_summary(entries: list[dict]) -> str:
    """
    Generate a human-readable trend summary from ledger entries.
    Useful for injecting into weekly analysis prompt.
    """
    if len(entries) < 2:
        return "Insufficient data for trend summary (need ≥2 days)."

    first = entries[0]
    last = entries[-1]
    n = len(entries)

    lines = []
    lines.append(f"TREND SUMMARY — {n} trading days ({first['date']} → {last['date']})")
    lines.append("")

    # Price
    p_start = first.get('price', 0)
    p_end = last.get('price', 0)
    if p_start and p_end:
        p_change = ((p_end - p_start) / p_start) * 100
        direction = "↑" if p_change > 0.5 else ("↓" if p_change < -0.5 else "→")
        lines.append(f"  Price: ${p_start:.2f} → ${p_end:.2f} ({p_change:+.1f}%) {direction}")

    # Track numeric fields
    tracked_fields = [
        ("fwd_pe", "Forward P/E"),
        ("pe", "P/E"),
        ("ps", "P/S"),
        ("rsi", "RSI"),
        ("short_float_pct", "Short Float %"),
        ("volume_vs_avg", "Vol vs Avg"),
        ("debt_equity", "Debt/Equity"),
        ("sentiment", "Sentiment"),
    ]

    for field, label in tracked_fields:
        vals = [e.get(field) for e in entries if e.get(field) is not None]
        if len(vals) >= 2:
            v_start = vals[0]
            v_end = vals[-1]
            change = v_end - v_start
            direction = "↑" if change > 0.05 else ("↓" if change < -0.05 else "→")
            lines.append(f"  {label}: {v_start} → {v_end} {direction}")

    # Verdict history
    verdicts = [e.get('verdict', '?') for e in entries]
    lines.append(f"\n  Verdict history: {' → '.join(verdicts)}")

    # Sentiment trajectory
    sents = [str(e.get('sentiment', '?')) for e in entries]
    lines.append(f"  Sentiment trajectory: {', '.join(sents)}")

    # Action zone drift
    zones_start = first.get('action_zones', {})
    zones_end = last.get('action_zones', {})
    if zones_start and zones_end:
        lines.append(f"\n  Zone drift:")
        for key in ['buy_below', 'trim_above']:
            vs = zones_start.get(key)
            ve = zones_end.get(key)
            if vs and ve:
                d = "↑" if ve > vs else ("↓" if ve < vs else "→")
                lines.append(f"    {key}: ${vs:.2f} → ${ve:.2f} {d}")

    return '\n'.join(lines)


# ── CLI ──────────────────────────────────────────────────────────────────────

def cmd_extract(args):
    """Extract JSON from report and append to ledger."""
    if len(args) < 2:
        print("Usage: ledger_manager.py extract <report_file> <ledger_file>",
              file=sys.stderr)
        sys.exit(1)

    report_file, ledger_file = args[0], args[1]
    report_text = Path(report_file).read_text()

    entry = extract_ledger_json(report_text)
    if entry is None:
        print("ERROR: Could not extract JSON from report.", file=sys.stderr)
        sys.exit(1)

    if not append_to_ledger(entry, ledger_file):
        sys.exit(0)  # Duplicate, not an error


def cmd_tail(args):
    """Print last N ledger entries as formatted context."""
    if len(args) < 1:
        print("Usage: ledger_manager.py tail <ledger_file> [N]", file=sys.stderr)
        sys.exit(1)

    ledger_file = args[0]
    n = int(args[1]) if len(args) > 1 else 10

    entries = read_ledger_tail(ledger_file, n)
    print(format_ledger_for_prompt(entries))


def cmd_triggers(args):
    """Find trigger alerts in daily reports."""
    if len(args) < 1:
        print("Usage: ledger_manager.py triggers <reports_dir> [since_date]",
              file=sys.stderr)
        sys.exit(1)

    reports_dir = args[0]
    since = args[1] if len(args) > 1 else None

    triggers = find_trigger_alerts(reports_dir, since)
    if not triggers:
        print("No trigger alerts found.")
    else:
        for t in triggers:
            print(f"  [{t['date']}] {t['excerpt']}")


def cmd_summary(args):
    """Generate trend summary from ledger."""
    if len(args) < 1:
        print("Usage: ledger_manager.py summary <ledger_file> [N]",
              file=sys.stderr)
        sys.exit(1)

    ledger_file = args[0]
    n = int(args[1]) if len(args) > 1 else 30

    entries = read_ledger_tail(ledger_file, n)
    print(generate_trend_summary(entries))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]
    cmd_args = sys.argv[2:]

    commands = {
        "extract": cmd_extract,
        "tail": cmd_tail,
        "triggers": cmd_triggers,
        "summary": cmd_summary,
    }

    if command not in commands:
        print(f"Unknown command: {command}", file=sys.stderr)
        print(f"Available: {', '.join(commands.keys())}", file=sys.stderr)
        sys.exit(1)

    commands[command](cmd_args)
