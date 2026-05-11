"""Planning London Datahub: live fetch on GET (default), optional cache-only read, POST sync for overrides."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx
from fastapi import APIRouter, Body, HTTPException, Query, Response

from app.data.planning_store import fetch_table_payload, replace_all_from_hits, store_debug_snapshot
from app.services.planning_ldh_client import applications_search_body, post_applications_search

router = APIRouter()
log = logging.getLogger(__name__)


def _extract_hit_list(data: dict[str, Any]) -> list[dict[str, Any]]:
    hits = data.get("hits", {})
    if not isinstance(hits, dict):
        return []
    hit_list = hits.get("hits")
    return hit_list if isinstance(hit_list, list) else []


def _extract_total(data: dict[str, Any]) -> Any:
    hits = data.get("hits", {})
    if not isinstance(hits, dict):
        return None
    total = hits.get("total")
    if isinstance(total, dict):
        return total.get("value")
    return total


def live_fetch_and_store(search_body: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Call Planning Datahub ``applications/_search``, persist hits to CSV via pandas, return
    table payload merged with diagnostics (timing, counts, human-readable ``message``).

    Raises ``ValueError``, ``httpx.HTTPStatusError``, or ``httpx.RequestError`` — caller maps to HTTP.
    """
    body = applications_search_body() if search_body is None else search_body
    t0 = time.perf_counter()
    data = post_applications_search(body)
    fetch_duration_ms = (time.perf_counter() - t0) * 1000

    hit_list = _extract_hit_list(data)
    stored = replace_all_from_hits(hit_list)
    print(f"[planning] Wrote {stored} hit(s) to CSV; loading table for API response…", flush=True)
    log.info("Planning CSV persist complete stored=%s", stored)
    table = fetch_table_payload()

    total_val = _extract_total(data)
    timed_out = data.get("timed_out")
    query_mode = (os.getenv("PLANNING_QUERY_MODE") or "full").strip().lower()

    if stored == 0:
        print(
            f"[planning] NOTE: 0 rows stored. ES reported total={total_val!r} (hits in this response: {len(hit_list)}).",
            flush=True,
        )

    msg_parts = [
        f"Planning Datahub responded in {fetch_duration_ms:.0f} ms.",
        f"Query mode: {query_mode!r}.",
        f"Elasticsearch returned {len(hit_list)} document(s) in this page; {stored} row(s) written to the CSV.",
    ]
    if total_val is not None:
        msg_parts.append(f"Reported total hit count (ES): {total_val}.")
    if timed_out:
        msg_parts.append("Warning: Elasticsearch reported timed_out=true.")
    if stored == 0 and query_mode == "full":
        msg_parts.append(
            "No matches: the combined filters (appeal date + B2/B8 + GIA) may be too strict, or field names differ from the index. "
            "Add PLANNING_QUERY_MODE=match_all to backend/.env to confirm the table works, then adjust PLANNING_GIA_EXISTING_MIN, "
            "PLANNING_APPEAL_START_AFTER, or the query in planning_ldh_client."
        )

    out: dict[str, Any] = {
        **table,
        "ok": True,
        "live_fetch": True,
        "cache_only": False,
        "fetch_duration_ms": round(fetch_duration_ms, 1),
        "upstream_stored_hits": stored,
        "elasticsearch_total": total_val,
        "timed_out": timed_out,
        "query_mode": query_mode,
        "message": " ".join(msg_parts),
    }
    print(f"[planning] Done — returning JSON to browser (table rows={len(table.get('rows') or [])}).", flush=True)
    log.info("Planning live fetch completed rows=%s", len(table.get("rows") or []))
    return out


@router.get("/planning/debug-store")
def get_planning_debug_store(response: Response):
    """Inspect the on-disk CSV store without calling Planning Datahub."""
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    snap = store_debug_snapshot()
    table = fetch_table_payload()
    return {
        **snap,
        "table_payload_row_count": table.get("row_count"),
        "table_payload_stored_row_count": table.get("stored_row_count"),
        "table_payload_parse_errors": table.get("parse_errors"),
        "table_columns_count": len(table.get("columns") or []),
    }


@router.get("/planning/results")
def get_planning_results(
    response: Response,
    cache_only: bool = Query(
        False,
        description="If true, read only the local CSV (no Planning Datahub request). Default false = live fetch then serve.",
    ),
):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"

    if cache_only:
        table = fetch_table_payload()
        return {
            **table,
            "ok": True,
            "live_fetch": False,
            "cache_only": True,
            "query_mode": "cache_only",
            "fetch_duration_ms": None,
            "message": "Loaded from local CSV only — no request was sent to Planning Datahub.",
        }

    try:
        return live_fetch_and_store(None)
    except ValueError as e:
        log.warning("Planning LDH config error: %s", e)
        raise HTTPException(status_code=503, detail=str(e)) from e
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        snippet = (e.response.text or "")[:800]
        log.warning("Planning LDH HTTP %s: %s", code, snippet)
        raise HTTPException(
            status_code=502,
            detail={
                "error": "Planning Datahub returned an error",
                "upstream_status": code,
                "upstream_body_preview": snippet,
                "hint": "Check the guest header in backend/.env (PLANNING_LDH_HEADER_VALUE) and the Elasticsearch query in planning_ldh_client.",
            },
        ) from e
    except httpx.RequestError as e:
        log.warning("Planning LDH request failed: %s", e)
        raise HTTPException(
            status_code=502,
            detail={
                "error": "Could not reach Planning Datahub",
                "transport": str(e),
                "hint": "Check network, firewall, and that planningdata.london.gov.uk is reachable from this machine.",
            },
        ) from e


@router.post("/planning/sync")
def post_planning_sync(
    response: Response,
    body: dict | None = Body(default=None),
):
    """
    Same as a live GET ``/api/planning/results`` but accepts an optional JSON body to override
    the Elasticsearch search payload (for experiments). Persists results to CSV.
    """
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    search_body = applications_search_body() if not body else body
    try:
        return live_fetch_and_store(search_body)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        snippet = (e.response.text or "")[:800]
        raise HTTPException(
            status_code=502,
            detail={
                "error": "Planning Datahub returned an error",
                "upstream_status": code,
                "upstream_body_preview": snippet,
            },
        ) from e
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=502,
            detail={"error": "Could not reach Planning Datahub", "transport": str(e)},
        ) from e
