from __future__ import annotations

from finzwiz.models import article_schema, manifest_schema, news_schema, quote_schema


def test_quote_schema_fixed_keys() -> None:
    payload = quote_schema(
        schema_version="1.0",
        ticker="AAPL",
        source_url="https://finviz.com/quote.ashx?t=AAPL",
        fetched_at="2026-02-23T09:00:00-08:00",
        company=None,
        price=None,
        snapshot_table=None,
        raw=None,
    )
    assert list(payload.keys()) == [
        "schema_version",
        "ticker",
        "source",
        "company",
        "price",
        "snapshot_table",
        "raw",
    ]
    assert payload["company"]["name"] is None
    assert payload["price"]["value"] is None


def test_news_and_article_schema_null_placeholders() -> None:
    news = news_schema(
        schema_version="1.0",
        ticker="AAPL",
        source_url="u",
        fetched_at="t",
        items=[
            {
                "url": "https://x",
                "article_id": "abc",
            }
        ],
    )
    item = news["items"][0]
    assert "publisher" in item
    assert item["publisher"] is None
    assert "resolved_url" in item
    assert item["resolved_url"] is None
    assert "url_resolution_status" in item
    assert item["url_resolution_status"] is None

    article = article_schema(
        schema_version="1.0",
        ticker="AAPL",
        url="https://x",
        fetched_at="t",
        success=False,
        method="http",
        error=None,
        metadata=None,
        content=None,
        links=None,
    )
    assert article["metadata"]["title"] is None
    assert article["content"]["text"] is None
    assert article["links"] == []


def test_manifest_schema_fixed_stats_keys() -> None:
    manifest = manifest_schema(
        schema_version="1.0",
        ticker="AAPL",
        run_date="2026-02-23",
        started_at="s",
        finished_at="f",
        timezone="America/Los_Angeles",
        config={},
        artifacts={},
        stats={},
        errors=[],
    )
    assert list(manifest["stats"].keys()) == [
        "news_links_total",
        "news_links_new",
        "news_links_skipped_recent",
        "news_links_retry_failed",
        "articles_fetched_ok",
        "articles_failed",
    ]
