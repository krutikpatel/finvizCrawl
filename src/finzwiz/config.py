from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class OutputConfig:
    data_dir: str
    pretty_json: bool


@dataclass(frozen=True)
class DedupConfig:
    retention_days: int
    seen_urls_filename: str
    compact_on_write: bool


@dataclass(frozen=True)
class PlaywrightConfig:
    headless: bool


@dataclass(frozen=True)
class ScrapingConfig:
    backend: str
    user_agent: str
    timeout_seconds: int
    retries: int
    delay_seconds: float
    max_concurrency: int
    playwright: PlaywrightConfig


@dataclass(frozen=True)
class ArticlesConfig:
    include_raw_html: bool
    max_text_chars: int
    max_articles_per_ticker: int


@dataclass(frozen=True)
class SentimentConfig:
    model: str
    max_articles_per_batch: int
    log_filename: str
    summary_filename: str


@dataclass(frozen=True)
class ProjectConfig:
    name: str
    schema_version: str


@dataclass(frozen=True)
class Config:
    project: ProjectConfig
    output: OutputConfig
    dedup: DedupConfig
    scraping: ScrapingConfig
    articles: ArticlesConfig
    sentiment: SentimentConfig


class ConfigError(ValueError):
    pass


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ConfigError("Config root must be a mapping")
    return data


def load_config(path: str | Path = "config.yaml") -> Config:
    raw = _read_yaml(Path(path))

    try:
        project_raw = raw["project"]
        output_raw = raw["output"]
        dedup_raw = raw["dedup"]
        scraping_raw = raw["scraping"]
        articles_raw = raw["articles"]
    except KeyError as exc:
        raise ConfigError(f"Missing required config section: {exc}") from exc

    sentiment_raw = raw.get("sentiment", {})

    backend = str(scraping_raw.get("backend", "http"))
    if backend != "http":
        raise ConfigError("Only scraping.backend=http is supported in v1")

    max_concurrency = int(scraping_raw.get("max_concurrency", 5))
    if max_concurrency < 1:
        raise ConfigError("scraping.max_concurrency must be >= 1")

    retention_days = int(dedup_raw.get("retention_days", 15))
    if retention_days < 1:
        raise ConfigError("dedup.retention_days must be >= 1")

    max_articles_per_ticker = int(articles_raw.get("max_articles_per_ticker", 10))
    if max_articles_per_ticker < 1:
        raise ConfigError("articles.max_articles_per_ticker must be >= 1")

    return Config(
        project=ProjectConfig(
            name=str(project_raw["name"]),
            schema_version=str(project_raw["schema_version"]),
        ),
        output=OutputConfig(
            data_dir=str(output_raw["data_dir"]),
            pretty_json=bool(output_raw.get("pretty_json", True)),
        ),
        dedup=DedupConfig(
            retention_days=retention_days,
            seen_urls_filename=str(dedup_raw.get("seen_urls_filename", "seen_urls.jsonl")),
            compact_on_write=bool(dedup_raw.get("compact_on_write", False)),
        ),
        scraping=ScrapingConfig(
            backend=backend,
            user_agent=str(scraping_raw["user_agent"]),
            timeout_seconds=int(scraping_raw.get("timeout_seconds", 30)),
            retries=int(scraping_raw.get("retries", 2)),
            delay_seconds=float(scraping_raw.get("delay_seconds", 0)),
            max_concurrency=max_concurrency,
            playwright=PlaywrightConfig(
                headless=bool(scraping_raw.get("playwright", {}).get("headless", True))
            ),
        ),
        articles=ArticlesConfig(
            include_raw_html=bool(articles_raw.get("include_raw_html", False)),
            max_text_chars=int(articles_raw.get("max_text_chars", 0)),
            max_articles_per_ticker=max_articles_per_ticker,
        ),
        sentiment=SentimentConfig(
            model=str(sentiment_raw.get("model", "claude-haiku-4-5-20251001")),
            max_articles_per_batch=int(sentiment_raw.get("max_articles_per_batch", 20)),
            log_filename=str(sentiment_raw.get("log_filename", "sentiment_log.jsonl")),
            summary_filename=str(sentiment_raw.get("summary_filename", "sentiment_summary.json")),
        ),
    )


def config_to_dict(config: Config) -> dict[str, Any]:
    return {
        "project": {
            "name": config.project.name,
            "schema_version": config.project.schema_version,
        },
        "output": {
            "data_dir": config.output.data_dir,
            "pretty_json": config.output.pretty_json,
        },
        "dedup": {
            "retention_days": config.dedup.retention_days,
            "seen_urls_filename": config.dedup.seen_urls_filename,
            "compact_on_write": config.dedup.compact_on_write,
        },
        "scraping": {
            "backend": config.scraping.backend,
            "user_agent": config.scraping.user_agent,
            "timeout_seconds": config.scraping.timeout_seconds,
            "retries": config.scraping.retries,
            "delay_seconds": config.scraping.delay_seconds,
            "max_concurrency": config.scraping.max_concurrency,
            "playwright": {
                "headless": config.scraping.playwright.headless,
            },
        },
        "articles": {
            "include_raw_html": config.articles.include_raw_html,
            "max_text_chars": config.articles.max_text_chars,
            "max_articles_per_ticker": config.articles.max_articles_per_ticker,
        },
        "sentiment": {
            "model": config.sentiment.model,
            "max_articles_per_batch": config.sentiment.max_articles_per_batch,
            "log_filename": config.sentiment.log_filename,
            "summary_filename": config.sentiment.summary_filename,
        },
    }
