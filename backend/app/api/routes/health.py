"""Minimal liveness endpoint for uptime checks and load balancers."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok"}
