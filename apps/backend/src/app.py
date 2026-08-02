"""FQP FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from apps.backend.src.auth import AuthMiddleware
from apps.backend.src.routers import (
    agents,
    agent_workspace,
    analysis,
    auth_router,
    backtests,
    betting,
    competition,
    dashboard,
    enrichment,
    health,
    official,
    ops,
    model_providers,
    pool,
    predictions,
    simulator,
    teams,
    tickets,
    ui,
    upsets,
)


class ApiV1AliasMiddleware:
    """Route /api/v1/* requests to the existing /api/* handlers."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            path = scope.get("path", "")
            if path.startswith("/api/v1/"):
                scope = dict(scope)
                scope["path"] = "/api/" + path.removeprefix("/api/v1/")
        await self.app(scope, receive, send)


def create_app() -> FastAPI:
    app = FastAPI(
        title="FQP From Scratch API",
        description="足彩/竞彩足球量化研究与长期运行系统。仅用于数据分析、模拟和复盘，不提供售彩、代购、出票、收款。",
        version="1.2.0",
    )
    app.add_middleware(ApiV1AliasMiddleware)
    tickets.UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=str(tickets.UPLOAD_ROOT)), name="uploads")

    app.include_router(auth_router.router)
    app.add_middleware(AuthMiddleware)

    app.include_router(health.router)
    app.include_router(official.router)
    app.include_router(teams.router)
    app.include_router(predictions.router)
    app.include_router(tickets.router)
    app.include_router(agents.router)
    app.include_router(agent_workspace.router)
    app.include_router(enrichment.router)
    app.include_router(ops.router)
    app.include_router(model_providers.router)
    app.include_router(backtests.router)
    app.include_router(pool.router)
    app.include_router(analysis.router)
    app.include_router(simulator.router)
    app.include_router(betting.router)
    app.include_router(competition.router)
    app.include_router(dashboard.router)
    app.include_router(ui.router)
    app.include_router(upsets.router)

    return app
