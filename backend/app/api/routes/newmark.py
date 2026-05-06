"""Newmark HTTP API: GeoJSON map features, PRAGMA-like schema, and filtered HTML preview."""

from __future__ import annotations

from fastapi import APIRouter, Query, Response

from app.data.newmark_store import points_geojson, preview_rows, table_schema

router = APIRouter()


@router.get("/newmark/geojson")
def get_newmark_geojson(
    response: Response,
    limit: int = Query(default=5000, ge=1, le=20000),
):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return points_geojson(limit=limit)


@router.get("/newmark/schema")
def get_newmark_schema(response: Response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return table_schema()


@router.get("/newmark/preview")
def get_newmark_preview(
    response: Response,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    skip_region_filter: bool = Query(
        default=False,
        description="If true, return raw table rows (no map filters: region or GE involvement). Use for inspecting column data.",
    ),
):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return preview_rows(limit=limit, offset=offset, skip_region_filter=skip_region_filter)

