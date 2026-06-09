from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests
import trafilatura
from bs4 import BeautifulSoup
from readability import Document
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from ..config import Config


@dataclass(frozen=True)
class ArticleFetchResult:
    success: bool
    http_status: int | None
    metadata: dict[str, Any]
    content: dict[str, Any]
    links: list[str]
    error: dict[str, Any] | None


class HttpArticleFetcher:
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
        self.session.headers.update({"User-Agent": config.scraping.user_agent})

    def fetch(self, url: str) -> ArticleFetchResult:
        try:
            response = self.session.get(url, timeout=self.config.scraping.timeout_seconds)
            status = response.status_code
            response.raise_for_status()
        except requests.RequestException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            return ArticleFetchResult(
                success=False,
                http_status=status,
                metadata=_empty_metadata(),
                content=_empty_content(),
                links=[],
                error={"type": "http_error", "message": str(exc), "context": {"url": url}},
            )

        html = response.text
        extracted = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=False,
            output_format="txt",
        )
        text = extracted.strip() if extracted else ""
        if not text:
            text = _readability_fallback(html)

        soup = BeautifulSoup(html, "lxml")
        title = soup.title.get_text(" ", strip=True) if soup.title else None
        links = sorted(
            {
                anchor.get("href")
                for anchor in soup.find_all("a", href=True)
                if isinstance(anchor.get("href"), str)
            }
        )
        blocks = [block.strip() for block in text.split("\n") if block.strip()] if text else []
        max_chars = self.config.articles.max_text_chars
        if max_chars and max_chars > 0:
            text = text[:max_chars]

        content = {
            "text": text or None,
            "text_blocks": blocks or None,
            "html": html if self.config.articles.include_raw_html else None,
        }
        metadata = {
            "title": title,
            "byline": None,
            "published_at": None,
            "site_name": response.url.split("/")[2] if "://" in response.url else None,
            "language": None,
        }
        return ArticleFetchResult(
            success=bool(text),
            http_status=status,
            metadata=metadata,
            content=content,
            links=links,
            error=None if text else {
                "type": "parse_error",
                "message": "No readable text extracted",
                "context": {"url": url},
            },
        )


def _readability_fallback(html: str) -> str:
    try:
        doc = Document(html)
        summary_html = doc.summary()
        soup = BeautifulSoup(summary_html, "lxml")
        return soup.get_text("\n", strip=True)
    except Exception:
        return ""


def _empty_metadata() -> dict[str, Any]:
    return {
        "title": None,
        "byline": None,
        "published_at": None,
        "site_name": None,
        "language": None,
    }


def _empty_content() -> dict[str, Any]:
    return {
        "text": None,
        "text_blocks": None,
        "html": None,
    }

