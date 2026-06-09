from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin, urlparse


@dataclass(frozen=True)
class URLResolution:
    resolved_url: str | None
    status: str
    reason: str | None


def resolve_news_url(raw_url: str | None, base_url: str) -> URLResolution:
    if raw_url is None:
        return URLResolution(
            resolved_url=None,
            status="invalid",
            reason="missing_url",
        )

    candidate = raw_url.strip()
    if not candidate:
        return URLResolution(
            resolved_url=None,
            status="invalid",
            reason="empty_url",
        )

    parsed = urlparse(candidate)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return URLResolution(
            resolved_url=candidate,
            status="already_absolute",
            reason=None,
        )

    resolved = urljoin(base_url, candidate)
    resolved_parsed = urlparse(resolved)
    if resolved_parsed.scheme not in {"http", "https"} or not resolved_parsed.netloc:
        return URLResolution(
            resolved_url=None,
            status="invalid",
            reason="invalid_resolved_url",
        )

    return URLResolution(
        resolved_url=resolved,
        status="resolved",
        reason=None,
    )

