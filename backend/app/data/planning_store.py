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
    """Replace CSV contents with ES ``hits.hits`` list; returns number of rows stored."""
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


_COLUMN_PRIORITY: tuple[str, ...] = (
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
    """Rows and column order for a simple HTML table, plus file-store diagnostics for the UI."""
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
        aid = str(r.get("application_id") or "").strip()
        if "id" not in flat and aid:
            flat["id"] = aid
        parsed.append(flat)
        key_set.update(flat.keys())

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
    }
    return out
