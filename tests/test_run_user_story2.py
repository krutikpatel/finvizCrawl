from __future__ import annotations

import json
from pathlib import Path

from finzwiz.articles.http import ArticleFetchResult
from finzwiz.providers.base import NewsItem, QuoteData
from finzwiz.run import run_scrape


def _write_config(path: Path, data_dir: Path) -> None:
    path.write_text(
        f"""
project:
  name: finzwiz
  schema_version: "1.0"
output:
  data_dir: "{data_dir}"
  pretty_json: true
dedup:
  retention_days: 15
  seen_urls_filename: "seen_urls.jsonl"
  compact_on_write: false
scraping:
  backend: "http"
  user_agent: "test-agent"
  timeout_seconds: 5
  retries: 0
  delay_seconds: 0
  max_concurrency: 5
  playwright:
    headless: true
articles:
  include_raw_html: false
  max_text_chars: 0
""".strip(),
        encoding="utf-8",
    )


def test_duplicate_urls_are_fetched_once_and_reported_per_item(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    cfg = tmp_path / "config.yaml"
    _write_config(cfg, data_dir)

    class FakeQuoteProvider:
        def __init__(self, _config) -> None:
            pass

        def fetch_quote(self, _ticker: str) -> QuoteData:
            duplicate_url = "https://example.com/a"
            return QuoteData(
                source_url="https://finviz.com/quote.ashx?t=TEST",
                fetched_at="2026-02-23T10:00:00-08:00",
                company={"name": "Test", "sector": None, "industry": None, "country": None},
                price={"value": 1.0, "change": 0.0, "change_percent": 0.0},
                snapshot_table={"P/E": "10"},
                news_items=[
                    NewsItem(None, "10:00AM", "pub", "headline1", duplicate_url),
                    NewsItem(None, "10:01AM", "pub", "headline2", duplicate_url),
                ],
                raw=None,
            )

    class FakeArticleFetcher:
        calls = 0

        def __init__(self, _config) -> None:
            pass

        def fetch(self, url: str) -> ArticleFetchResult:
            FakeArticleFetcher.calls += 1
            return ArticleFetchResult(
                success=True,
                http_status=200,
                metadata={
                    "title": "title",
                    "byline": None,
                    "published_at": None,
                    "site_name": "example.com",
                    "language": None,
                },
                content={"text": "text", "text_blocks": ["text"], "html": None},
                links=[url],
                error=None,
            )

    exit_code = run_scrape(
        ticker="TEST",
        config_path=str(cfg),
        force=False,
        quote_provider_cls=FakeQuoteProvider,
        article_fetcher_cls=FakeArticleFetcher,
    )
    assert exit_code == 0
    assert FakeArticleFetcher.calls == 1

    run_dirs = sorted(path for path in (data_dir / "TEST").iterdir() if path.is_dir())
    assert run_dirs
    news_path = run_dirs[-1] / "finviz_news.json"
    manifest_path = run_dirs[-1] / "run_manifest.json"

    with news_path.open("r", encoding="utf-8") as handle:
        news_payload = json.load(handle)
    assert len(news_payload["items"]) == 2
    assert news_payload["items"][0]["dedup_status"] == "new"
    assert news_payload["items"][1]["dedup_status"] == "new"
    assert news_payload["items"][0]["resolved_url"] == "https://example.com/a"
    assert news_payload["items"][0]["url_resolution_status"] == "already_absolute"

    with manifest_path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    assert manifest["stats"]["news_links_total"] == 2
    assert manifest["stats"]["articles_fetched_ok"] == 1


def test_relative_urls_resolve_and_dedup_on_resolved_url(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    cfg = tmp_path / "config.yaml"
    _write_config(cfg, data_dir)

    class FakeQuoteProvider:
        def __init__(self, _config) -> None:
            pass

        def fetch_quote(self, _ticker: str) -> QuoteData:
            return QuoteData(
                source_url="https://finviz.com/quote.ashx?t=TEST",
                fetched_at="2026-02-23T10:00:00-08:00",
                company={"name": "Test", "sector": None, "industry": None, "country": None},
                price={"value": 1.0, "change": 0.0, "change_percent": 0.0},
                snapshot_table={"P/E": "10"},
                news_items=[
                    NewsItem(None, "10:00AM", "pub", "headline1", "/news/abc"),
                    NewsItem(None, "10:01AM", "pub", "headline2", "https://finviz.com/news/abc"),
                ],
                raw=None,
            )

    class FakeArticleFetcher:
        calls = 0
        seen_urls = []

        def __init__(self, _config) -> None:
            pass

        def fetch(self, url: str) -> ArticleFetchResult:
            FakeArticleFetcher.calls += 1
            FakeArticleFetcher.seen_urls.append(url)
            return ArticleFetchResult(
                success=True,
                http_status=200,
                metadata={
                    "title": "title",
                    "byline": None,
                    "published_at": None,
                    "site_name": "finviz.com",
                    "language": None,
                },
                content={"text": "text", "text_blocks": ["text"], "html": None},
                links=[url],
                error=None,
            )

    exit_code = run_scrape(
        ticker="TEST",
        config_path=str(cfg),
        force=False,
        quote_provider_cls=FakeQuoteProvider,
        article_fetcher_cls=FakeArticleFetcher,
    )
    assert exit_code == 0
    assert FakeArticleFetcher.calls == 1
    assert FakeArticleFetcher.seen_urls == ["https://finviz.com/news/abc"]

    run_dirs = sorted(path for path in (data_dir / "TEST").iterdir() if path.is_dir())
    news_path = run_dirs[-1] / "finviz_news.json"
    with news_path.open("r", encoding="utf-8") as handle:
        news_payload = json.load(handle)

    assert news_payload["items"][0]["resolved_url"] == "https://finviz.com/news/abc"
    assert news_payload["items"][0]["url_resolution_status"] == "resolved"
    assert news_payload["items"][1]["resolved_url"] == "https://finviz.com/news/abc"


def test_scrape_caps_article_fetches_per_ticker(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    cfg = tmp_path / "config.yaml"
    _write_config(cfg, data_dir)

    class FakeQuoteProvider:
        def __init__(self, _config) -> None:
            pass

        def fetch_quote(self, _ticker: str) -> QuoteData:
            return QuoteData(
                source_url="https://finviz.com/quote.ashx?t=TEST",
                fetched_at="2026-02-23T10:00:00-08:00",
                company={"name": "Test", "sector": None, "industry": None, "country": None},
                price={"value": 1.0, "change": 0.0, "change_percent": 0.0},
                snapshot_table={"P/E": "10"},
                news_items=[
                    NewsItem(None, "10:00AM", "pub", f"headline{i}", f"https://example.com/{i}")
                    for i in range(12)
                ],
                raw=None,
            )

    class FakeArticleFetcher:
        calls = 0

        def __init__(self, _config) -> None:
            pass

        def fetch(self, url: str) -> ArticleFetchResult:
            FakeArticleFetcher.calls += 1
            return ArticleFetchResult(
                success=True,
                http_status=200,
                metadata={
                    "title": "title",
                    "byline": None,
                    "published_at": None,
                    "site_name": "example.com",
                    "language": None,
                },
                content={"text": url, "text_blocks": [url], "html": None},
                links=[],
                error=None,
            )

    exit_code = run_scrape(
        ticker="TEST",
        config_path=str(cfg),
        force=False,
        quote_provider_cls=FakeQuoteProvider,
        article_fetcher_cls=FakeArticleFetcher,
    )

    assert exit_code == 0
    assert FakeArticleFetcher.calls == 10

    run_dirs = sorted(path for path in (data_dir / "TEST").iterdir() if path.is_dir())
    manifest_path = run_dirs[-1] / "run_manifest.json"
    with manifest_path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    assert manifest["stats"]["news_links_total"] == 12
    assert manifest["stats"]["news_links_new"] == 12
    assert manifest["stats"]["articles_fetched_ok"] == 10
