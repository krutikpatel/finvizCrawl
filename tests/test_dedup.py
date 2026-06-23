from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from finzwiz.dedup import DedupStore, article_id_from_url

PACIFIC = ZoneInfo("America/Los_Angeles")


def test_article_id_is_deterministic() -> None:
    url = "https://example.com/article/1"
    assert article_id_from_url(url) == article_id_from_url(url)


def test_dedup_recent_success_skips(tmp_path) -> None:
    store = DedupStore(tmp_path / "seen_urls.jsonl", retention_days=15)
    now = datetime(2026, 2, 23, 10, 0, tzinfo=PACIFIC)
    url = "https://example.com/success"
    article_id = article_id_from_url(url)
    store.update(
        url=url,
        article_id=article_id,
        now=now,
        fetch_status="fetched_ok",
        http_status=200,
        note=None,
    )
    store.flush()

    loaded = DedupStore(tmp_path / "seen_urls.jsonl", retention_days=15)
    decision = loaded.decide(url=url, now=now, force=False)
    assert decision.fetch is False
    assert decision.status == "skipped_recent"


def test_dedup_recent_success_stays_skipped_across_runs(tmp_path) -> None:
    path = tmp_path / "seen_urls.jsonl"
    now = datetime(2026, 2, 23, 10, 0, tzinfo=PACIFIC)
    url = "https://example.com/success"
    article_id = article_id_from_url(url)

    store = DedupStore(path, retention_days=15)
    store.update(
        url=url,
        article_id=article_id,
        now=now,
        fetch_status="fetched_ok",
        http_status=200,
        note=None,
    )
    store.flush()

    second_run = DedupStore(path, retention_days=15)
    decision = second_run.decide(url=url, now=now, force=False)
    assert decision.fetch is False
    second_run.update(
        url=url,
        article_id=article_id,
        now=now,
        fetch_status=decision.status,
        http_status=None,
        note=decision.reason,
    )
    second_run.flush()

    third_run = DedupStore(path, retention_days=15)
    decision = third_run.decide(url=url, now=now, force=False)
    assert decision.fetch is False
    assert decision.status == "skipped_recent"
    assert decision.reason == "recent_success"


def test_dedup_recent_failed_retries(tmp_path) -> None:
    store = DedupStore(tmp_path / "seen_urls.jsonl", retention_days=15)
    now = datetime(2026, 2, 23, 10, 0, tzinfo=PACIFIC)
    url = "https://example.com/failed"
    article_id = article_id_from_url(url)
    store.update(
        url=url,
        article_id=article_id,
        now=now,
        fetch_status="fetched_failed",
        http_status=500,
        note="failure",
    )
    store.flush()

    loaded = DedupStore(tmp_path / "seen_urls.jsonl", retention_days=15)
    decision = loaded.decide(url=url, now=now, force=False)
    assert decision.fetch is True
    assert decision.status == "retry_failed_recent"


def test_dedup_older_than_window_fetches(tmp_path) -> None:
    store = DedupStore(tmp_path / "seen_urls.jsonl", retention_days=15)
    old = datetime(2026, 1, 1, 10, 0, tzinfo=PACIFIC)
    now = datetime(2026, 2, 23, 10, 0, tzinfo=PACIFIC)
    url = "https://example.com/old"
    article_id = article_id_from_url(url)
    store.update(
        url=url,
        article_id=article_id,
        now=old,
        fetch_status="fetched_ok",
        http_status=200,
        note=None,
    )
    store.flush()

    loaded = DedupStore(tmp_path / "seen_urls.jsonl", retention_days=15)
    decision = loaded.decide(url=url, now=now, force=False)
    assert decision.fetch is True
    assert decision.status == "new"


def test_dedup_ignores_corrupt_jsonl_lines(tmp_path) -> None:
    dedup_path = tmp_path / "seen_urls.jsonl"
    dedup_path.write_text(
        '{"url":"https://example.com/a","last_seen_at":"2026-02-23T10:00:00-08:00","status":"fetched_ok"}\n'
        '{"bad_json":\n',
        encoding="utf-8",
    )
    loaded = DedupStore(dedup_path, retention_days=15)
    now = datetime(2026, 2, 23, 11, 0, tzinfo=PACIFIC)
    decision = loaded.decide(url="https://example.com/a", now=now, force=False)
    assert decision.fetch is False
    assert decision.status == "skipped_recent"
