"""Trial dashboard summary JSON (KPIs + series + recent rows); optional ``q`` filter."""

from typing import Optional

from fastapi import APIRouter, Query

from app.data.fake_data import get_dashboard_summary

router = APIRouter()


@router.get("/summary")
def summary(q: Optional[str] = Query(default=None, description="Optional search filter (trial)")):
    payload = get_dashboard_summary()
    if q:
        needle = q.lower().strip()
        rows = payload.get("recent_rows", [])
        payload = {
            **payload,
            "recent_rows": [r for r in rows if needle in r["entity"].lower() or needle in r["region"].lower()],
            "filter": q,
        }
    return payload
