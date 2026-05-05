"""
Chatham Direct rates (SONIA, SONIA swaps, gilts).

Credentials must be supplied via environment variables — never commit secrets:
  CHATHAM_USERNAME
  CHATHAM_PASSWORD

Optional: `backend/.env` loaded automatically when `python-dotenv` is installed.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx

LOGIN_URL = "https://chathamdirect.com/authentication/api/v1/login/authenticate"
SONIA_URL = "https://chathamdirect.com/rates/api/v1/rateset/sonia/historical-rates"
SONIA_SWAP_URL = "https://chathamdirect.com/rates/api/v1/rateset/sonia-swaps/historical-rates"
GILT_URL = "https://chathamdirect.com/rates/api/v1/rateset/gilt/historical-rates"


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    env_path = Path(__file__).resolve().parents[2] / ".env"
    load_dotenv(env_path)


def _fmt_signed(value: float, decimals: int) -> str:
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.{decimals}f}"


def _series_points(result: dict[str, Any], index: int) -> tuple[str, list[dict[str, Any]]]:
    data = result.get("data") or []
    if index < 0 or index >= len(data):
        raise IndexError(f"Chatham result has no series at index {index}")
    item = data[index]
    sid = str(item.get("id", index))
    pts = item.get("data") or []
    return sid, pts


def _row_from_curve(label: str, points: list[dict[str, Any]], decimals: int) -> dict[str, Any]:
    if not points:
        return {"ticker": label, "label": label, "error": "Empty series"}

    vals: list[float] = []
    for p in points:
        try:
            vals.append(float(p["value"]) * 100.0)
        except (KeyError, TypeError, ValueError):
            continue
    if not vals:
        return {"ticker": label, "label": label, "error": "No numeric values"}

    last_v = vals[-1]
    prev_v = vals[-2] if len(vals) >= 2 else last_v
    lo = min(vals)
    hi = max(vals)
    change = last_v - prev_v
    pct = (change / prev_v * 100.0) if prev_v else 0.0

    return {
        "ticker": label,
        "label": label,
        "decimals": decimals,
        "price": last_v,
        "previousClose": prev_v,
        "change": _fmt_signed(change, decimals),
        "changePercent": _fmt_signed(pct, 2),
        "fiftyTwoWeekLow": lo,
        "fiftyTwoWeekHigh": hi,
    }


def _get_json_result(client: httpx.Client, url: str) -> dict[str, Any]:
    r = client.get(
        url,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    r.raise_for_status()
    body = r.json()
    if "result" not in body:
        raise ValueError(f"Unexpected Chatham response keys: {list(body.keys())[:8]}")
    res = body["result"]
    if not isinstance(res, dict):
        raise ValueError("Chatham result is not an object")
    return res


def fetch_chatham_market_rows() -> list[dict[str, Any]]:
    """
    Four dashboard rows matching the Apps Script intent:
      - SONIA daily (first series, index 0)
      - SONIA swap (series index 3; date/value from that series — fixes undefined soniaswap0)
      - UK gilt (series indices 9 and 13 — fixes undefined gilt0 for date)
    """
    _load_env()
    username = (os.getenv("CHATHAM_USERNAME") or "").strip()
    password = os.getenv("CHATHAM_PASSWORD") or ""
    if not username or not password:
        return []

    rows: list[dict[str, Any]] = []

    try:
        with httpx.Client(timeout=90.0, follow_redirects=True) as client:
            login_payload = {
                "username": username,
                "password": password,
                "skipImpersonation": "",
                "redirectUrl": "",
            }
            lr = client.post(
                LOGIN_URL,
                json=login_payload,
                headers={
                    "Content-Type": "application/json",
                    "Connection": "keep-alive",
                },
            )
            if lr.status_code >= 400:
                raise RuntimeError(f"Chatham login HTTP {lr.status_code}")

            sonia = _get_json_result(client, SONIA_URL)
            sid0, pts0 = _series_points(sonia, 0)
            rows.append(
                _row_from_curve(f"SONIA — {sid0} (Chatham)", pts0, 5),
            )

            swaps = _get_json_result(client, SONIA_SWAP_URL)
            sid3, pts3 = _series_points(swaps, 3)
            rows.append(
                _row_from_curve(f"SONIA swap — {sid3}-year (Chatham)", pts3, 3),
            )

            gilt = _get_json_result(client, GILT_URL)
            for idx, dec in ((9, 3), (13, 3)):
                try:
                    gid, gpts = _series_points(gilt, idx)
                    rows.append(
                        _row_from_curve(f"UK gilt — {gid}-year (Chatham)", gpts, dec),
                    )
                except IndexError:
                    rows.append(
                        {
                            "ticker": f"gilt[{idx}]",
                            "label": f"UK gilt (series index {idx})",
                            "error": "Series index not present in Chatham response",
                        },
                    )
    except Exception as exc:  # noqa: BLE001
        return [
            {
                "ticker": "chatham",
                "label": "Chatham Direct",
                "error": str(exc),
            }
        ]

    return rows
