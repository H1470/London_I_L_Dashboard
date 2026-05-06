"""
FastAPI entrypoint: REST API + static frontend when ``../frontend`` exists.

Routers live under ``/api``. Static mount at ``/`` uses ``html=True`` so ``/`` serves
``index.html`` and relative asset paths work. For production you may serve the UI
from a CDN instead and keep only the API here.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import health, indices, newmark, news_feed, summary

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"

app = FastAPI(title="London I&L Dashboard API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(summary.router, prefix="/api", tags=["summary"])
app.include_router(indices.router, prefix="/api", tags=["indices"])
app.include_router(news_feed.router, prefix="/api", tags=["news"])
app.include_router(newmark.router, prefix="/api", tags=["newmark"])

if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
