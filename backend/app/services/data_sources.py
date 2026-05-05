"""
Planned ingestion layer — implement daily refresh jobs to call these.

Suggested layout:
- data/raw/excel/     incoming spreadsheets (gitignored)
- data/cache/         normalized parquet or sqlite (gitignored)
- app/jobs/daily_refresh.py  orchestration (cron, Windows Task Scheduler, or APScheduler)
"""


def load_excel_snapshots() -> None:
    """TODO: pandas.read_excel / openpyxl; merge multiple workbooks."""
    raise NotImplementedError


def load_yfinance_series() -> None:
    """Live pulls: see `app.services.yfinance_market` (used by /api/indices)."""
    raise NotImplementedError


def load_external_api_payload() -> None:
    """TODO: httpx/async client; auth from env."""
    raise NotImplementedError
