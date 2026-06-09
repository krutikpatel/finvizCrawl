from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class NewsItem:
    published_at: str | None
    published_at_raw: str | None
    publisher: str | None
    headline: str | None
    url: str


@dataclass(frozen=True)
class QuoteData:
    source_url: str
    fetched_at: str
    company: dict
    price: dict
    snapshot_table: dict
    news_items: list[NewsItem]
    raw: str | None


class QuoteProvider(Protocol):
    def fetch_quote(self, ticker: str) -> QuoteData:
        raise NotImplementedError

