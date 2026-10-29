"""Authenticated historical reference reads from the shared PostgreSQL database."""

from fastapi import APIRouter, HTTPException, Path, Query
from psycopg2.errors import QueryCanceled, UndefinedTable

from apps.backend.src.db import get_db
from scripts.football_history_storage import HistoryDomain, match_history_reference

router = APIRouter(prefix="/api/matches", tags=["football-history"])


@router.get("/{match_id}/history-reference")
def history_reference(
    match_id: int = Path(gt=0, le=9007199254740991),
    domain: HistoryDomain = "match_stats",
    batch_id: int | None = Query(None, gt=0, le=9007199254740991),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0, le=10000),
):
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SET LOCAL transaction_read_only=on")
                cur.execute("SET LOCAL statement_timeout='5s'")
            return match_history_reference(
                conn, match_id, domain=domain, batch_id=batch_id, limit=limit, offset=offset
            )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except UndefinedTable as exc:
        raise HTTPException(503, "历史共享数据结构尚未初始化") from exc
    except QueryCanceled as exc:
        raise HTTPException(503, "历史参考读取超时，请稍后重试") from exc
