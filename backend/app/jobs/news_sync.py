"""
Run inbox → news store sync once (for Task Scheduler / cron).

  python -m app.jobs.news_sync

Requires NEWS_IMAP_* in environment (and optional NEWS_SYNC_SECRET not used here).
"""

from app.services.email_inbound_news import sync_inbox_to_store


def main() -> None:
    out = sync_inbox_to_store()
    print(out)


if __name__ == "__main__":
    main()
