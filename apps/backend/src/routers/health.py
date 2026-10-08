"""Health check and root endpoints."""

from __future__ import annotations

import os

from fastapi import APIRouter
from redis import Redis
from starlette.responses import JSONResponse

from apps.backend.src.db import db_health, get_db
from apps.backend.src.services.business_health import get_business_health

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    return {"status": "ok", "service": "fqp-from-scratch"}


@router.get("/health/ready")
def readiness():
    """Check dependencies without exposing connection strings or error details."""
    database = db_health()
    checks = {"database": database["status"], "redis": "error"}
    try:
        with Redis.from_url(
            os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"),
            socket_connect_timeout=1,
            socket_timeout=1,
        ) as client:
            if client.ping():
                checks["redis"] = "ok"
    except Exception:
        pass
    ready = all(value == "ok" for value in checks.values())
    return JSONResponse(
        {"status": "ok" if ready else "unavailable", "checks": checks},
        status_code=200 if ready else 503,
    )


@router.get("/api/ops/business-health")
def business_health():
    """Authenticated read-only reconciliation; never changes historical money."""
    with get_db() as conn:
        return get_business_health(conn)


@router.get("/")
def root():
    return {"name": "FQP From Scratch", "boundary": "analysis_simulation_review_only"}
