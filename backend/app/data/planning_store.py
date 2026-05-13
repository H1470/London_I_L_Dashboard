"""
Pandas-backed file store for Planning London Datahub ``applications`` search hits.

**Storage:** CSV file (default ``backend/data/planning_applications.csv``), overridden by
``PLANNING_STORE_PATH``. No standalone SQLite installation is required; pandas reads/writes
the file like a simple table.

If ``planning_london.db`` exists from an older build and the CSV does not, rows are copied
once from that SQLite file into the new CSV (best-effort migration).

Each sync replaces the entire file with the latest API response.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

_CSV_COLUMNS = ("application_id", "hit_json", "updated_at")


def _csv_path() -> Path:
    explicit = (os.getenv("PLANNING_STORE_PATH") or "").strip()
    if explicit:
        return Path(explicit)
    return Path(__file__).resolve().parents[2] / "data" / "planning_applications.csv"


def _legacy_sqlite_candidates() -> list[Path]:
    out: list[Path] = []
    env = (os.getenv("PLANNING_DB_PATH") or "").strip()
    if env.endswith(".db"):
        out.append(Path(env))
    out.append(Path(__file__).resolve().parents[2] / "data" / "planning_london.db")
    seen: set[str] = set()
    uniq: list[Path] = []
    for p in out:
        k = str(p.resolve())
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    return uniq


def _migrate_sqlite_to_csv_if_needed(csv_path: Path) -> None:
    """One-time copy from legacy SQLite into CSV when CSV is missing."""
    if csv_path.exists():
        return
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    for legacy in _legacy_sqlite_candidates():
        if not legacy.is_file():
            continue
        try:
            con = sqlite3.connect(legacy)
            con.row_factory = sqlite3.Row
            cur = con.execute(
                "SELECT application_id, hit_json, updated_at FROM planning_application ORDER BY application_id"
            )
            rows = [dict(r) for r in cur.fetchall()]
            con.close()
            if not rows:
                continue
            pd.DataFrame(rows, columns=list(_CSV_COLUMNS)).to_csv(csv_path, index=False)
            return
        except (OSError, sqlite3.Error, ValueError, TypeError):
            continue


def replace_all_from_hits(hits: list[dict[str, Any]]) -> int:
    """Replace CSV contents with ES ``hits.hits`` list (after store use_class allowlist); returns number of rows stored."""
    hits = filter_hits_store_use_class_allowlist(hits)
    now = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, str]] = []
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        src = hit.get("_source")
        if not isinstance(src, dict):
            src = {}
        app_id = str(hit.get("_id") or src.get("id") or "").strip()
        if not app_id:
            continue
        rows.append(
            {
                "application_id": app_id,
                "hit_json": json.dumps(hit, ensure_ascii=False),
                "updated_at": now,
            }
        )

    path = _csv_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows, columns=list(_CSV_COLUMNS))
    df.to_csv(path, index=False)
    return len(df)


def _scalar_cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def _flatten_source(obj: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in obj.items():
        if isinstance(v, (dict, list)):
            out[k] = json.dumps(v, ensure_ascii=False)
        elif v is None:
            out[k] = ""
        else:
            out[k] = v
    return out


def _existing_proposed_floorspace_details_from_source(src: dict[str, Any]) -> Any:
    """Floorspace object/array from ``_source`` — top-level or under ``application_details``."""
    ep = src.get("existing_proposed_floorspace_details")
    if ep is not None:
        return ep
    ad = src.get("application_details")
    if isinstance(ad, dict):
        return ad.get("existing_proposed_floorspace_details")
    return None


def _gia_existing_from_source(src: dict[str, Any]) -> str:
    """``gia_existing`` from floorspace slice or ``application_details.total_gia_existing`` fallback."""
    ep = _existing_proposed_floorspace_details_from_source(src)
    cell = ""
    if isinstance(ep, dict):
        cell = _scalar_cell(ep.get("gia_existing"))
    elif isinstance(ep, list):
        parts: list[str] = []
        for item in ep:
            if isinstance(item, dict) and "gia_existing" in item:
                parts.append(_scalar_cell(item.get("gia_existing")))
        cell = "; ".join(x for x in parts if x)
    if cell:
        return cell
    ad = src.get("application_details")
    if isinstance(ad, dict) and ad.get("total_gia_existing") is not None:
        return _scalar_cell(ad.get("total_gia_existing"))
    return ""


def _use_class_from_source(src: dict[str, Any]) -> str:
    """``use_class`` from floorspace in ``_source`` (top-level or under ``application_details``)."""
    ep = _existing_proposed_floorspace_details_from_source(src)
    if ep is None:
        return ""
    if isinstance(ep, dict):
        return _scalar_cell(ep.get("use_class"))
    if isinstance(ep, list):
        parts: list[str] = []
        for item in ep:
            if isinstance(item, dict) and "use_class" in item:
                parts.append(_scalar_cell(item.get("use_class")))
        return "; ".join(x for x in parts if x)
    return ""


def _polygon_from_source(src: dict[str, Any]) -> str:
    """Site / application polygon from ``_source`` (top-level or under ``application_details``), as JSON text for the table."""
    p = src.get("polygon")
    if p is not None:
        return _scalar_cell(p)
    ad = src.get("application_details")
    if isinstance(ad, dict) and ad.get("polygon") is not None:
        return _scalar_cell(ad.get("polygon"))
    return ""


_USE_CLASS_COL_AD = "application_details.existing_proposed_floorspace_details.use_class"
_USE_CLASS_COL_TOP = "existing_proposed_floorspace_details.use_class"
_GIA_COL_AD = "application_details.existing_proposed_floorspace_details.gia_existing"
_GIA_COL_TOP = "existing_proposed_floorspace_details.gia_existing"

# After ES fetch: only persist / show rows whose floorspace ``use_class`` cell contains at least one of these (``;``-separated segments, exact match).
PLANNING_STORE_USE_CLASS_ALLOWLIST: tuple[str, ...] = ("B8", "B2", "E(g)(iii)")


def _use_class_allowlist_tokens() -> frozenset[str]:
    return frozenset(PLANNING_STORE_USE_CLASS_ALLOWLIST)


def use_class_cell_matches_store_allowlist(cell: str) -> bool:
    """True if any ``;``-split segment of ``cell`` equals one of ``PLANNING_STORE_USE_CLASS_ALLOWLIST`` (trimmed, exact)."""
    if not (cell or "").strip():
        return False
    allowed = _use_class_allowlist_tokens()
    for part in cell.split(";"):
        if part.strip() in allowed:
            return True
    return False


def hit_matches_store_use_class_allowlist(hit: dict[str, Any]) -> bool:
    """True if the hit's ``_source`` floorspace ``use_class`` matches the store allowlist (see ``use_class_cell_matches_store_allowlist``)."""
    if not isinstance(hit, dict):
        return False
    src = hit.get("_source")
    if not isinstance(src, dict):
        src = {}
    return use_class_cell_matches_store_allowlist(_use_class_from_source(src))


