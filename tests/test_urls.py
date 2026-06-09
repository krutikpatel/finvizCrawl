from __future__ import annotations

from finzwiz.urls import resolve_news_url


def test_resolve_relative_url() -> None:
    resolved = resolve_news_url("/news/123", "https://finviz.com/quote.ashx?t=AAPL")
    assert resolved.resolved_url == "https://finviz.com/news/123"
    assert resolved.status == "resolved"
    assert resolved.reason is None


def test_absolute_url_passthrough() -> None:
    resolved = resolve_news_url("https://example.com/a", "https://finviz.com/quote.ashx?t=AAPL")
    assert resolved.resolved_url == "https://example.com/a"
    assert resolved.status == "already_absolute"
    assert resolved.reason is None


def test_invalid_url_rejected() -> None:
    resolved = resolve_news_url("", "https://finviz.com/quote.ashx?t=AAPL")
    assert resolved.resolved_url is None
    assert resolved.status == "invalid"
    assert resolved.reason == "empty_url"

