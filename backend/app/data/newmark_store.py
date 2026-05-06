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


def _region_filter_key_index() -> int:
    """0-based index into the SELECT result row (see _select_row_layout); default 8."""
    raw = (os.getenv("NEWMARK_REGION_KEY_INDEX") or "").strip()
    if raw.isdigit():
        return max(0, int(raw))
    return 8


def _ge_filter_key_index() -> int | None:
    """Layout index from NEWMARK_GE_INVOLVEMENT_KEY_INDEX only when set (no default — avoids wrong column)."""
    raw = (os.getenv("NEWMARK_GE_INVOLVEMENT_KEY_INDEX") or "").strip()
    if raw.isdigit():
        return max(0, int(raw))
    return None


def _norm_region_token(raw: Any) -> str:
    s = str(raw or "").strip().lower().replace("\u00a0", " ").replace("-", " ")
    return re.sub(r"\s+", " ", s).strip()


def _norm_ge_involvement_value(raw: Any) -> str:
    """Normalise GE involvement cell values (slashes / spaces); used only for value matching."""
    s = str(raw or "").strip().lower().replace("\u00a0", " ")
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s*/\s*", "/", s)
    return s.strip()


_GE_INVOLVEMENT_ALLOWED: frozenset[str] = frozenset(
    {
        _norm_ge_involvement_value("Buying/Purchased"),
        _norm_ge_involvement_value("Selling Sold"),
        _norm_ge_involvement_value("Selling/Sold"),
        _norm_ge_involvement_value("Yes"),
    }
)


def _looks_like_ge_involvement_header(name: str) -> bool:
    """Match the GE involvement column by header text (e.g. \"GE Involvement\")."""
    low = _norm_region_token(name)
    if "ge" not in low:
        return False
    if "involvement" in low:
        return True
    if "involv" in low:
        return True
    return False


def _layout_column_matching(names: tuple[str, ...], intent: str) -> str | None:
    """Map configured header text to the exact column label returned by SELECT (spacing/case-insensitive)."""
    target = _norm_region_token(intent)
    if not target:
        return None
    for c in names:
        if c == "_rowid_":
            continue
        if _norm_region_token(c) == target:
            return c
    return None


# Cache: (column_names, db_path_key, table_name, db_mtime) so ingest / replace DB refreshes layout.
_LAYOUT_CACHE: tuple[tuple[str, ...], str, str, float] | None = None


def _select_row_layout() -> tuple[str, ...]:
    """
    Column names in the exact order returned by `SELECT rowid AS _rowid_, * FROM <table>`.
    This matches sqlite3.Row integer indices and reliable access by name (Cursor.description),
    avoiding subtle mismatches with list(r.keys()).
    """
    global _LAYOUT_CACHE
    dbp = _db_path()
    table = _table_name()
    db_key = str(dbp.resolve())
    try:
        mtime = float(dbp.stat().st_mtime) if dbp.exists() else -1.0
    except OSError:
        mtime = -1.0
    if _LAYOUT_CACHE is not None:
        names0, kdb, kt, km = _LAYOUT_CACHE
        if kdb == db_key and kt == table and km == mtime:
            return names0
    try:
        with _conn() as c:
            c.row_factory = sqlite3.Row
            cur = c.execute(f"SELECT rowid AS _rowid_, * FROM {table} WHERE 0")
            desc = cur.description
    except Exception:  # noqa: BLE001
        return ()
    if not desc:
        return ()
    names = tuple(str(d[0]) for d in desc)
    _LAYOUT_CACHE = (names, db_key, table, mtime)
    return names


def _region_column_name() -> str | None:
    """Result column used for London / South East filter."""
    env = (os.getenv("NEWMARK_REGION_COLUMN") or "").strip()
    names = _select_row_layout()
    if not names:
        return None
    if env:
        hit = _layout_column_matching(names, env)
        if hit:
            return hit
        if env in names:
            return env
        return None
    idx = _region_filter_key_index()
    if idx < 0 or idx >= len(names):
        return None
    return names[idx]


def _ge_column_name() -> str | None:
    """
    Resolve GE involvement column for filtering: env (fuzzy-matched to layout), explicit index,
    canonical \"GE Involvement\", then header heuristic.
    """
    names = _select_row_layout()
    if not names:
        return None
    env = (os.getenv("NEWMARK_GE_INVOLVEMENT_COLUMN") or "").strip()
    if env:
        hit = _layout_column_matching(names, env)
        if hit:
            return hit
        if env in names:
            return env
        return None
    idx = _ge_filter_key_index()
    if idx is not None and 0 <= idx < len(names):
        return names[idx]
    canon = _layout_column_matching(names, "GE Involvement")
    if canon:
        return canon
    for col in names:
        if col == "_rowid_":
            continue
        if _looks_like_ge_involvement_header(col):
            return col
    return None


def _row_value(r: sqlite3.Row, column: str) -> Any:
    try:
        return r[column]
    except (KeyError, IndexError, ValueError):
        return None