def filter_hits_store_use_class_allowlist(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Subset of ``hits`` that pass ``hit_matches_store_use_class_allowlist`` (for CSV replace)."""
    return [h for h in hits if isinstance(h, dict) and hit_matches_store_use_class_allowlist(h)]


def _use_class_cell(row: dict[str, Any]) -> str:
    return str(row.get(_USE_CLASS_COL_AD) or row.get(_USE_CLASS_COL_TOP) or "")


def _gia_numeric_max_from_display_cell(cell: str) -> float | None:
    """Best-effort max numeric from ``gia_existing`` display cell (``;``-joined segments)."""
    if not (cell or "").strip():
        return None
    nums: list[float] = []
    for part in cell.split(";"):
        t = part.strip()
        if not t:
            continue
        try:
            nums.append(float(t))
        except ValueError:
            continue
    return max(nums) if nums else None


def apply_planning_row_filters(
    payload: dict[str, Any],
    *,
    use_class_contains: str | None = None,
    status_contains: str | None = None,
    gia_existing_min: float | None = None,
) -> dict[str, Any]:
    """
    Return a shallow copy of a ``fetch_table_payload`` / API merge dict with ``rows`` filtered in memory.

    Use when Elasticsearch nested/object floorspace queries are awkward but the table already has
    denormalised ``use_class`` / ``gia_existing`` columns. CSV on disk is unchanged.
    """
    out = dict(payload)
    rows = out.get("rows")
    if not isinstance(rows, list):
        out["client_filters_applied"] = False
        return out

    has_uc = bool((use_class_contains or "").strip())
    has_st = bool((status_contains or "").strip())
    has_gia = gia_existing_min is not None
    if not has_uc and not has_st and not has_gia:
        out["client_filters_applied"] = False
        return out

    uc_needle = (use_class_contains or "").strip().lower()
    st_needle = (status_contains or "").strip().lower()
    gia_min = float(gia_existing_min) if has_gia else None

    def keep(row: dict[str, Any]) -> bool:
        if not isinstance(row, dict):
            return False
        if has_uc and uc_needle not in _use_class_cell(row).lower():
            return False
        if has_st and st_needle not in str(row.get("status") or "").lower():
            return False
        if has_gia and gia_min is not None:
            cell = str(row.get(_GIA_COL_AD) or row.get(_GIA_COL_TOP) or "")
            mx = _gia_numeric_max_from_display_cell(cell)
            if mx is None or mx <= gia_min:
                return False
        return True

    pre_n = len(rows)
    filtered = [r for r in rows if keep(r)]
    out["rows"] = filtered
    out["row_count"] = len(filtered)
    out["client_filters_applied"] = True
    out["pre_client_filter_row_count"] = pre_n
    out["client_filters"] = {
        k: v
        for k, v in (
            ("use_class_contains", (use_class_contains or "").strip() if has_uc else None),
            ("status_contains", (status_contains or "").strip() if has_st else None),
            ("gia_existing_min", gia_existing_min if has_gia else None),
        )
        if v is not None
    }
    return out


_COLUMN_PRIORITY: tuple[str, ...] = (
    "id",
    "uprn",
    "description",
    "description_of_development",
    "development_description",
    "proposal",
    "application_location",
    "site_address",
    "polygon",
    "lpa_name",
    "lpa_app_no",
    "application_type",
    "appeal_start_date",
    "status",
    "valid_date",
    "decision_date",
    "last_updated",
    "application_details.existing_proposed_floorspace_details.use_class",
    "existing_proposed_floorspace_details.use_class",
    "application_details.existing_proposed_floorspace_details.gia_existing",
    "existing_proposed_floorspace_details.gia_existing",
    "existing_proposed_floorspace_details",
)


def store_debug_snapshot() -> dict[str, Any]:
    """Lightweight CSV diagnostics for troubleshooting persistence (local/dev)."""
    path = _csv_path().resolve()
    out: dict[str, Any] = {
        "csv_path": str(path),
        "exists": path.is_file(),
        "size_bytes": path.stat().st_size if path.is_file() else 0,
        "store_kind": "pandas_csv",
    }
    if not path.is_file() or path.stat().st_size == 0:
        out["pandas_row_count"] = 0
        out["sample_application_ids"] = []
        return out
    try:
        st = path.stat()
        out["mtime_utc"] = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()
    except OSError:
        pass
    try:
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        out["pandas_row_count"] = len(df)
        out["columns_in_csv"] = list(df.columns)
        if "application_id" in df.columns:
            out["sample_application_ids"] = (
                df["application_id"].dropna().astype(str).head(8).tolist()
            )
        else:
            out["sample_application_ids"] = []
        hit_preview = ""
        if "hit_json" in df.columns and len(df.index) > 0:
            raw = str(df.iloc[0]["hit_json"])
            hit_preview = raw[:240] + ("…" if len(raw) > 240 else "")
        out["first_hit_json_preview"] = hit_preview
    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError, ValueError) as e:
        out["read_error"] = str(e)
    return out


def fetch_table_payload() -> dict[str, Any]:
    """Rows and column order for a simple HTML table, plus file-store diagnostics for the UI.

    Parsed rows are restricted to ``PLANNING_STORE_USE_CLASS_ALLOWLIST`` on the denormalised
    ``existing_proposed_floorspace_details.use_class`` cell (same value as the AD-prefixed column).
    The CSV file still holds whatever was last written by ``replace_all_from_hits`` (already filtered on sync).
    """
    _migrate_sqlite_to_csv_if_needed(_csv_path())
    path = _csv_path().resolve()

    if not path.is_file() or path.stat().st_size == 0:
        return {
            "columns": [],
            "rows": [],
            "row_count": 0,
            "sqlite_row_count": 0,
            "stored_row_count": 0,
            "parse_errors": 0,
            "db_path": str(path),
            "store_path": str(path),
            "store_kind": "pandas_csv",
            "store_use_class_allowlist": list(PLANNING_STORE_USE_CLASS_ALLOWLIST),
            "pre_use_class_allowlist_row_count": 0,
        }

    try:
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError, ValueError):
        return {
            "columns": [],
            "rows": [],
            "row_count": 0,
            "sqlite_row_count": 0,
            "stored_row_count": 0,
            "parse_errors": 0,
            "db_path": str(path),
            "store_path": str(path),
            "store_kind": "pandas_csv",
            "store_error": "Could not read CSV (file corrupt or not valid CSV).",
            "store_use_class_allowlist": list(PLANNING_STORE_USE_CLASS_ALLOWLIST),
            "pre_use_class_allowlist_row_count": 0,
        }
    for col in _CSV_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    file_row_count = len(df)

    parsed: list[dict[str, Any]] = []
    parse_errors = 0
    key_set: set[str] = set()
    for _, r in df.iterrows():
        try:
            hit = json.loads(r["hit_json"])
        except (json.JSONDecodeError, TypeError):
            parse_errors += 1
            continue
        src = hit.get("_source")
        if not isinstance(src, dict):
            src = {}
        flat = _flatten_source(src)
        # Omit raw nested object from the table (debug-only noise); floorspace is still in denormalised columns below.
        flat.pop("application_details", None)
        flat["polygon"] = _polygon_from_source(src)
        aid = str(r.get("application_id") or "").strip()
        if "id" not in flat and aid:
            flat["id"] = aid
        gia = _gia_existing_from_source(src)
        flat["application_details.existing_proposed_floorspace_details.gia_existing"] = gia
        flat["existing_proposed_floorspace_details.gia_existing"] = gia
        use_class = _use_class_from_source(src)
        flat["application_details.existing_proposed_floorspace_details.use_class"] = use_class
        flat["existing_proposed_floorspace_details.use_class"] = use_class
        flat["status"] = _scalar_cell(src.get("status"))
        parsed.append(flat)
        key_set.update(flat.keys())

    pre_allowlist_n = len(parsed)
    parsed = [
        r
        for r in parsed
        if isinstance(r, dict) and use_class_cell_matches_store_allowlist(_use_class_cell(r))
    ]

    ordered: list[str] = [c for c in _COLUMN_PRIORITY if c in key_set]
    ordered.extend(sorted(k for k in key_set if k not in _COLUMN_PRIORITY))

    out: dict[str, Any] = {
        "columns": ordered,
        "rows": parsed,
        "row_count": len(parsed),
        "sqlite_row_count": file_row_count,
        "stored_row_count": file_row_count,
        "parse_errors": parse_errors,
        "db_path": str(path),
        "store_path": str(path),
        "store_kind": "pandas_csv",
        "store_use_class_allowlist": list(PLANNING_STORE_USE_CLASS_ALLOWLIST),
        "pre_use_class_allowlist_row_count": pre_allowlist_n,
    }
    return out
