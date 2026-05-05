"""Placeholder aggregates until real pipelines (Excel, yfinance, APIs) are wired."""

from datetime import date


def get_dashboard_summary() -> dict:
    return {
        "as_of": date.today().isoformat(),
        "source": "fake",
        "kpis": [
            {"id": "revenue", "label": "Revenue (trial)", "value": 1_240_000, "unit": "GBP"},
            {"id": "headcount", "label": "Headcount (trial)", "value": 42, "unit": "FTE"},
            {"id": "run_rate", "label": "Run rate (trial)", "value": 3.2, "unit": "%"},
        ],
        "series": {
            "months": ["Jan", "Feb", "Mar", "Apr", "May"],
            "values": [820, 910, 880, 940, 990],
        },
        "recent_rows": [
            {"entity": "Alpha Ltd", "region": "London", "score": 0.91},
            {"entity": "Beta Co", "region": "Manchester", "score": 0.77},
            {"entity": "Gamma LLP", "region": "London", "score": 0.84},
        ],
    }
