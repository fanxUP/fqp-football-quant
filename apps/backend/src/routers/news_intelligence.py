"""Read-only API for sourced football news intelligence."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from apps.backend.src.db import get_db
from apps.backend.src.services.news_intelligence_store import (
    get_news_overview,
    get_news_shadow_experiment,
    list_news_articles,
    list_news_events,
    list_news_feature_snapshots,
    list_news_sources,
    review_news_event,
    set_news_source_enabled,
)

router = APIRouter(prefix="/api/news-intelligence", tags=["news-intelligence"])


class SourceStatusRequest(BaseModel):
    enabled: bool


class EventVerificationRequest(BaseModel):
    status: Literal["pending", "verified", "rejected"]
    review_note: str | None = Field(default=None, alias="reviewNote", max_length=2000)

    @field_validator("review_note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        return value.strip() if value and value.strip() else None


@router.get("/overview")
def overview() -> dict[str, object]:
    with get_db() as conn:
        payload = get_news_overview(conn)
    return {"overview": payload}


@router.get("/articles")
def articles(
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


@router.get("/events")
def events(
    match_id: Annotated[int | None, Query(alias="matchId", ge=1)] = None,
    verification_status: Annotated[
        Literal["pending", "verified", "rejected", "conflicting"] | None,
        Query(alias="verificationStatus"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    with get_db() as conn:
        items, total = list_news_events(
            conn,
            match_id=match_id,
            verification_status=verification_status,
            limit=limit,
            offset=offset,
        )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/matches/{match_id}/timeline")
def match_timeline(match_id: int) -> dict[str, object]:
    with get_db() as conn:
        items, total = list_news_events(conn, match_id=match_id, limit=100, offset=0)
    return {"matchId": match_id, "items": items, "total": total}


@router.get("/features")
def features(
    match_id: Annotated[int | None, Query(alias="matchId", ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    with get_db() as conn:
        items, total = list_news_feature_snapshots(
            conn,
            match_id=match_id,
            limit=limit,
            offset=offset,
        )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/sources")
def sources() -> dict[str, object]:
    with get_db() as conn:
        items = list_news_sources(conn)
    return {"sources": items, "total": len(items)}


@router.patch("/sources/{source_id}")
def update_source(source_id: int, body: SourceStatusRequest) -> dict[str, object]:
    try:
        with get_db() as conn:
            source = set_news_source_enabled(conn, source_id=source_id, enabled=body.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"source": source}


@router.patch("/events/{event_id}/verification")
def verify_event(event_id: int, body: EventVerificationRequest) -> dict[str, object]:
    try:
        with get_db() as conn:
            event = review_news_event(
                conn,
                event_id=event_id,
                status=body.status,
                review_note=body.review_note,
            )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"event": event}


@router.get("/experiments")
def experiments() -> dict[str, object]:
    with get_db() as conn:
        experiment = get_news_shadow_experiment(conn)
    return {"experiment": experiment}
