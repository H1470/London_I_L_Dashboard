"""
Chatham Direct rates (SONIA, SONIA swaps, gilts).

Credentials: CHATHAM_USERNAME, CHATHAM_PASSWORD (see backend/.env).

No public API docs — this client mirrors the prior Apps Script flow:
POST login, join Set-Cookie name=value segments, GET rates with that Cookie header.
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

# Some gateways block non-browser user agents; keep requests looking like a normal browser.
_DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://chathamdirect.com",
    "Referer": "https://chathamdirect.com/",
}


def _load_env() -> None:
    """Repo root .env then backend/.env (backend wins). From app/services/: parents[3]=repo, parents[2]=backend."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    here = Path(__file__).resolve()
    load_dotenv(here.parents[3] / ".env", override=False)
    load_dotenv(here.parents[2] / ".env", override=True)


def _env_clean(raw: str | None) -> str:
    """Strip whitespace and a single layer of surrounding quotes from .env values."""
    s = (raw or "").strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        s = s[1:-1].strip()
    return s


def _fmt_signed(value: float, decimals: int) -> str:
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.{decimals}f}"


def _cookie_header_from_response(response: httpx.Response) -> str:
    """Match Apps Script: take each Set-Cookie's name=value segment before the first ';'."""
    parts: list[str] = []
    for key, value in response.headers.multi_items():
        if key.lower() != "set-cookie":
            continue
        segment = value.split(";", 1)[0].strip()
        if segment and "=" in segment:
            parts.append(segment)
    return "; ".join(parts)


def _raise_if_login_json_rejects(lr: httpx.Response) -> None:
    ct = (lr.headers.get("content-type") or "").lower()
    if "json" not in ct:
        return
    try:
        body = lr.json()
    except Exception:
        return
    if not isinstance(body, dict):
        return
    for ok_key in ("isSuccessful", "IsSuccessful", "success", "Success"):
        if ok_key in body and body[ok_key] is False:
            msg = (
                body.get("message")
                or body.get("Message")
                or body.get("error")
                or body.get("Error")
                or "Login rejected by API"
            )
            raise RuntimeError(f"Chatham login failed: {msg}")


def _unwrap_rates_payload(body: Any) -> dict[str, Any]:
    """Accept several possible envelope shapes."""
    if not isinstance(body, dict):
        raise ValueError("Chatham response JSON is not an object")

    for key in ("result", "Result"):
        inner = body.get(key)
        if isinstance(inner, dict):
            return inner

    if isinstance(body.get("data"), list):
        return body  # already { data: [...] }

    raise ValueError(f"Unexpected Chatham JSON shape (keys: {list(body.keys())[:12]})")


def _series_points(result: dict[str, Any], index: int) -> tuple[str, list[dict[str, Any]]]:
    data = result.get("data") or []
    if index < 0 or index >= len(data):
        raise IndexError(f"Chatham result has no series at index {index}")
    item = data[index]
    sid = str(item.get("id", index))
    pts = list(item.get("data") or [])
    return sid, pts


def _sort_points_by_date(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(points, key=lambda p: str(p.get("date", "")))


def _row_from_curve(label: str, points: list[dict[str, Any]], decimals: int) -> dict[str, Any]:
    pts = _sort_points_by_date(points)
    if not pts:
        return {"ticker": label, "label": label, "error": "Empty series"}

    vals: list[float] = []
    for p in pts:
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


def _get_json_result(client: httpx.Client, url: str, cookie_header: str) -> dict[str, Any]:
    headers = {
        **_DEFAULT_HEADERS,
        "Content-Type": "application/json",
        "Cookie": cookie_header,
    }
    r = client.get(url, headers=headers)
    if r.status_code == 401 or r.status_code == 403:
        raise RuntimeError(f"Chatham rates HTTP {r.status_code} (auth or permission). Body: {r.text[:400]}")
    r.raise_for_status()
    body = r.json()
    return _unwrap_rates_payload(body)


def fetch_chatham_market_rows() -> list[dict[str, Any]]:
    """
    Four dashboard rows:
      - SONIA curve data[0]
      - SONIA swap curve data[3]
      - Gilt curves data[9] and data[13]
    """
    _load_env()
    username = _env_clean(os.getenv("CHATHAM_USERNAME"))
    password = _env_clean(os.getenv("CHATHAM_PASSWORD"))
    if not username or not password:
        return []

    try:
        with httpx.Client(timeout=90.0, follow_redirects=True) as client:
            lr = client.post(
                LOGIN_URL,
                json={
                    "username": username,
                    "password": password,
                    "skipImpersonation": "",
                    "redirectUrl": "",
                },
                headers={
                    **_DEFAULT_HEADERS,
                    "Content-Type": "application/json",
                    "Connection": "keep-alive",
                },
            )
            if lr.status_code >= 400:
                raise RuntimeError(f"Chatham login HTTP {lr.status_code}: {lr.text[:500]}")

            _raise_if_login_json_rejects(lr)

            cookie_header = _cookie_header_from_response(lr)
            if not cookie_header:
                # Fall back to whatever httpx captured on the jar (some stacks split Set-Cookie oddly).
                jar_bits = [f"{k}={v}" for k, v in lr.cookies.items()]
                cookie_header = "; ".join(jar_bits)

            if not cookie_header:
                raise RuntimeError(
                    "Chatham login returned no cookies. "
                    "If your org uses SSO or MFA, API password login may not apply."
                )

            rows: list[dict[str, Any]] = []

            sonia = _get_json_result(client, SONIA_URL, cookie_header)
            sid0, pts0 = _series_points(sonia, 0)
            rows.append(_row_from_curve(f"SONIA — {sid0} (Chatham)", pts0, 5))

            swaps = _get_json_result(client, SONIA_SWAP_URL, cookie_header)
            sid3, pts3 = _series_points(swaps, 3)
            rows.append(_row_from_curve(f"SONIA swap — {sid3}-year (Chatham)", pts3, 3))

            gilt = _get_json_result(client, GILT_URL, cookie_header)
            for idx, dec in ((9, 3), (13, 3)):
                try:
                    gid, gpts = _series_points(gilt, idx)
                    rows.append(_row_from_curve(f"UK gilt — {gid}-year (Chatham)", gpts, dec))
                except IndexError:
                    rows.append(
                        {
                            "ticker": f"gilt[{idx}]",
                            "label": f"UK gilt (series index {idx})",
                            "error": "Series index not present in Chatham response",
                        },
                    )

            return rows
    except Exception as exc:  # noqa: BLE001
        return [
            {
                "ticker": "chatham",
                "label": "Chatham Direct",
                "error": str(exc),
            }
        ]
