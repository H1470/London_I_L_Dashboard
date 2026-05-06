"""
Ingest Newmark tracker workbooks into local SQLite databases, then merge into one combined DB.

Run:
  python -m app.jobs.newmark_excel_sync

Edit NEWMARK_SOURCES below: each workbook can use different Excel column numbers (1-based),
as long as every source selects the SAME COUNT of columns in the SAME logical order so the
concatenated `master_all` table lines up. `drop_top_rows` can also differ per file if needed.

Same field, different Excel positions: e.g. two files read column 68 and one reads 67 — use the
same list *length* and order of meanings, but put 67 vs 68 in the slot where that field lives.
After `skiprows`, pandas uses the header row; `pd.concat` aligns merged columns by header name,
so keep the same header text in that column on each sheet (or rename in Excel) so the merge
matches. Each workbook still gets its own SQLite file first, then rows are appended into
`newmark_combined.db` as today.
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path
from typing import Any, TypedDict

import pandas as pd

from app.services.excel_to_sqlite import read_workbook_sheet, sync_workbook_to_sqlite


class NewmarkSourceConfig(TypedDict):
    """One workbook → one per-workbook SQLite file + one slice for the combined merge."""

    source_tag: str
    workbook_path: str
    sqlite_db_name: str
    sheet_names: list[str]
    columns_1based: list[int]
    drop_top_rows: int


# ---------------------------------------------------------------------------
# EDIT HERE — one dict per workbook / sheet group
# ---------------------------------------------------------------------------
NEWMARK_SOURCES: list[NewmarkSourceConfig] = [
    {
        "source_tag": "multi_let_post_2022",
        "workbook_path": r"O:\NIA\INDUSTRIAL TEAM\Investment Trackers\LIVE VERSIONS\MASTER TRACKERS\Industrial Multi Let - Tracker LIVE - POST 2022.xlsm",
        "sqlite_db_name": "newmark_multi_let_post_2022.db",
        "sheet_names": ["Master Sheet - Post 2022"],
        "drop_top_rows": 7,
        "columns_1based": [
            3,
            4,
            5,
            6,
            7,
            8,
            10,
            11,
            12,
            13,
            14,
            16,
            17,
            18,
            19,
            20,
            21,
            22,
            23,
            24,
            25,
            26,
            27,
            28,
            29,
            31,
            32,
            33,
            34,
            35,
            36,
            37,
            68,
        ],
    },
    {
        "source_tag": "multi_let_pre_2022",
        "workbook_path": r"O:\NIA\INDUSTRIAL TEAM\Investment Trackers\LIVE VERSIONS\MASTER TRACKERS\Industrial Multi Let - Tracker LIVE - PRE 2022.xlsm",
        "sqlite_db_name": "newmark_multi_let_pre_2022.db",
        "sheet_names": ["Master Sheet - Pre 2022"],
        "drop_top_rows": 7,
        # If PRE uses different physical columns, change this list only — keep same LENGTH and meaning order as POST.
        "columns_1based": [
            3,
            4,
            5,
            6,
            7,
            8,
            10,
            11,
            12,
            13,
            14,
            16,
            17,
            18,
            19,
            20,
            21,
            22,
            23,
            24,
            25,
            26,
            27,
            28,
            29,
            31,
            32,
            33,
            34,
            35,
            36,
            37,
            67,
        ],
    },
    {
        "source_tag": "single_let",
        "workbook_path": r"O:\NIA\INDUSTRIAL TEAM\Investment Trackers\LIVE VERSIONS\MASTER TRACKERS\Industrial Single Let - Tracker LIVE.xlsm",
        "sqlite_db_name": "newmark_single_let.db",
        "sheet_names": ["Master Sheet _ Raw Data"],
        "drop_top_rows": 7,
        # Single-let tracker: adjust integers here if its sheet layout differs; keep same list length as the others.
        "columns_1based": [
            3,
            4,
            5,
            6,
            7,
            8,
            10,
            11,
            12,
            13,
            14,
            16,
            17,
            18,
            19,
            20,
            21,
            22,
            23,
            24,
            25,
            26,
            27,
            28,
            29,
            31,
            32,
            33,
            34,
            35,
            36,
            37,
            68,
        ],
    },
]


def _validate_column_selections(sources: list[NewmarkSourceConfig]) -> None:
    lengths = [len(s["columns_1based"]) for s in sources]
    if len(set(lengths)) != 1:
        details = {s["source_tag"]: len(s["columns_1based"]) for s in sources}
        raise ValueError(
            "Each NEWMARK_SOURCES entry must select the same number of Excel columns so merged "
            f"rows align. Column counts by source_tag: {details}"
        )


def main() -> None:
    _validate_column_selections(NEWMARK_SOURCES)

    # backend/app/jobs/<this>.py -> parents[2] == backend/
    data_dir = Path(__file__).resolve().parents[2] / "data"
    out: list[Any] = []

    for cfg in NEWMARK_SOURCES:
        out.append(
            sync_workbook_to_sqlite(
                workbook_path=cfg["workbook_path"],
                db_path=data_dir / cfg["sqlite_db_name"],
                only_sheets=cfg["sheet_names"],
                drop_top_rows=cfg["drop_top_rows"],
                keep_columns_1based=cfg["columns_1based"],
                table_name="master",
            )
        )

    frames: list[pd.DataFrame] = []
    combined_sources: list[dict[str, object]] = []
    for cfg in NEWMARK_SOURCES:
        sheet = cfg["sheet_names"][0]
        r = read_workbook_sheet(
            workbook_path=cfg["workbook_path"],
            sheet_name=sheet,
            drop_top_rows=cfg["drop_top_rows"],
            keep_columns_1based=cfg["columns_1based"],
        )
        if not r.get("ok"):
            out.append({"ok": False, "error": "Combined append failed; could not read sheet", "details": r})
            print(out)
            return
        df: pd.DataFrame = r["df"]  # type: ignore[assignment]
        df = df.copy()
        df.insert(0, "source", cfg["source_tag"])
        df.insert(1, "source_sheet", sheet)
        frames.append(df)
        combined_sources.append(
            {
                "source": cfg["source_tag"],
                "workbook_path": r.get("workbook_path"),
                "workbook_mtime_utc": r.get("workbook_mtime_utc"),
                "rows": r.get("rows"),
                "cols": r.get("cols"),
                "excel_columns_1based_count": len(cfg["columns_1based"]),
            }
        )

    combined_df = pd.concat(frames, ignore_index=True, sort=False)
    cols = list(combined_df.columns)
    seen: dict[str, int] = {}
    out_cols: list[str] = []
    for c in cols:
        base = " ".join(str(c).replace("\u00A0", " ").split()).strip() or "col"
        key = base.casefold()
        n = seen.get(key, 0) + 1
        seen[key] = n
        out_cols.append(base if n == 1 else f"{base}__{n}")
    combined_df.columns = out_cols

    combined_db = data_dir / "newmark_combined.db"
    combined_table = "master_all"
    combined_db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(combined_db, timeout=60) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        combined_df.to_sql(combined_table, conn, if_exists="replace", index=False)
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
                ("combined_table", combined_table),
                ("row_count", str(int(combined_df.shape[0]))),
                ("col_count", str(int(combined_df.shape[1]))),
            ],
        )

    out.append(
        {
            "ok": True,
            "db_path": str(combined_db),
            "table": combined_table,
            "rows": int(combined_df.shape[0]),
            "cols": int(combined_df.shape[1]),
            "sources": combined_sources,
        }
    )

    copy1 = data_dir / "newmark_combined_1.db"
    copy2 = data_dir / "newmark_combined_2.db"
    shutil.copy2(combined_db, copy1)
    shutil.copy2(combined_db, copy2)
    out.append({"ok": True, "copied_to": [str(copy1), str(copy2)]})
    print(out)


if __name__ == "__main__":
    main()