def _row_passes_region_filter(r: sqlite3.Row) -> bool:
    """Keep rows where the region column normalises to London or South East."""
    allowed = frozenset({"london", "south east"})
    col = _region_column_name()
    if not col:
        return False
    val = _norm_region_token(_row_value(r, col))
    return val in allowed


def _row_passes_ge_involvement_filter(r: sqlite3.Row) -> bool:
    """Keep rows where the GE column matches the allowed list. Unresolved column rejects rows (no silent skip)."""
    allowed = _GE_INVOLVEMENT_ALLOWED
    col = _ge_column_name()
    if not col:
        return False
    val = _norm_ge_involvement_value(_row_value(r, col))
    return val in allowed


def _row_passes_newmark_filters(r: sqlite3.Row) -> bool:
    """Both filters must pass (short-circuit AND — same as running one after the other, not parallel)."""
    if not _row_passes_region_filter(r):
        return False
    if not _row_passes_ge_involvement_filter(r):
        return False
    return True


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
    layout = _select_row_layout()
    reg_col = _region_column_name()
    ge_col = _ge_column_name()
    ge_from_env = bool(
        (os.getenv("NEWMARK_GE_INVOLVEMENT_KEY_INDEX") or "").strip().isdigit()
        or (os.getenv("NEWMARK_GE_INVOLVEMENT_COLUMN") or "").strip()
    )
    region_from_env = bool((os.getenv("NEWMARK_REGION_COLUMN") or "").strip())
    ge_idx = layout.index(ge_col) if ge_col and ge_col in layout else None
    reg_idx = layout.index(reg_col) if reg_col and reg_col in layout else None
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
        "select_row_layout": list(layout),
        "region_filter_key_index": _region_filter_key_index(),
        "region_column_name": reg_col,
        "region_column_from_env": region_from_env,
        "ge_filter_key_index": _ge_filter_key_index(),
        "ge_involvement_row_key_index": ge_idx,
        "ge_involvement_column_name": ge_col,
        "ge_involvement_key_from_env": ge_from_env,
        "ge_involvement_allowed": [
            "Buying/Purchased",
            "Selling Sold",
            "Selling/Sold",
            "Yes",
        ],
    }


def preview_rows(limit: int = 20, offset: int = 0, *, skip_region_filter: bool = False) -> dict[str, Any]:
    table = _table_name()
    cap = max(1, min(int(limit), 200))
    off = max(0, int(offset))
    try:
        with _conn() as c:
            c.row_factory = sqlite3.Row
            all_rows = c.execute(f"SELECT rowid AS _rowid_, * FROM {table}").fetchall()
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
    if skip_region_filter:
        filtered = list(all_rows)
        filter_meta: dict[str, Any] = {"applied": False}
    else:
        filtered = [r for r in all_rows if _row_passes_newmark_filters(r)]
        layout = _select_row_layout()
        reg_col = _region_column_name()
        ge_col = _ge_column_name()
        ge_idx = layout.index(ge_col) if ge_col and ge_col in layout else None
        reg_idx = layout.index(reg_col) if reg_col and reg_col in layout else None
        filter_meta = {
            "applied": True,
            "region": {
                "row_key_index": _region_filter_key_index(),
                "column": reg_col,
                "layout_index": reg_idx,
                "values": ["London", "South East"],
            },
            "ge_involvement": {
                "row_key_index": _ge_filter_key_index(),
                "column": ge_col,
                "layout_index": ge_idx,
                "values": ["Buying/Purchased", "Selling Sold", "Selling/Sold", "Yes"],
                "active": ge_col is not None,
                "disabled": ge_col is None,
            },
        }
    page = filtered[off : off + cap]
    if not page:
        cols = list(filtered[0].keys()) if filtered else (list(all_rows[0].keys()) if all_rows else [])
        return {
            "ok": True,
            "db_path": str(_db_path()),
            "table": table,
            "tables_present": _list_tables(),
            "filter": filter_meta,
            "total_row_count": len(all_rows),
            "preview_row_count": len(filtered),
            "columns": cols,
            "rows": [],
        }
    columns = list(page[0].keys())
    out_rows = [[r[col] for col in columns] for r in page]
    return {
        "ok": True,
        "db_path": str(_db_path()),
        "table": table,
        "tables_present": _list_tables(),
        "filter": filter_meta,
        "total_row_count": len(all_rows),
        "preview_row_count": len(filtered),
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
    layout = _select_row_layout()

    with _conn() as c:
        c.row_factory = sqlite3.Row
        cur = c.execute(f"SELECT rowid AS _rowid_, * FROM {table}")
        rows = cur.fetchall()

    if not rows:
        return []

    out: list[dict[str, Any]] = []
    for r in rows:
        if not _row_passes_newmark_filters(r):
            continue
        if coords_idx < 0 or coords_idx >= len(layout):
            continue
        coord_col = layout[coords_idx]
        coords_raw = r[coord_col]
        parsed = _parse_coords(coords_raw)
        if not parsed:
            continue
        lat, lon = parsed
        props = {k: r[k] for k in layout if k not in {"_rowid_"}}
        out.append({"id": int(r["_rowid_"]), "lat": lat, "lon": lon, "props": props})
        if len(out) >= cap:
            break
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

