from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .storage import read_jsonl, write_jsonl_atomic


@dataclass(frozen=True)
class DedupDecision:
    fetch: bool
    status: str
    reason: str


def article_id_from_url(url: str, length: int = 24) -> str:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return digest[:length]


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


class DedupStore:
    def __init__(self, path: Path, retention_days: int) -> None:
        self.path = path
        self.retention_days = retention_days
        self._rows_by_url: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        for row in read_jsonl(self.path):
            url = row.get("url")
            if not url:
                continue
            previous = self._rows_by_url.get(url)
            if previous is None:
                self._rows_by_url[url] = row
                continue
            prev_ts = parse_iso(previous.get("last_seen_at"))
            curr_ts = parse_iso(row.get("last_seen_at"))
            if prev_ts is None or (curr_ts is not None and curr_ts >= prev_ts):
                self._rows_by_url[url] = row

    def decide(self, *, url: str, now: datetime, force: bool) -> DedupDecision:
        if force:
            return DedupDecision(fetch=True, status="forced", reason="forced_by_flag")

        row = self._rows_by_url.get(url)
        if row is None:
            return DedupDecision(fetch=True, status="new", reason="not_seen_before")

        last_seen = parse_iso(row.get("last_seen_at"))
        if last_seen is None:
            return DedupDecision(fetch=True, status="new", reason="invalid_last_seen")

        is_recent = (now - last_seen) <= timedelta(days=self.retention_days)
        status = row.get("status")
        if is_recent and status in {"fetched_ok", "skipped_recent"}:
            return DedupDecision(fetch=False, status="skipped_recent", reason="recent_success")
        if is_recent and status == "fetched_failed":
            return DedupDecision(fetch=True, status="retry_failed_recent", reason="recent_failure_retry")
        return DedupDecision(fetch=True, status="new", reason="older_than_window")

    def update(
        self,
        *,
        url: str,
        article_id: str,
        now: datetime,
        fetch_status: str,
        http_status: int | None,
        note: str | None,
    ) -> None:
        previous = self._rows_by_url.get(url)
        row = {
            "url": url,
            "article_id": article_id,
            "first_seen_at": previous.get("first_seen_at") if previous else now.isoformat(),
            "last_seen_at": now.isoformat(),
            "last_fetched_at": now.isoformat() if fetch_status in {"fetched_ok", "fetched_failed"} else (
                previous.get("last_fetched_at") if previous else None
            ),
            "status": fetch_status,
            "http_status": http_status,
            "note": note,
        }
        self._rows_by_url[url] = row

    def flush(self) -> None:
        rows = sorted(self._rows_by_url.values(), key=lambda value: (value.get("url") or ""))
        write_jsonl_atomic(self.path, rows)
