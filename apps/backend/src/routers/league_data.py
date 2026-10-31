"""Authenticated, read-only league references; browsing never acquires data."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Path, Query
from psycopg2.errors import LockNotAvailable, QueryCanceled, UndefinedTable

from apps.backend.src.db import get_db
from scripts.league_reference_storage import league_catalog, league_fixtures, league_season

Dataset = Literal["reference", "verified"]

router = APIRouter(prefix="/api/league-data", tags=["league-data"])


def _read(loader, *args, **kwargs):
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute("SET LOCAL statement_timeout='5s'")
                cur.execute("SET LOCAL lock_timeout='2s'")
            return loader(conn, *args, **kwargs)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (QueryCanceled, LockNotAvailable) as exc:
        raise HTTPException(503, "联赛资料读取超时，请稍后重试") from exc
    except UndefinedTable as exc:
        raise HTTPException(503, "联赛共享数据结构尚未初始化") from exc


@router.get("/catalog")
def catalog(dataset: Dataset = "reference"):
    return _read(league_catalog, dataset=dataset)


@router.get("/seasons/{season_id}")
def season(season_id: int = Path(gt=0, le=9007199254740991), dataset: Dataset = "reference"):
    return _read(league_season, season_id, dataset=dataset)


@router.get("/seasons/{season_id}/fixtures")
def fixtures(
    season_id: int = Path(gt=0, le=9007199254740991),
    dataset: Dataset = "reference",
    round_id: str | None = Query(None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
    status: Literal["all", "finished", "upcoming", "postponed"] = "all",
    team_id: int | None = Query(None, gt=0, le=9007199254740991),
    batch_id: int | None = Query(None, gt=0, le=9007199254740991),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, le=100000),
):
    if dataset == "verified" and any(value is not None for value in (round_id, team_id, batch_id)):
        raise HTTPException(422, "核实归属赛程不支持联赛资料批次、轮次或规范球队筛选")
    return _read(
        league_fixtures,
        season_id,
        dataset=dataset,
        round_id=round_id,
        status=status,
        team_id=team_id,
        batch_id=batch_id,
        limit=limit,
        offset=offset,
    )
