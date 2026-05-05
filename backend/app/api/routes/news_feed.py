from __future__ import annotations

import os

from fastapi import APIRouter, Header, HTTPException, Response

from app.data.news_store import list_stories
from app.services.email_inbound_news import sync_inbox_to_store

router = APIRouter()


@router.get("/news")
def get_news(response: Response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return {"stories": list_stories(10)}


@router.post("/news/sync")
def post_news_sync(
    response: Response,
    x_news_sync_secret: str | None = Header(default=None),
):
    """
    Pull UNSEEN messages from IMAP, parse, append to rolling store (max 10), mark read.
    If NEWS_SYNC_SECRET is set in the environment, the same value must be sent in header X-News-Sync-Secret.
    """
    response.headers["Cache-Control"] = "no-store"
    expected = os.getenv("NEWS_SYNC_SECRET")
    if expected and (x_news_sync_secret or "").strip() != expected.strip():
        raise HTTPException(status_code=401, detail="Missing or invalid X-News-Sync-Secret")

    result = sync_inbox_to_store()
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result)
    return result
