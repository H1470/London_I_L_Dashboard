from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable


def _db_path() -> Path:
    env = (os.getenv("NEWMARK_DB_PATH") or "").strip()
    if env:
        return Path(env)
    # backend/app/data/<this>.py -> backend/data/
    return Path(__file__).resolve().parents[2] / "data" / "newmark_combined.db"


def _table_name() -> str:
    return (os.getenv("NEWMARK_TABLE") or "master_all").strip() or "master_all"


def _coords_col_index_0based() -> int:
    # 0-based index into the combined `master_all` row (sqlite3.Row order: rowid, then columns).
    # Override with NEWMARK_COORD_COL_INDEX if the sheet layout changes.
    raw = (os.getenv("NEWMARK_COORD_COL_INDEX") or "").strip()
    if raw.isdigit():
        return max(0, int(raw))
    return 7


_COORDS_RE = re.compile(
    r"""
    (?:
      POINT\s*\(\s*(?P<lon1>-?\d+(?:\.\d+)?)\s+(?P<lat1>-?\d+(?:\.\d+)?)\s*\)
      |
      \(\s*(?P<a>-?\d+(?:\.\d+)?)\s*,\s*(?P<b>-?\d+(?:\.\d+)?)\s*\)
      |
      (?P<c>-?\d+(?:\.\d+)?)\s*,\s*(?P<d>-?\d+(?:\.\d+)?)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _parse_coords(raw: Any) -> tuple[float, float] | None:
    """
    Returns (lat, lon) or None.
    Accepts: "51.5,-0.12", "(51.5, -0.12)", "POINT (-0.12 51.5)".
    If it looks like lon/lat, swaps automatically.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s.lower() in {"nan", "none"}:
        return None
    m = _COORDS_RE.search(s)
    if not m:
        return None
    if m.group("lat1") and m.group("lon1"):
        lon = float(m.group("lon1"))
        lat = float(m.group("lat1"))
    else:
        a = m.group("a") or m.group("c")
        b = m.group("b") or m.group("d")
        if a is None or b is None:
            return None
        lat = float(a)
        lon = float(b)

    # Heuristic swap if first number can't be latitude
    if abs(lat) > 90 and abs(lon) <= 90:
        lat, lon = lon, lat

    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(_db_path(), timeout=30)


def _list_tables() -> list[str]:
    try:
        with _conn() as c:
            cur = c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            return [r[0] for r in cur.fetchall()]
    except Exception:  # noqa: BLE001
        return []


def table_schema() -> dict[str, Any]:
    """
    Return the schema/column order for the configured table.
    Useful for confirming which column index contains coordinates.
    """
    table = _table_name()
    try:
        with _conn() as c:
            c.row_factory = sqlite3.Row
            cols = c.execute(f"PRAGMA table_info({table})").fetchall()
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": str(exc),
            "db_path": str(_db_path()),
            "table": table,
            "tables_present": _list_tables(),
            "coords_col_index_0based": _coords_col_index_0based(),
        }
    return {
        "ok": True,
        "db_path": str(_db_path()),
        "table": table,
        "tables_present": _list_tables(),
        "columns": [
            {
                "cid": int(r["cid"]),
                "name": str(r["name"]),
                "type": str(r["type"] or ""),
                "notnull": bool(r["notnull"]),
                "pk": bool(r["pk"]),
            }
            for r in cols
        ],
        "coords_col_index_0based": _coords_col_index_0based(),
    }


def preview_rows(limit: int = 20, offset: int = 0) -> dict[str, Any]:
    table = _table_name()
    cap = max(1, min(int(limit), 200))
    off = max(0, int(offset))
    try:
        with _conn() as c:
            c.row_factory = sqlite3.Row
            rows = c.execute(f"SELECT rowid AS _rowid_, * FROM {table} LIMIT ? OFFSET ?", (cap, off)).fetchall()
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": str(exc),
            "db_path": str(_db_path()),
            "table": table,
            "tables_present": _list_tables(),
            "columns": [],
            "rows": [],
        }
    if not rows:
        return {"ok": True, "db_path": str(_db_path()), "table": table, "tables_present": _list_tables(), "columns": [], "rows": []}
    columns = list(rows[0].keys())
    out_rows = [[r[col] for col in columns] for r in rows]
    return {
        "ok": True,
        "db_path": str(_db_path()),
        "table": table,
        "tables_present": _list_tables(),
        "columns": columns,
        "rows": out_rows,
    }


def iter_points(limit: int = 5000) -> Iterable[dict[str, Any]]:
    """
    Iterate rows and yield dicts with keys: id, lat, lon, props (remaining columns).
    """
    table = _table_name()
    coords_idx = _coords_col_index_0based()
    cap = max(1, min(int(limit), 20000))

    with _conn() as c:
        c.row_factory = sqlite3.Row
        cur = c.execute(f"SELECT rowid AS _rowid_, * FROM {table} LIMIT ?", (cap,))
        rows = cur.fetchall()

    if not rows:
        return []

    out: list[dict[str, Any]] = []
    for r in rows:
        keys = list(r.keys())
        if coords_idx >= len(keys):
            continue
        coords_raw = r[keys[coords_idx]]
        parsed = _parse_coords(coords_raw)
        if not parsed:
            continue
        lat, lon = parsed
        props = {k: r[k] for k in keys if k not in {"_rowid_"}}
        out.append({"id": int(r["_rowid_"]), "lat": lat, "lon": lon, "props": props})
    return out


def points_geojson(limit: int = 5000) -> dict[str, Any]:
    feats = []
    for item in iter_points(limit=limit):
        feats.append(
            {
                "type": "Feature",
                "id": item["id"],
                "geometry": {"type": "Point", "coordinates": [item["lon"], item["lat"]]},
                "properties": item["props"],
            }
        )
    return {"type": "FeatureCollection", "features": feats}

