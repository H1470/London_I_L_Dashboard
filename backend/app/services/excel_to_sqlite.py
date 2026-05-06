"""
Excel → SQLite helpers: read sheets with ``openpyxl``/pandas, optional row skip and
column subset (1-based Excel indices). ``usecols`` ignores list order; we reorder with
``_reorder_columns_after_int_usecols`` so merged workbooks stay column-aligned.

``_dedupe_columns`` keeps SQLite happy when Excel repeats a header (e.g. two "Address").
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


def _safe_table_name(name: str) -> str:
    s = name.strip()
    if not s:
        s = "sheet"
    s = re.sub(r"[^A-Za-z0-9_]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    if not s:
        s = "sheet"
    if s[0].isdigit():
        s = f"s_{s}"
    return s.lower()


def _mapped_drive_hint(path: Path) -> str | None:
    p = str(path)
    if re.match(r"^[A-Za-z]:\\", p):
        drive = p[0].upper()
        return (
            f"If this is a mapped drive ({drive}:), scheduled tasks/services may not see it. "
            "Prefer a UNC path (\\\\server\\share\\...) or run under a user session that has the drive mapped."
        )
    return None


def _reorder_columns_after_int_usecols(df: pd.DataFrame, keep_columns_1based: list[int]) -> pd.DataFrame:
    """
    pandas read_excel(usecols=[ints]) ignores list order and uses ascending column index.
    Restore the caller's 1-based Excel column order after a subset read.
    """
    order_0 = [max(0, int(c) - 1) for c in keep_columns_1based]
    unique_sorted = sorted(set(order_0))
    if not unique_sorted:
        return df
    pos = {excel_idx: j for j, excel_idx in enumerate(unique_sorted)}
    iloc_order = [pos[c] for c in order_0]
    return df.iloc[:, iloc_order].copy()


def _dedupe_columns(cols: list[object]) -> list[str]:
    """
    SQLite (and pandas.to_sql) requires unique column names.
    Excel sheets sometimes have duplicates like "Address" repeated; we suffix them.
    """
    def norm(s: str) -> str:
        # normalize whitespace so "Address" and "Address " collide
        s2 = re.sub(r"\s+", " ", s.replace("\u00A0", " ")).strip()
        return s2 or "col"

    seen: dict[str, int] = {}
    out: list[str] = []
    for c in cols:
        base = norm(str(c if c is not None else ""))
        key = base.casefold()  # case-insensitive uniqueness for SQLite
        n = seen.get(key, 0) + 1
        seen[key] = n
        out.append(base if n == 1 else f"{base}__{n}")
    return out


def read_workbook_sheet(
    *,
    workbook_path: str | Path,
    sheet_name: str,
    drop_top_rows: int = 0,
    keep_columns_1based: list[int] | None = None,
) -> dict[str, Any]:
    """
    Read one sheet into a DataFrame with the same cleaning options used by sync_workbook_to_sqlite.
    Returns {ok, df?, error?, workbook_mtime_utc?, ...}.
    """
    wb = Path(workbook_path)
    if not wb.exists():
        out: dict[str, Any] = {
            "ok": False,
            "error": "Workbook not found",
            "workbook_path": str(wb),
            "sheet": sheet_name,
        }
        hint = _mapped_drive_hint(wb)
        if hint:
            out["hint"] = hint
        return out

    stat = wb.stat()
    if keep_columns_1based:
        order_0 = [max(0, int(c) - 1) for c in keep_columns_1based]
        keep_cols_0based = sorted(set(order_0))
    else:
        order_0 = None
        keep_cols_0based = None

    try:
        df = pd.read_excel(
            wb,
            sheet_name=sheet_name,
            engine="openpyxl",
            skiprows=drop_top_rows if drop_top_rows > 0 else 0,
            header=0,
            usecols=keep_cols_0based,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": str(exc),
            "workbook_path": str(wb),
            "workbook_mtime_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            "sheet": sheet_name,
        }

    if order_0 is not None:
        df = _reorder_columns_after_int_usecols(df, keep_columns_1based)
    df.columns = _dedupe_columns(list(df.columns))

    return {
        "ok": True,
        "workbook_path": str(wb),
        "workbook_mtime_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        "sheet": sheet_name,
        "rows": int(df.shape[0]),
        "cols": int(df.shape[1]),
        "df": df,
    }


def sync_workbook_to_sqlite(
    *,
    workbook_path: str | Path,
    db_path: str | Path,
    only_sheets: list[str] | None = None,
    drop_top_rows: int = 0,
    keep_columns_1based: list[int] | None = None,
    table_name: str | None = None,
) -> dict[str, Any]:
    """
    Read an Excel workbook (including .xlsm) and write each sheet into a SQLite database.
    Tables are replaced on each run.
    """
    wb = Path(workbook_path)
    db = Path(db_path)

    if not wb.exists():
        out: dict[str, Any] = {
            "ok": False,
            "error": "Workbook not found",
            "workbook_path": str(wb),
            "db_path": str(db),
        }
        hint = _mapped_drive_hint(wb)
        if hint:
            out["hint"] = hint
        return out

    db.parent.mkdir(parents=True, exist_ok=True)
    ingested_at = datetime.now(timezone.utc).isoformat()
    stat = wb.stat()

    try:
        # Engine selection: openpyxl supports xlsm.
        xls = pd.ExcelFile(wb, engine="openpyxl")
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": f"Could not open workbook: {exc}",
            "workbook_path": str(wb),
            "db_path": str(db),
        }

    available_sheets = list(xls.sheet_names)
    if only_sheets:
        requested = list(only_sheets)
        missing = [s for s in requested if s not in available_sheets]
        sheet_names = [s for s in requested if s in available_sheets]
    else:
        requested = []
        missing = []
        sheet_names = available_sheets
    if keep_columns_1based:
        order_0 = [max(0, int(c) - 1) for c in keep_columns_1based]
        keep_cols_0based = sorted(set(order_0))
    else:
        order_0 = None
        keep_cols_0based = None

    sheet_summaries: list[dict[str, Any]] = []

    with sqlite3.connect(db, timeout=60) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS __meta (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        conn.execute("DELETE FROM __meta")
        conn.executemany(
            "INSERT INTO __meta(key, value) VALUES(?, ?)",
            [
                ("workbook_path", str(wb)),
                ("workbook_mtime_utc", datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()),
                ("ingested_at_utc", ingested_at),
                ("sheet_count", str(len(available_sheets))),
                ("ingested_sheet_count", str(len(sheet_names))),
            ],
        )

        if missing:
            sheet_summaries.append(
                {
                    "ok": False,
                    "error": "Missing required sheet(s)",
                    "missing_sheets": missing,
                    "available_sheets": available_sheets,
                }
            )

        for sheet in sheet_names:
            try:
                # drop_top_rows: remove pre-header junk rows; new top row becomes headers
                df = pd.read_excel(
                    xls,
                    sheet_name=sheet,
                    engine="openpyxl",
                    skiprows=drop_top_rows if drop_top_rows > 0 else 0,
                    header=0,
                    usecols=keep_cols_0based,
                )
            except Exception as exc:  # noqa: BLE001
                sheet_summaries.append({"sheet": sheet, "ok": False, "error": str(exc)})
                continue

            if order_0 is not None:
                df = _reorder_columns_after_int_usecols(df, keep_columns_1based)
            df.columns = _dedupe_columns(list(df.columns))

            table = table_name or f"sheet_{_safe_table_name(sheet)}"
            try:
                df.to_sql(table, conn, if_exists="replace", index=False)
            except Exception as exc:  # noqa: BLE001
                sheet_summaries.append({"sheet": sheet, "ok": False, "error": f"to_sql failed: {exc}"})
                continue

            sheet_summaries.append(
                {
                    "sheet": sheet,
                    "ok": True,
                    "table": table,
                    "rows": int(df.shape[0]),
                    "cols": int(df.shape[1]),
                }
            )

        # Verification: list tables and count rows for imported sheets
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [r[0] for r in cur.fetchall()]

    ok_sheets = [s for s in sheet_summaries if s.get("ok")]
    inserted_tables = [s.get("table") for s in ok_sheets if s.get("table")]

    return {
        "ok": len(ok_sheets) > 0 and not missing,
        "workbook_path": str(wb),
        "workbook_mtime_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        "db_path": str(db),
        "sheet_count": len(available_sheets),
        "ingested_sheet_count": len(sheet_names),
        "requested_sheets": requested,
        "missing_sheets": missing,
        "sheets": sheet_summaries,
        "tables_written": inserted_tables,
    }

