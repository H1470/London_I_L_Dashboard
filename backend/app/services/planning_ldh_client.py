"""
Planning London Datahub (Elasticsearch guest API).

Base URL, header name/value, and search body are driven by env (see ``backend/.env.example``).
Guest access uses header ``X-API-AllowRequest`` per the Datahub connection guide.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger(__name__)

_DEFAULT_BASE = "https://planningdata.london.gov.uk/api-guest"
_DEFAULT_HEADER_NAME = "X-API-AllowRequest"
_SEARCH_PATH = "applications/_search"
# Elasticsearch ``size`` for ``applications/_search``.
# Planning Datahub rejects ``from`` + ``size`` > ``index.max_result_window`` (10000 on this index).
_SEARCH_SIZE_DEFAULT = 10000
_SEARCH_SIZE_MAX = 10000

# Returned fields: UPRN + descriptions first; include floorspace slice and appeal context.
# (Adjust names against planninglondondatahub_public_technical_schemav2.1.xlsx if the API omits any.)
_PLANNING_SOURCE_FIELDS: tuple[str, ...] = (
    "id",
    "uprn",
    "description",
    "description_of_development",
    "development_description",
    "proposal",
    "application_location",
    "site_address",
    "lpa_name",
    "lpa_app_no",
    "application_type",
    "appeal_start_date",
    "status",
    "valid_date",
    "decision_date",
    "last_updated",
    "application_details",
    "existing_proposed_floorspace_details",
)

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    here = Path(__file__).resolve()
    load_dotenv(here.parents[3] / ".env", override=False)
    load_dotenv(here.parents[2] / ".env", override=True)


def _base_url() -> str:
    raw = (os.getenv("PLANNING_LDH_BASE_URL") or _DEFAULT_BASE).strip().rstrip("/")
    return raw or _DEFAULT_BASE


def _header_pair() -> tuple[str, str]:
    name = (os.getenv("PLANNING_LDH_HEADER_NAME") or _DEFAULT_HEADER_NAME).strip() or _DEFAULT_HEADER_NAME
    value = (os.getenv("PLANNING_LDH_HEADER_VALUE") or "").strip()
    return name, value


def _search_size() -> int:
    raw = (os.getenv("PLANNING_LDH_SEARCH_SIZE") or str(_SEARCH_SIZE_DEFAULT)).strip()
    try:
        n = int(raw)
    except ValueError:
        n = _SEARCH_SIZE_DEFAULT
    return max(1, min(n, _SEARCH_SIZE_MAX))


def _appeal_start_gt() -> str:
    """
    Lower bound for ``range`` on ``appeal_start_date`` (exclusive ``gt`` in the query).

    Planning London Datahub maps this field with format **dd/MM/yyyy** — ISO strings such as
    ``2025-01-01`` are rejected (HTTP 400). Default matches the connection guide: ``01/01/2025``.

    Override with ``PLANNING_APPEAL_START_AFTER`` (must use the same format the index expects).
    """
    raw = (os.getenv("PLANNING_APPEAL_START_AFTER") or "").strip()
    if raw:
        return raw
    return "01/01/2025"


# ``decision_date`` range lower bound (exclusive ``gt``). LDH expects **dd/MM/yyyy** as written here — not ISO.
_DECISION_DATE_GT = "01/01/2025"


def _decision_date_filter() -> dict[str, Any]:
    """``decision_date`` > ``_DECISION_DATE_GT`` (AND with other ``bool`` ``filter`` clauses)."""
    return {"range": {"decision_date": {"gt": _DECISION_DATE_GT}}}


def _es_gia_existing_floorspace_gt_threshold() -> float:
    """
    Exclusive ``gt`` for GIA in Elasticsearch (see ``_application_details_gia_existing_filter``).

    Env ``PLANNING_ES_GIA_EXISTING_GT`` (default ``10000``). Set e.g. ``20000`` when you want a stricter pull.
    """
    raw = (os.getenv("PLANNING_ES_GIA_EXISTING_GT") or "10000").strip()
    try:
        return float(raw)
    except ValueError:
        return 10000.0


def planning_es_gia_existing_gt() -> float:
    """Lower bound (exclusive ``gt``) for the ES floorspace ``gia_existing`` range filter."""
    _load_env()
    return _es_gia_existing_floorspace_gt_threshold()


def _application_details_gia_existing_filter() -> dict[str, Any]:
    """
    GIA **>** threshold on ``application_details`` using the two places LDH stores it (no DSL “tree building”):

    - ``application_details.existing_proposed_floorspace_details.gia_existing`` (array row), or
    - ``application_details.total_gia_existing`` (rollup on the same object).

    Either match is enough (``bool`` ``should``, ``minimum_should_match`` 1).
    """
    gt = _es_gia_existing_floorspace_gt_threshold()
    return {
        "bool": {
            "should": [
                {
                    "range": {
                        "application_details.existing_proposed_floorspace_details.gia_existing": {
                            "gt": gt,
                        }
                    }
                },
                {"range": {"application_details.total_gia_existing": {"gt": gt}}},
            ],
            "minimum_should_match": 1,
        }
    }


# --- Status filter (OR across these LDH ``status`` values) ---
_PLANNING_STATUS_OR_LABELS: tuple[str, ...] = (
    "Allowed",
    "Approved",
    "Application Received",
    "Completed",
    "Commenced",
)


def planning_status_filter_labels() -> tuple[str, ...]:
    """Human-readable status values included in the default query (OR — any one may match)."""
    return _PLANNING_STATUS_OR_LABELS


def _status_clause_for_phrase(phrase: str) -> dict[str, Any]:
    """
    One status value: ``term`` / ``wildcard`` on ``status.keyword`` plus ``match_phrase`` on ``status``.

    Phrases with spaces (e.g. **Application Received**) rely on ``match_phrase``; exact keyword
    terms still match when the index stores the same string.
    """
    lower = phrase.lower()
    return {
        "bool": {
            "should": [
                {"term": {"status.keyword": phrase}},
                {"term": {"status.keyword": lower}},
                {"wildcard": {"status.keyword": f"*{phrase}*"}},
                {"wildcard": {"status.keyword": f"*{lower}*"}},
                {"match_phrase": {"status": phrase}},
            ],
            "minimum_should_match": 1,
        }
    }


def _status_filter() -> dict[str, Any]:
    """``status`` is any one of ``_PLANNING_STATUS_OR_LABELS`` (OR)."""
    return {
        "bool": {
            "should": [_status_clause_for_phrase(label) for label in _PLANNING_STATUS_OR_LABELS],
            "minimum_should_match": 1,
        }
    }


def planning_decision_date_gt() -> str:
    """Lower bound (exclusive ``gt``) used in the default ``decision_date`` filter — for API diagnostics."""
    _load_env()
    return _DECISION_DATE_GT


def planning_search_size() -> int:
    """Elasticsearch ``size`` for ``applications/_search`` (env ``PLANNING_LDH_SEARCH_SIZE``)."""
    _load_env()
    return _search_size()


def applications_search_body() -> dict[str, Any]:
    """
    Default ``applications/_search`` body for Planning London Datahub (Elasticsearch 7.9).

    **Filters** (all AND)

    - ``status`` is one of **Allowed**, **Approved**, **Application Received**, **Completed**,
      **Commenced** (OR — see ``_status_filter`` / ``planning_status_filter_labels``).
    - ``decision_date`` **>** ``01/01/2025`` as **dd/MM/yyyy** (see ``_DECISION_DATE_GT`` / ``_decision_date_filter``).
    - GIA **>** ``PLANNING_ES_GIA_EXISTING_GT`` (default ``10000``) on **either**
      ``application_details.existing_proposed_floorspace_details.gia_existing`` **or**
      ``application_details.total_gia_existing`` (see ``_application_details_gia_existing_filter``).

    Clauses are passed as Elasticsearch ``bool`` ``filter`` (required matches, no extra scoring) — that word is ES DSL,
    not an additional in-app filter pass after the search.

    **Projection** — ``_source`` includes UPRN, descriptions, LPA fields, appeal/decision dates,
    ``status``, and floorspace. Adjust ``_PLANNING_SOURCE_FIELDS`` if the schema differs.

    **Result window** — ``size`` defaults to ``_SEARCH_SIZE_DEFAULT`` (10000, LDH ``max_result_window``); env
    ``PLANNING_LDH_SEARCH_SIZE`` overrides, capped at ``_SEARCH_SIZE_MAX`` (10000). For more hits use scroll / ``search_after`` (not implemented here).
    """
    _load_env()
    filters: list[dict[str, Any]] = [
        _status_filter(),
        _decision_date_filter(),
        _application_details_gia_existing_filter(),
    ]
    return {
        "query": {
            "bool": {
                "filter": filters,
            }
        },
        "size": _search_size(),
        "_source": list(_PLANNING_SOURCE_FIELDS),
    }


def post_applications_search(body: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    POST ``applications/_search``; returns parsed JSON (``hits``, ``aggregations``, etc.).
    """
    _load_env()
    name, value = _header_pair()
    if not value:
        raise ValueError(
            "PLANNING_LDH_HEADER_VALUE is not set — add the guest allow header value to backend/.env "
            "(see .env.example)."
        )

    url = f"{_base_url()}/{_SEARCH_PATH}"
    headers = {
        name: value,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": _DEFAULT_UA,
    }
    payload = body if body is not None else applications_search_body()

    # Visible in the uvicorn terminal so long requests do not look hung (timeout 120s).
    print(f"[planning-ldh] POST {url} — starting (timeout 120s)…", flush=True)
    log.info("Planning LDH POST %s starting", url)
    t0 = time.perf_counter()
    with httpx.Client(timeout=120.0) as client:
        r = client.post(url, headers=headers, json=payload)
        elapsed = time.perf_counter() - t0
        print(
            f"[planning-ldh] HTTP {r.status_code} in {elapsed:.2f}s — parsing JSON…",
            flush=True,
        )
        log.info("Planning LDH response status=%s elapsed=%.2fs", r.status_code, elapsed)
        r.raise_for_status()
        data = r.json()
    print(f"[planning-ldh] OK — JSON parsed after {time.perf_counter() - t0:.2f}s total.", flush=True)
    return data
