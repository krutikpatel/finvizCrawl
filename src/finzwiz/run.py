from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .articles.http import HttpArticleFetcher
from .config import ConfigError, config_to_dict, load_config
from .dedup import DedupStore, article_id_from_url
from .models import article_schema, manifest_schema, news_schema, quote_schema
from .providers.finviz_http import HttpFinvizProvider, QuoteParseError
from .storage import ensure_dir, write_json_atomic
from .urls import resolve_news_url

PACIFIC_TZ = ZoneInfo("America/Los_Angeles")


def run_scrape(
    *,
    ticker: str,
    config_path: str,
    force: bool,
    quote_provider_cls=HttpFinvizProvider,
    article_fetcher_cls=HttpArticleFetcher,
) -> int:
    ticker = ticker.upper().strip()
    started_at = datetime.now(PACIFIC_TZ)
    run_date = started_at.date().isoformat()
    errors: list[dict] = []
    stats = {
        "news_links_total": 0,
        "news_links_new": 0,
        "news_links_skipped_recent": 0,
        "news_links_retry_failed": 0,
        "articles_fetched_ok": 0,
        "articles_failed": 0,
    }

    try:
        config = load_config(config_path)
    except ConfigError as exc:
        _print_error(str(exc))
        return 2

    data_root = Path(config.output.data_dir)
    run_dir = data_root / ticker / run_date
    articles_dir = run_dir / "articles"
    quote_path = run_dir / "finviz_quote.json"
    news_path = run_dir / "finviz_news.json"
    manifest_path = run_dir / "run_manifest.json"
    dedup_path = data_root / ticker / config.dedup.seen_urls_filename

    ensure_dir(articles_dir)
    dedup_store = DedupStore(dedup_path, retention_days=config.dedup.retention_days)

    provider = quote_provider_cls(config)
    article_fetcher = article_fetcher_cls(config)

    try:
        quote_data = provider.fetch_quote(ticker)
    except (QuoteParseError, Exception) as exc:
        errors.append(
            {
                "type": "quote_error",
                "message": str(exc),
                "context": {"ticker": ticker},
            }
        )
        finished_at = datetime.now(PACIFIC_TZ)
        _write_manifest(
            manifest_path=manifest_path,
            config=config,
            ticker=ticker,
            run_date=run_date,
            started_at=started_at,
            finished_at=finished_at,
            stats=stats,
            errors=errors,
            quote_path=quote_path,
            news_path=news_path,
            articles_dir=articles_dir,
            dedup_path=dedup_path,
        )
        _print_error(f"Failed to fetch/parse Finviz quote page: {exc}")
        return 10

    quote_payload = quote_schema(
        schema_version=config.project.schema_version,
        ticker=ticker,
        source_url=quote_data.source_url,
        fetched_at=quote_data.fetched_at,
        company=quote_data.company,
        price=quote_data.price,
        snapshot_table=quote_data.snapshot_table,
        raw=quote_data.raw,
    )
    write_json_atomic(quote_path, quote_payload, pretty=config.output.pretty_json)

    now = datetime.now(PACIFIC_TZ)
    news_items = []
    fetch_jobs: list[tuple[dict, str, str]] = []
    url_decisions: dict[str, tuple[str, str, str, bool]] = {}
    processed_resolved_urls: set[str] = set()
    for item in quote_data.news_items:
        stats["news_links_total"] += 1
        raw_url = item.url
        resolution = resolve_news_url(raw_url, quote_data.source_url)
        resolved_url = resolution.resolved_url

        if resolved_url is None:
            article_id = article_id_from_url(raw_url)
            decision_status = "invalid_url"
            decision_reason = resolution.reason or "invalid_url"
            decision_fetch = False
            errors.append(
                {
                    "type": "url_resolution_error",
                    "message": "News URL could not be resolved to fetchable absolute URL",
                    "context": {
                        "ticker": ticker,
                        "url": raw_url,
                        "reason": decision_reason,
                    },
                }
            )
        elif resolved_url in url_decisions:
            article_id, decision_status, decision_reason, decision_fetch = url_decisions[resolved_url]
        else:
            article_id = article_id_from_url(resolved_url)
            decision = dedup_store.decide(url=resolved_url, now=now, force=force)
            decision_status = decision.status
            decision_reason = decision.reason
            decision_fetch = decision.fetch
            url_decisions[resolved_url] = (article_id, decision_status, decision_reason, decision_fetch)

        if decision_status in {"new", "forced"}:
            stats["news_links_new"] += 1
        elif decision_status == "skipped_recent":
            stats["news_links_skipped_recent"] += 1
        elif decision_status == "retry_failed_recent":
            stats["news_links_retry_failed"] += 1

        news_entry = {
            "published_at": item.published_at,
            "published_at_raw": item.published_at_raw,
            "publisher": item.publisher,
            "headline": item.headline,
            "url": raw_url,
            "resolved_url": resolved_url,
            "url_resolution_status": resolution.status,
            "url_resolution_reason": resolution.reason,
            "article_id": article_id,
            "dedup_status": decision_status,
            "dedup_reason": decision_reason,
        }
        news_items.append(news_entry)

        if resolved_url and decision_fetch and resolved_url not in processed_resolved_urls:
            fetch_jobs.append((news_entry, resolved_url, article_id))
            processed_resolved_urls.add(resolved_url)
        else:
            if (
                resolved_url
                and decision_status == "skipped_recent"
                and resolved_url not in processed_resolved_urls
            ):
                dedup_store.update(
                    url=resolved_url,
                    article_id=article_id,
                    now=now,
                    fetch_status="skipped_recent",
                    http_status=None,
                    note=decision_reason,
                )
                processed_resolved_urls.add(resolved_url)

    news_payload = news_schema(
        schema_version=config.project.schema_version,
        ticker=ticker,
        source_url=quote_data.source_url,
        fetched_at=datetime.now(PACIFIC_TZ).isoformat(),
        items=news_items,
    )
    write_json_atomic(news_path, news_payload, pretty=config.output.pretty_json)

    with ThreadPoolExecutor(max_workers=config.scraping.max_concurrency) as pool:
        futures = {
            pool.submit(article_fetcher.fetch, fetch_url): (entry, fetch_url, article_id)
            for entry, fetch_url, article_id in fetch_jobs
        }
        for future in as_completed(futures):
            entry, fetch_url, article_id = futures[future]
            result = future.result()
            article_payload = article_schema(
                schema_version=config.project.schema_version,
                ticker=ticker,
                url=fetch_url,
                fetched_at=datetime.now(PACIFIC_TZ).isoformat(),
                success=result.success,
                method="http",
                error=result.error,
                metadata=result.metadata,
                content=result.content,
                links=result.links,
            )
            article_path = articles_dir / f"{article_id}.json"
            write_json_atomic(article_path, article_payload, pretty=config.output.pretty_json)

            if result.success:
                stats["articles_fetched_ok"] += 1
                dedup_store.update(
                    url=fetch_url,
                    article_id=article_id,
                    now=datetime.now(PACIFIC_TZ),
                    fetch_status="fetched_ok",
                    http_status=result.http_status,
                    note=None,
                )
            else:
                stats["articles_failed"] += 1
                err = result.error or {
                    "type": "parse_error",
                    "message": "Unknown article parsing error",
                    "context": {"url": fetch_url},
                }
                errors.append(err)
                dedup_store.update(
                    url=fetch_url,
                    article_id=article_id,
                    now=datetime.now(PACIFIC_TZ),
                    fetch_status="fetched_failed",
                    http_status=result.http_status,
                    note=err.get("message"),
                )

    dedup_store.flush()
    finished_at = datetime.now(PACIFIC_TZ)
    _write_manifest(
        manifest_path=manifest_path,
        config=config,
        ticker=ticker,
        run_date=run_date,
        started_at=started_at,
        finished_at=finished_at,
        stats=stats,
        errors=errors,
        quote_path=quote_path,
        news_path=news_path,
        articles_dir=articles_dir,
        dedup_path=dedup_path,
    )

    return 0


def _write_manifest(
    *,
    manifest_path: Path,
    config,
    ticker: str,
    run_date: str,
    started_at: datetime,
    finished_at: datetime,
    stats: dict,
    errors: list[dict],
    quote_path: Path,
    news_path: Path,
    articles_dir: Path,
    dedup_path: Path,
) -> None:
    manifest_payload = manifest_schema(
        schema_version=config.project.schema_version,
        ticker=ticker,
        run_date=run_date,
        started_at=started_at.isoformat(),
        finished_at=finished_at.isoformat(),
        timezone="America/Los_Angeles",
        config=config_to_dict(config),
        artifacts={
            "finviz_quote": str(quote_path),
            "finviz_news": str(news_path),
            "articles_dir": str(articles_dir),
            "dedup_file": str(dedup_path),
            "run_manifest": str(manifest_path),
        },
        stats=stats,
        errors=errors,
    )
    write_json_atomic(manifest_path, manifest_payload, pretty=config.output.pretty_json)


def _print_error(message: str) -> None:
    print(message, file=sys.stderr)
