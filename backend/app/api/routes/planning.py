"""Planning London Datahub: live fetch on GET (default), optional cache-only read, POST sync for overrides."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx
from fastapi import APIRouter, Body, HTTPException, Query, Response

from app.data.planning_store import (
    apply_planning_row_filters,
    fetch_table_payload,
    replace_all_from_hits,
    store_debug_snapshot,
)
from app.services.planning_ldh_client import (
    applications_search_body,
    planning_decision_date_gt,
    planning_es_gia_existing_gt,
    planning_search_size,
    planning_status_filter_labels,
    post_applications_search,
)

router = APIRouter()
log = logging.getLogger(__name__)


def _merge_client_row_filters(
    out: dict[str, Any],
    *,
    client_use_class_contains: str | None,
    client_status_contains: str | None,
    client_gia_existing_min: float | None,
) -> dict[str, Any]:
    merged = apply_planning_row_filters(
        out,
        use_class_contains=client_use_class_contains,
        status_contains=client_status_contains,
        gia_existing_min=client_gia_existing_min,
    )
    if merged.get("client_filters_applied"):
        cf = merged.get("client_filters") or {}
        pre = merged.get("pre_client_filter_row_count")
        n = merged.get("row_count")
        bit = f"Client-side row filter {cf} — showing {n} of {pre} row(s)."
        prev = merged.get("message")
        merged["message"] = f"{prev} {bit}".strip() if prev else bit
    return merged


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
    decision_gt = planning_decision_date_gt()
    status_labels = list(planning_status_filter_labels())
    es_gia_gt = planning_es_gia_existing_gt()
    _bs = body.get("size") if isinstance(body, dict) else None
    if isinstance(_bs, int) and not isinstance(_bs, bool):
        search_size = _bs
    else:
        search_size = planning_search_size()
    t0 = time.perf_counter()
    data = post_applications_search(body)
    fetch_duration_ms = (time.perf_counter() - t0) * 1000

    hit_list = _extract_hit_list(data)
    es_hits_in_response = len(hit_list)
    stored = replace_all_from_hits(hit_list)
    print(f"[planning] Wrote {stored} hit(s) to CSV; loading table for API response…", flush=True)
    log.info("Planning CSV persist complete stored=%s", stored)
    table = fetch_table_payload()

    total_val = _extract_total(data)
    timed_out = data.get("timed_out")
    query_mode = "full"

    if stored == 0:
        print(
            f"[planning] NOTE: 0 rows stored. ES reported total={total_val!r} (hits in this response: {es_hits_in_response}).",
            flush=True,
        )

    msg_parts = [
        f"Planning Datahub responded in {fetch_duration_ms:.0f} ms.",
        f"Query mode: {query_mode!r}.",
        f"Elasticsearch returned {es_hits_in_response} document(s) in this page; "
        f"{stored} row(s) written to the CSV after use_class allowlist (B8, B2, E(g)(iii)).",
    ]
    if total_val is not None:
        msg_parts.append(f"Reported total hit count (ES): {total_val}.")
    if timed_out:
        msg_parts.append("Warning: Elasticsearch reported timed_out=true.")
    if stored == 0:
        joined = ", ".join(status_labels)
        if es_hits_in_response > 0:
            msg_parts.append(
                f"No CSV rows: all **{es_hits_in_response}** hit(s) from this response were removed by the "
                "**use_class** store allowlist (**B8**, **B2**, **E(g)(iii)** only — exact segment match on floorspace)."
            )
        else:
            msg_parts.append(
                f"No matches: **status** is one of ({joined}) (OR), **decision_date** > {decision_gt} (dd/MM/yyyy), "
                f"**application_details** GIA > {es_gia_gt} (floorspace gia_existing OR total_gia_existing). "
                "Adjust filters or env in planning_ldh_client.py / .env if needed."
            )

    out: dict[str, Any] = {
        **table,
        "ok": True,
        "live_fetch": True,
        "cache_only": False,
        "fetch_duration_ms": round(fetch_duration_ms, 1),
        "upstream_stored_hits": stored,
        "es_hits_in_response": es_hits_in_response,
        "elasticsearch_total": total_val,
        "timed_out": timed_out,
        "query_mode": query_mode,
        "decision_date_gt": decision_gt,
        "status_filter_labels": status_labels,
        "es_gia_existing_gt": es_gia_gt,
        "planning_search_size": search_size,
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
    client_use_class_contains: str | None = Query(
        None,
        description="After load: keep rows whose floorspace use_class cell contains this substring (case-insensitive).",
    ),
    client_status_contains: str | None = Query(
        None,
        description="After load: keep rows whose status cell contains this substring (case-insensitive).",
    ),
    client_gia_existing_min: float | None = Query(
        None,
        ge=0,
        description="After load: further restrict rows so max parsed gia_existing display value is **>** this (exclusive).",
    ),
):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"

    if cache_only:
        table = fetch_table_payload()
        out = {
            **table,
            "ok": True,
            "live_fetch": False,
            "cache_only": True,
            "query_mode": "cache_only",
            "fetch_duration_ms": None,
            "message": "Loaded from local CSV only — no request was sent to Planning Datahub.",
        }
        return _merge_client_row_filters(
            out,
            client_use_class_contains=client_use_class_contains,
            client_status_contains=client_status_contains,
            client_gia_existing_min=client_gia_existing_min,
        )

    try:
        out = live_fetch_and_store(None)
        return _merge_client_row_filters(
            out,
            client_use_class_contains=client_use_class_contains,
            client_status_contains=client_status_contains,
            client_gia_existing_min=client_gia_existing_min,
        )
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
