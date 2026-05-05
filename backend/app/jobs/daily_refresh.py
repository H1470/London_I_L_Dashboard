"""
Daily refresh entrypoint (stub).

Run manually:  python -m app.jobs.daily_refresh
Production:   schedule this module via OS cron, Windows Task Scheduler,
              or a process manager that runs `uvicorn` plus a worker.
"""

from datetime import datetime, timezone


def main() -> None:
    now = datetime.now(timezone.utc).isoformat()
    print(f"[{now}] daily_refresh stub: would refresh Excel, yfinance, APIs")


if __name__ == "__main__":
    main()
