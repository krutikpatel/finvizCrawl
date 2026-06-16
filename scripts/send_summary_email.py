#!/usr/bin/env python3
"""Send finzwiz daily summary email via Gmail SMTP.

Credentials are read from macOS Keychain — never stored in plaintext.
One-time setup:
  security add-generic-password -a "<your@gmail.com>" -s "finzwiz-smtp" -w "<app-password>"
  (App passwords: https://myaccount.google.com/apppasswords — requires 2FA)
"""
from __future__ import annotations

import argparse
import json
import smtplib
import subprocess
import sys
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path
from zoneinfo import ZoneInfo

PACIFIC_TZ = ZoneInfo("America/Los_Angeles")


def _keychain_password(account: str) -> str:
    result = subprocess.run(
        ["security", "find-generic-password", "-a", account, "-s", "finzwiz-smtp", "-w"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Gmail app password not found in Keychain for {account}.\n"
            f"Run once to store it:\n"
            f"  security add-generic-password -a '{account}' -s 'finzwiz-smtp' -w '<app-password>'\n"
            f"Get an app password at: https://myaccount.google.com/apppasswords"
        )
    return result.stdout.strip()


def _load_summary(data_root: Path, ticker: str) -> dict:
    path = data_root / ticker / "sentiment_summary.json"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _build_body(tickers: list[str], date: str, data_root: Path) -> str:
    now = datetime.now(PACIFIC_TZ).strftime("%Y-%m-%d %H:%M PT")
    lines: list[str] = [
        f"finzwiz Daily Summary — {now}",
        "=" * 48,
        "",
    ]

    for ticker in tickers:
        summary = _load_summary(data_root, ticker)
        if not summary:
            lines += [f"{ticker} — no data available", ""]
            continue

        sentiment = summary.get("overall_sentiment", "?")
        score = summary.get("overall_score_avg", 0.0)
        total = summary.get("total_analyzed", 0)
        dist = summary.get("sentiment_distribution", {})
        bullish = dist.get("bullish", 0)
        neutral = dist.get("neutral", 0)
        bearish = dist.get("bearish", 0)

        lines.append(f"{ticker} — {sentiment} ({score:+.2f})")
        lines.append(
            f"  {total} articles total  |  "
            f"{bullish} bullish  {neutral} neutral  {bearish} bearish"
        )

        by_date = summary.get("by_date", [])
        today_entry = next((d for d in by_date if d.get("date") == date), None)
        if today_entry:
            new_count = today_entry.get("articles_analyzed", 0)
            lines.append(f"  Today: {new_count} articles analyzed")
            top = today_entry.get("top_headlines", [])[:3]
            if top:
                lines.append("  Top stories:")
                for h in top:
                    score_tag = f"{h.get('score', 0.0):+.1f}"
                    headline = (h.get("headline") or "")[:75]
                    publisher = (h.get("publisher") or "").strip("()")
                    suffix = f"  ({publisher})" if publisher else ""
                    lines.append(f"    [{score_tag}] {headline}{suffix}")

        lines.append("")

    lines += [
        "-" * 48,
        f"Data:  {data_root.resolve()}",
        "Sent by finzwiz workflow",
    ]
    return "\n".join(lines)


def _build_subject(tickers: list[str], date: str, data_root: Path) -> str:
    parts: list[str] = []
    for ticker in tickers[:5]:
        s = _load_summary(data_root, ticker)
        if s:
            sentiment = s.get("overall_sentiment", "?")
            score = s.get("overall_score_avg", 0.0)
            parts.append(f"{ticker} {sentiment} ({score:+.2f})")
    overview = ", ".join(parts) if parts else "no data"
    suffix = f" +{len(tickers) - 5} more" if len(tickers) > 5 else ""
    return f"[finzwiz] {date} — {overview}{suffix}"


def send_email(*, to: str, tickers: list[str], date: str, data_root: Path) -> None:
    password = _keychain_password(to)
    body = _build_body(tickers, date, data_root)
    subject = _build_subject(tickers, date, data_root)

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = to
    msg["To"] = to

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.ehlo()
        server.starttls()
        server.login(to, password)
        server.send_message(msg)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--to", required=True, help="Gmail address (sender and recipient)")
    parser.add_argument("--tickers", required=True, help="Space-separated ticker list")
    parser.add_argument("--date", required=True, help="Run date YYYY-MM-DD")
    parser.add_argument("--data-dir", default="data", help="Root data directory")
    args = parser.parse_args()

    tickers = args.tickers.split()
    data_root = Path(args.data_dir)

    try:
        send_email(to=args.to, tickers=tickers, date=args.date, data_root=data_root)
        print(f"Email sent to {args.to}")
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
