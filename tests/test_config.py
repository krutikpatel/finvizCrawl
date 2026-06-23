from __future__ import annotations

from pathlib import Path

from finzwiz.config import ConfigError, load_config


def test_load_config_defaults() -> None:
    cfg = load_config("config.yaml")
    assert cfg.scraping.backend == "http"
    assert cfg.dedup.retention_days == 15
    assert cfg.scraping.max_concurrency == 5
    assert cfg.articles.max_articles_per_ticker == 10


def test_load_config_rejects_non_http_backend(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
project:
  name: finzwiz
  schema_version: "1.0"
output:
  data_dir: data
  pretty_json: true
dedup:
  retention_days: 15
  seen_urls_filename: seen_urls.jsonl
  compact_on_write: false
scraping:
  backend: playwright
  user_agent: test
  timeout_seconds: 30
  retries: 2
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

    try:
        load_config(config_path)
    except ConfigError:
        return
    raise AssertionError("Expected ConfigError for non-http backend")
