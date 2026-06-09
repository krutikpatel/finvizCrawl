from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from ..config import Config
from .base import NewsItem, QuoteData

PACIFIC_TZ = ZoneInfo("America/Los_Angeles")


class QuoteParseError(RuntimeError):
    pass


class HttpFinvizProvider:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.session = requests.Session()
        retry = Retry(
            total=config.scraping.retries,
            connect=config.scraping.retries,
            read=config.scraping.retries,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.session.headers.update(
            {
                "User-Agent": config.scraping.user_agent,
                "Accept": "text/html,application/xhtml+xml",
            }
        )

    def fetch_quote(self, ticker: str) -> QuoteData:
        quote_url = f"https://finviz.com/quote.ashx?t={ticker}"
        response = self.session.get(quote_url, timeout=self.config.scraping.timeout_seconds)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")

        snapshot_table = self._parse_snapshot_table(soup)
        if not snapshot_table:
            raise QuoteParseError("Failed to parse Finviz snapshot table")

        company = self._parse_company(soup)
        price = self._parse_price(soup)
        news_items = self._parse_news(soup, now=datetime.now(PACIFIC_TZ))

        return QuoteData(
            source_url=response.url,
            fetched_at=datetime.now(PACIFIC_TZ).isoformat(),
            company=company,
            price=price,
            snapshot_table=snapshot_table,
            news_items=news_items,
            raw=None,
        )

    def _parse_snapshot_table(self, soup: BeautifulSoup) -> dict[str, str]:
        table = soup.find("table", class_=re.compile(r"snapshot-table2"))
        if table is None:
            return {}
        cells = table.find_all("td")
        result: dict[str, str] = {}
        for idx in range(0, len(cells) - 1, 2):
            key = cells[idx].get_text(" ", strip=True)
            value = cells[idx + 1].get_text(" ", strip=True)
            if key:
                result[key] = value
        return result

    def _parse_company(self, soup: BeautifulSoup) -> dict[str, str | None]:
        company_name = None
        sector = None
        industry = None
        country = None

        header = soup.find("div", class_=re.compile(r"quote-header_left"))
        if header:
            anchor = header.find("a")
            if anchor:
                company_name = anchor.get_text(" ", strip=True) or None

        profile = soup.find("td", class_=re.compile(r"fullview-links"))
        if profile:
            links = [item.get_text(" ", strip=True) for item in profile.find_all("a")]
            if len(links) > 0:
                sector = links[0] or None
            if len(links) > 1:
                industry = links[1] or None
            if len(links) > 2:
                country = links[2] or None

        return {
            "name": company_name,
            "sector": sector,
            "industry": industry,
            "country": country,
        }

    def _parse_price(self, soup: BeautifulSoup) -> dict[str, float | None]:
        value = None
        change = None
        change_percent = None

        price_node = soup.find("strong", class_=re.compile(r"quote-price"))
        if price_node:
            value = _safe_float(price_node.get_text(strip=True))

        change_node = soup.find("span", class_=re.compile(r"quote-change"))
        if change_node:
            text = change_node.get_text(" ", strip=True)
            numbers = re.findall(r"[-+]?\d+(?:\.\d+)?", text)
            if numbers:
                change = _safe_float(numbers[0])
            if len(numbers) > 1:
                change_percent = _safe_float(numbers[1])

        return {
            "value": value,
            "change": change,
            "change_percent": change_percent,
        }

    def _parse_news(self, soup: BeautifulSoup, now: datetime) -> list[NewsItem]:
        items: list[NewsItem] = []
        news_table = soup.find("table", class_=re.compile(r"news-table"))
        if news_table is None:
            return items

        for row in news_table.find_all("tr"):
            date_cell = row.find("td", align="right")
            link = row.find("a")
            if date_cell is None or link is None:
                continue

            raw_time = date_cell.get_text(" ", strip=True) or None
            url = (link.get("href") or "").strip()
            if not url:
                continue

            headline = link.get_text(" ", strip=True) or None
            source_span = row.find("span")
            publisher = source_span.get_text(" ", strip=True) if source_span else None
            published_at = _parse_news_datetime(raw_time, now)

            items.append(
                NewsItem(
                    published_at=published_at,
                    published_at_raw=raw_time,
                    publisher=publisher,
                    headline=headline,
                    url=url,
                )
            )
        return items


def _safe_float(value: str) -> float | None:
    try:
        return float(value.replace("%", "").replace(",", ""))
    except (TypeError, ValueError):
        return None


def _parse_news_datetime(value: str | None, now: datetime) -> str | None:
    if not value:
        return None
    cleaned = value.strip()
    try:
        if cleaned.lower().startswith("today"):
            parsed_time = date_parser.parse(cleaned.replace("Today", "").strip())
            final = now.replace(
                hour=parsed_time.hour,
                minute=parsed_time.minute,
                second=0,
                microsecond=0,
            )
            return final.isoformat()
        if cleaned.lower().startswith("yesterday"):
            parsed_time = date_parser.parse(cleaned.replace("Yesterday", "").strip())
            base = now.replace(
                hour=parsed_time.hour,
                minute=parsed_time.minute,
                second=0,
                microsecond=0,
            )
            return (base - timedelta(days=1)).isoformat()
        parsed = date_parser.parse(cleaned)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=PACIFIC_TZ)
        return parsed.isoformat()
    except Exception:
        return None
