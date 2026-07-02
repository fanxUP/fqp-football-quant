"""FQP FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI

from apps.backend.src.routers import (
    agents,
    backtests,
    enrichment,
    health,
    ops,
    pool,
    predictions,
    teams,
    tickets,
)


def create_app() -> FastAPI:
    app = FastAPI(
        title="FQP From Scratch API",
        description="足彩/竞彩足球量化研究与长期运行系统。仅用于数据分析、模拟和复盘，不提供售彩、代购、出票、收款。",
        version="1.0.0",
    )

    app.include_router(health.router)
    app.include_router(teams.router)
    app.include_router(predictions.router)
    app.include_router(tickets.router)
    app.include_router(agents.router)
    app.include_router(enrichment.router)
    app.include_router(ops.router)
    app.include_router(backtests.router)
    app.include_router(pool.router)

    return app
