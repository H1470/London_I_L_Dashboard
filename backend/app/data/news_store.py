"""SQLite rolling store for inbox-sourced news (max 10 rows, newest kept)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

MAX_STORIES = 10

_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "news.db"


def _conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(_DB_PATH, timeout=30)


def init_news_db() -> None:
    with _conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS stories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id TEXT UNIQUE,
                headline TEXT NOT NULL,
                url TEXT NOT NULL,
                received_at TEXT NOT NULL
            )
            """
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_stories_received ON stories(received_at)")
        c.commit()


def _trim_to_max() -> None:
    with _conn() as c:
        c.execute(
            f"""
            DELETE FROM stories
            WHERE id NOT IN (
                SELECT id FROM stories
                ORDER BY received_at DESC, id DESC
                LIMIT {MAX_STORIES}
            )
            """
        )
        c.commit()


def upsert_story(*, message_id: str, headline: str, url: str, received_at: str) -> bool:
    """
    Insert one story (skip duplicate message_id). Then drop oldest beyond MAX_STORIES.
    Returns True if a new row was inserted.
    """
    init_news_db()
    with _conn() as c:
        cur = c.execute(
            """
            INSERT OR IGNORE INTO stories (message_id, headline, url, received_at)
            VALUES (?, ?, ?, ?)
            """,
            (message_id[:998], headline[:2000], url[:4000], received_at),
        )
        inserted = cur.rowcount > 0
        c.commit()
    if inserted:
        _trim_to_max()
    return bool(inserted)


def list_stories(limit: int = MAX_STORIES) -> list[dict[str, Any]]:
    init_news_db()
    cap = min(max(limit, 1), MAX_STORIES)
    with _conn() as c:
        cur = c.execute(
            """
            SELECT headline, url, received_at
            FROM stories
            ORDER BY received_at DESC, id DESC
            LIMIT ?
            """,
            (cap,),
        )
        rows = cur.fetchall()
    return [{"headline": r[0], "url": r[1], "received_at": r[2]} for r in rows]
