"""Read-only API for sourced football news intelligence."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query

from apps.backend.src.db import get_db
from apps.backend.src.services.news_intelligence_store import (
    get_news_overview,
    list_news_articles,
    list_news_sources,
)

router = APIRouter(prefix="/api/news-intelligence", tags=["news-intelligence"])


@router.get("/overview")
def overview() -> dict[str, object]:
    with get_db() as conn:
        payload = get_news_overview(conn)
    return {"overview": payload}


@router.get("/events")
def events(
    match_id: Annotated[int | None, Query(alias="matchId", ge=1)] = None,
    source_level: Annotated[
        Literal["S", "A", "B", "C", "D"] | None,
        Query(alias="sourceLevel"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    with get_db() as conn:
        items, total = list_news_articles(
            conn,
            match_id=match_id,
            source_level=source_level,
            limit=limit,
            offset=offset,
        )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/matches/{match_id}/timeline")
def match_timeline(match_id: int) -> dict[str, object]:
    with get_db() as conn:
        items, total = list_news_articles(conn, match_id=match_id, limit=100, offset=0)
    return {"matchId": match_id, "items": items, "total": total}


@router.get("/sources")
def sources() -> dict[str, object]:
    with get_db() as conn:
        items = list_news_sources(conn)
    return {"sources": items, "total": len(items)}


@router.get("/experiments")
def experiments() -> dict[str, object]:
    return {"experiments": [], "productionFeatureEnabled": False}
