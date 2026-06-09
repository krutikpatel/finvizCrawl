from __future__ import annotations

import argparse

from .run import run_scrape
from .sentiment import run_sentiment


def main() -> None:
    parser = argparse.ArgumentParser(prog="finzwiz")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scrape = subparsers.add_parser("scrape", help="Scrape one ticker from Finviz")
    scrape.add_argument("--ticker", required=True, help="Stock ticker symbol")
    scrape.add_argument("--config", default="config.yaml", help="Config path")
    scrape.add_argument("--force", action="store_true", help="Force re-fetch of recent URLs")

    analyze = subparsers.add_parser("analyze", help="Analyze sentiment of crawled articles")
    analyze.add_argument("--ticker", required=True, help="Stock ticker symbol")
    analyze.add_argument("--config", default="config.yaml", help="Config path")
    analyze.add_argument(
        "--date",
        default=None,
        metavar="YYYY-MM-DD",
        help="Run date to analyze (defaults to today Pacific)",
    )

    args = parser.parse_args()
    if args.command == "scrape":
        exit_code = run_scrape(ticker=args.ticker, config_path=args.config, force=args.force)
        raise SystemExit(exit_code)
    if args.command == "analyze":
        exit_code = run_sentiment(ticker=args.ticker, config_path=args.config, run_date=args.date)
        raise SystemExit(exit_code)

    raise SystemExit(2)


if __name__ == "__main__":
    main()
