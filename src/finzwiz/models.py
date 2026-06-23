from __future__ import annotations

from typing import Any


def quote_schema(
    *,
    schema_version: str,
    ticker: str,
    source_url: str,
    fetched_at: str,
    company: dict[str, Any] | None,
    price: dict[str, Any] | None,
    snapshot_table: dict[str, str] | None,
    raw: str | None,
) -> dict[str, Any]:
    return {
        "schema_version": schema_version,
        "ticker": ticker,
        "source": {
            "name": "finviz",
            "url": source_url,
            "fetched_at": fetched_at,
        },
        "company": {
            "name": (company or {}).get("name"),
            "sector": (company or {}).get("sector"),
            "industry": (company or {}).get("industry"),
            "country": (company or {}).get("country"),
        },
        "price": {
            "value": (price or {}).get("value"),
            "change": (price or {}).get("change"),
            "change_percent": (price or {}).get("change_percent"),
        },
        "snapshot_table": snapshot_table or {},
        "raw": raw,
    }


def news_schema(
    *,
    schema_version: str,
    ticker: str,
    source_url: str,
    fetched_at: str,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    normalized_items: list[dict[str, Any]] = []
    for item in items:
        normalized_items.append(
            {
                "published_at": item.get("published_at"),
                "published_at_raw": item.get("published_at_raw"),
                "publisher": item.get("publisher"),
                "headline": item.get("headline"),
                "url": item.get("url"),
                "resolved_url": item.get("resolved_url"),
                "url_resolution_status": item.get("url_resolution_status"),
                "url_resolution_reason": item.get("url_resolution_reason"),
                "article_id": item.get("article_id"),
                "dedup_status": item.get("dedup_status"),
                "dedup_reason": item.get("dedup_reason"),
            }
        )
    return {
        "schema_version": schema_version,
        "ticker": ticker,
        "source": {
            "name": "finviz",
            "url": source_url,
            "fetched_at": fetched_at,
        },
        "items": normalized_items,
    }


def article_schema(
    *,
    schema_version: str,
    ticker: str,
    url: str,
    fetched_at: str,
    success: bool,
    method: str,
    error: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
    content: dict[str, Any] | None,
    links: list[str] | None,
) -> dict[str, Any]:
    metadata = metadata or {}
    content = content or {}
    return {
        "schema_version": schema_version,
        "ticker": ticker,
        "source": {
            "name": "article",
            "url": url,
            "fetched_at": fetched_at,
        },
        "extraction": {
            "method": method,
            "success": success,
            "error": error,
        },
        "metadata": {
            "title": metadata.get("title"),
            "byline": metadata.get("byline"),
            "published_at": metadata.get("published_at"),
            "site_name": metadata.get("site_name"),
            "language": metadata.get("language"),
        },
        "content": {
            "text": content.get("text"),
            "text_blocks": content.get("text_blocks"),
            "html": content.get("html"),
        },
    }


def manifest_schema(
    *,
    schema_version: str,
    ticker: str,
    run_date: str,
    started_at: str,
    finished_at: str,
    timezone: str,
    config: dict[str, Any],
    artifacts: dict[str, str],
    stats: dict[str, int],
    errors: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": schema_version,
        "ticker": ticker,
        "run_date": run_date,
        "started_at": started_at,
        "finished_at": finished_at,
        "timezone": timezone,
        "config": config,
        "artifacts": {
            "finviz_quote": artifacts.get("finviz_quote"),
            "finviz_news": artifacts.get("finviz_news"),
            "articles_dir": artifacts.get("articles_dir"),
            "dedup_file": artifacts.get("dedup_file"),
            "run_manifest": artifacts.get("run_manifest"),
        },
        "stats": {
            "news_links_total": stats.get("news_links_total", 0),
            "news_links_new": stats.get("news_links_new", 0),
            "news_links_skipped_recent": stats.get("news_links_skipped_recent", 0),
            "news_links_retry_failed": stats.get("news_links_retry_failed", 0),
            "articles_fetched_ok": stats.get("articles_fetched_ok", 0),
            "articles_failed": stats.get("articles_failed", 0),
        },
        "errors": errors,
    }
