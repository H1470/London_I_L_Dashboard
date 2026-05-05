from fastapi import APIRouter

from app.data.fake_indices import get_indices_snapshot
from app.services.chatham_rates import fetch_chatham_market_rows
from app.services.yfinance_market import fetch_yfinance_ticker_rows

router = APIRouter()


@router.get("/indices")
def indices():
    payload = get_indices_snapshot()
    payload["chatham_rows"] = fetch_chatham_market_rows()
    payload["yfinance_rows"] = fetch_yfinance_ticker_rows()
    return payload
