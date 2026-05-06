"""
Ingest Newmark tracker workbooks into local SQLite databases.

Run:
  python -m app.jobs.newmark_excel_sync
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pandas as pd

from app.services.excel_to_sqlite import read_workbook_sheet, sync_workbook_to_sqlite


def main() -> None:
    # Cleaning config (easy to adjust later)
    # - remove first 7 rows so the new top row becomes headers
    # - keep only these 1-based column positions (Excel-style counting, starting at 1)
    drop_top_rows = 7
    keep_columns_1based = [
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
    ]

    # NOTE: these can be moved to env vars later; for now keep them explicit.
    workbooks = [
        (
            r"O:\NIA\INDUSTRIAL TEAM\Investment Trackers\LIVE VERSIONS\MASTER TRACKERS\Industrial Multi Let - Tracker LIVE - POST 2022.xlsm",
            "newmark_multi_let_post_2022.db",
            ["Master Sheet - Post 2022"],
            "multi_let_post_2022",
        ),
        (
            r"O:\NIA\INDUSTRIAL TEAM\Investment Trackers\LIVE VERSIONS\MASTER TRACKERS\Industrial Multi Let - Tracker LIVE - PRE 2022.xlsm",
            "newmark_multi_let_pre_2022.db",
            ["Master Sheet - Pre 2022"],
            "multi_let_pre_2022",
        ),
        (
            r"O:\NIA\INDUSTRIAL TEAM\Investment Trackers\LIVE VERSIONS\MASTER TRACKERS\Industrial Single Let - Tracker LIVE.xlsm",
            "newmark_single_let.db",
            ["Master Sheet _ Raw Data"],
            "single_let",
        ),
    ]

    # backend/app/jobs/<this>.py -> parents[2] == backend/
    # Keep DBs under backend/data/ (matches API readers)
    data_dir = Path(__file__).resolve().parents[2] / "data"
    out = []
    for wb_path, db_name, only_sheets, _source_tag in workbooks:
        out.append(
            sync_workbook_to_sqlite(
                workbook_path=wb_path,
                db_path=data_dir / db_name,
                only_sheets=only_sheets,
                drop_top_rows=drop_top_rows,
                keep_columns_1based=keep_columns_1based,
                table_name="master",
            )
        )

    # Append into one combined DB
    frames: list[pd.DataFrame] = []
    combined_sources: list[dict[str, object]] = []
    for wb_path, _db_name, only_sheets, source_tag in workbooks:
        sheet = only_sheets[0]
        r = read_workbook_sheet(
            workbook_path=wb_path,
            sheet_name=sheet,
            drop_top_rows=drop_top_rows,
            keep_columns_1based=keep_columns_1based,
        )
        if not r.get("ok"):
            out.append({"ok": False, "error": "Combined append failed; could not read sheet", "details": r})
            print(out)
            return
        df: pd.DataFrame = r["df"]  # type: ignore[assignment]
        df = df.copy()
        df.insert(0, "source", source_tag)
        df.insert(1, "source_sheet", sheet)
        frames.append(df)
        combined_sources.append(
            {
                "source": source_tag,
                "workbook_path": r.get("workbook_path"),
                "workbook_mtime_utc": r.get("workbook_mtime_utc"),
                "rows": r.get("rows"),
                "cols": r.get("cols"),
            }
        )

    combined_df = pd.concat(frames, ignore_index=True, sort=False)
    # Final safety: ensure combined columns are unique for SQLite even if headers
    # differ only by case/whitespace across sources.
    cols = list(combined_df.columns)
    seen = {}
    out_cols = []
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

    # Duplicate the combined DB twice (for different filtering later)
    copy1 = data_dir / "newmark_combined_1.db"
    copy2 = data_dir / "newmark_combined_2.db"
    shutil.copy2(combined_db, copy1)
    shutil.copy2(combined_db, copy2)
    out.append({"ok": True, "copied_to": [str(copy1), str(copy2)]})
    print(out)


if __name__ == "__main__":
    main()

