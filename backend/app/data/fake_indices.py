"""Placeholder index data until yfinance or another feed backs this endpoint."""


def get_indices_snapshot() -> dict:
    return {
        "ftse100": {
            "price": 8124.56,
            "previousClose": 8098.12,
            "change": "+26.44",
            "changePercent": "+0.33",
            "fiftyTwoWeekHigh": 8445.0,
            "fiftyTwoWeekLow": 7310.2,
        },
        "ftse250": {
            "price": 20456.78,
            "previousClose": 20388.0,
            "change": "+68.78",
            "changePercent": "+0.34",
            "fiftyTwoWeekHigh": 21560.0,
            "fiftyTwoWeekLow": 18200.5,
        },
    }
