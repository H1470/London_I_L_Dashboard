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
    "valid_date",
    "decision_date",
    "last_updated",
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
    raw = (os.getenv("PLANNING_LDH_SEARCH_SIZE") or "50").strip()
    try:
        n = int(raw)
    except ValueError:
        n = 50
    return max(1, min(n, 500))


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


def _gia_existing_min_gt() -> float:
    raw = (os.getenv("PLANNING_GIA_EXISTING_MIN") or "20000").strip()
    try:
        return float(raw)
    except ValueError:
        return 20000.0


def _floorspace_nested_path() -> str:
    return (os.getenv("PLANNING_LDH_FLOORS_PATH") or "existing_proposed_floorspace_details").strip()


def _use_nested_floors() -> bool:
    """
    Use Elasticsearch ``nested`` query only if the index maps ``existing_proposed_floorspace_details``
    as ``nested``. Planning London Datahub's ``applications`` index uses ``object`` (not nested),
    so the default is **off**. Set ``PLANNING_LDH_FLOORS_NESTED=1`` only for indices that declare a
    nested mapping for this path.
    """
    raw = (os.getenv("PLANNING_LDH_FLOORS_NESTED") or "0").strip().lower()
    return raw in ("1", "true", "yes")


def _floorspace_filter() -> dict[str, Any]:
    """
    Floorspace slice: ``use_class`` contains B8 or B2 (wildcard), AND ``gia_existing`` > threshold.

    By default this is a plain ``bool`` filter on dotted field paths (object/array-of-objects mapping).
    With ``PLANNING_LDH_FLOORS_NESTED=1``, wraps in ``nested`` — required only if the index mapping
    defines ``existing_proposed_floorspace_details`` as ``nested`` (otherwise ES returns 400:
    ``failed to find nested object under path``).
    """
    path = _floorspace_nested_path()
    p = f"{path}."
    gia_min = _gia_existing_min_gt()
    # Text vs keyword subfields: try both so wildcard is not silently empty.
    use_should: list[dict[str, Any]] = []
    for code in ("B8", "B2"):
        for suf in ("", ".keyword"):
            field = f"{p}use_class{suf}"
            use_should.append({"wildcard": {field: f"*{code}*"}})
    inner: dict[str, Any] = {
        "bool": {
            "must": [
                {"range": {f"{p}gia_existing": {"gt": gia_min}}},
                {
                    "bool": {
                        "should": use_should,
                        "minimum_should_match": 1,
                    },
                },
            ]
        }
    }
    if _use_nested_floors():
        return {"nested": {"path": path, "query": inner}}
    return inner


def applications_search_body() -> dict[str, Any]:
    """
    Default ``applications/_search`` body for Planning London Datahub (Elasticsearch 7.9).

    **Filters**

    - ``appeal_start_date`` **>** ``PLANNING_APPEAL_START_AFTER`` (default ``01/01/2025``, DD/MM/YYYY
      as in the connection guide).
    - Floorspace: ``use_class`` contains **B8** or **B2** (``wildcard``), and ``gia_existing`` **>**
      ``PLANNING_GIA_EXISTING_MIN`` (default ``20000``). Default query shape matches LDH ``object``
      mapping; optional ``nested`` wrapper via ``PLANNING_LDH_FLOORS_NESTED=1`` if your index uses it.

    **Projection** — ``_source`` includes UPRN, description-style fields, LPA identifiers,
    appeal and decision dates, and the floorspace array. Tweak ``_PLANNING_SOURCE_FIELDS`` if the
    technical schema uses different property names.

    **Query mode** — ``PLANNING_QUERY_MODE``:

    - ``full`` (default): appeal date + B2/B8 floorspace + GIA filters.
    - ``match_all``: no filters (smoke test — verifies connectivity and table UI).
    """
    _load_env()
    mode = (os.getenv("PLANNING_QUERY_MODE") or "full").strip().lower()
    if mode in ("match_all", "smoke", "test"):
        return {
            "query": {"match_all": {}},
            "size": _search_size(),
            "_source": list(_PLANNING_SOURCE_FIELDS),
        }
    return {
        "query": {
            "bool": {
                "filter": [
                    {"range": {"appeal_start_date": {"gt": _appeal_start_gt()}}},
                    _floorspace_filter(),
                ]
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
