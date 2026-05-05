"""Live market rows via yfinance (used by /api/indices)."""

from __future__ import annotations

from typing import Any

import yfinance as yf

YFIN_TICKERS: list[str] = ["GBP=X", "EURGBP=X", "GC=F", "BZ=F", "BTC-USD"]

TICKER_LABELS: dict[str, str] = {
    "GBP=X": "GBP / USD (GBP=X)",
    "EURGBP=X": "EUR / GBP (EURGBP=X)",
    "GC=F": "Gold (GC=F)",
    "BZ=F": "Brent crude (BZ=F)",
    "BTC-USD": "Bitcoin (BTC-USD)",
}

TICKER_DECIMALS: dict[str, int] = {
    "GBP=X": 4,
    "EURGBP=X": 4,
    "GC=F": 2,
    "BZ=F": 2,
    "BTC-USD": 2,
}


def _fmt_signed(value: float, decimals: int) -> str:
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.{decimals}f}"


def _row_ok(
    ticker: str,
    label: str,
    decimals: int,
    last: float,
    prev: float,
    lo: float,
    hi: float,
) -> dict[str, Any]:
    change = last - prev
    pct = (change / prev * 100.0) if prev else 0.0
    return {
        "ticker": ticker,
        "label": label,
        "decimals": decimals,
        "price": last,
        "previousClose": prev,
        "change": _fmt_signed(change, decimals),
        "changePercent": _fmt_signed(pct, 2),
        "fiftyTwoWeekLow": lo,
        "fiftyTwoWeekHigh": hi,
    }


def _row_error(ticker: str, message: str) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "label": TICKER_LABELS.get(ticker, ticker),
        "error": message,
    }


def _snapshot_for_ticker(ticker: str) -> dict[str, Any]:
    label = TICKER_LABELS.get(ticker, ticker)
    decimals = TICKER_DECIMALS.get(ticker, 2)

    t = yf.Ticker(ticker)
    hist = t.history(period="3mo", auto_adjust=False)
    if hist.empty or "Close" not in hist.columns:
        return _row_error(ticker, "No price history returned")

    close = hist["Close"].astype(float).dropna()
    if close.empty:
        return _row_error(ticker, "Close series empty")

    last = float(close.iloc[-1])
    prev = float(close.iloc[-2]) if len(close) >= 2 else last

    hist_1y = t.history(period="1y", auto_adjust=False)
    if hist_1y.empty or "Close" not in hist_1y.columns:
        lo = float(close.min())
        hi = float(close.max())
    else:
        c1 = hist_1y["Close"].astype(float).dropna()
        lo = float(c1.min())
        hi = float(c1.max())

    return _row_ok(ticker, label, decimals, last, prev, lo, hi)


def fetch_yfinance_ticker_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ticker in YFIN_TICKERS:
        try:
            rows.append(_snapshot_for_ticker(ticker))
        except Exception as exc:  # noqa: BLE001 — return per-row errors for the UI
            rows.append(_row_error(ticker, str(exc)))
    return rows
