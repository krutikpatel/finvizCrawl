# How To Test (Smoke Test)

## Prerequisites
- Run from project root: `/Users/krutik/Documents/GptCodexWorkspace/finzwizCrawl1`
- Python virtual environment exists at `.venv`
- Dependencies installed in `.venv`

## 1) Install deps (if needed)
```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

## 2) Run unit tests
```bash
.venv/bin/python -m pytest -q
```

Expected:
- All tests pass (currently `9 passed`)

## 3) Run live smoke scrape
```bash
PYTHONPATH=src .venv/bin/python -m finzwiz.cli scrape --ticker AAPL
```

Expected:
- Command exits with code `0`
- Output folder created under:
  - `data/AAPL/<YYYY-MM-DD>/`

## 4) Verify required artifacts
Check these files exist:
- `data/AAPL/<YYYY-MM-DD>/finviz_quote.json`
- `data/AAPL/<YYYY-MM-DD>/finviz_news.json`
- `data/AAPL/<YYYY-MM-DD>/run_manifest.json`
- `data/AAPL/<YYYY-MM-DD>/articles/` (contains many `<ARTICLE_ID>.json` files)
- `data/AAPL/seen_urls.jsonl`

Example command:
```bash
find data/AAPL -maxdepth 3 -type f | sort
```

## 5) Validate manifest stats
Open:
- `data/AAPL/<YYYY-MM-DD>/run_manifest.json`

Confirm:
- `news_links_total` is populated
- `articles_fetched_ok` and `articles_failed` are populated
- `errors` list contains details for failed URLs

## Notes
- Some failures are expected (paywalls/403/blocked URLs).
- Current known gap: some Finviz news links can be relative (`/news/...`) and may fail unless converted to absolute URL before fetch.
