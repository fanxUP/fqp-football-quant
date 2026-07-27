### Task 1: Add bcrypt dependency and env config

**Files:**
- Modify: `requirements.txt`
- Modify: `.env.local`
- Modify: `apps/backend/src/app.py`

**Interfaces:**
- Produces: `bcrypt` available via `import bcrypt`
- Produces: `FQP_AUTH_MODE` env var read by middleware
- Produces: `FQP_ADMIN_PASSWORD_HASH` env var added to `.env.local`
- Produces: `app.py` registers auth router and middleware

- [ ] **Step 1: Add bcrypt to requirements.txt**

Insert `bcrypt==4.3.0` after `apscheduler==3.11.3`:

```txt
apscheduler==3.11.3
bcrypt==4.3.0
redis==8.0.1
```

- [ ] **Step 2: Add auth env vars to `.env.local`**

Append to `/home/admin/fqp-football-quant/.env.local`:

```env
FQP_AUTH_MODE=none
FQP_ADMIN_PASSWORD_HASH=$2b$12$LJ3m4ys3Lk0TSwHnbfOMiOXPm1Qlq5y0q5z5q5z5q5z5q5z5q5z5O
FQP_SESSION_TTL=86400
```

This is a placeholder bcrypt hash — will be regenerated in production.

- [ ] **Step 3: Generate real bcrypt hash for password "123"**

```bash
python3 -c "import bcrypt; print(bcrypt.hashpw(b'123', bcrypt.gensalt(rounds=12)).decode())"
```

Copy the output. Update `.env.local`:

```env
FQP_ADMIN_PASSWORD_HASH=<output_from_command>
```

- [ ] **Step 4: Register auth router and middleware in `app.py`**

Modify `/home/admin/fqp-football-quant/apps/backend/src/app.py`:

```python
"""FQP FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from apps.backend.src.routers import (
    agents,
    analysis,
    backtests,
    betting,
    competition,
    dashboard,
    enrichment,
    health,
    official,
    ops,
    pool,
    predictions,
    simulator,
    teams,
    tickets,
    ui,
    upsets,
)
from apps.backend.src.auth import AuthMiddleware  # new
from apps.backend.src.routers import auth_router  # new


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

    # Auth router must be registered before middleware so login/logout bypass checks
    app.include_router(auth_router.router)
    app.add_middleware(AuthMiddleware)

    app.include_router(health.router)
    app.include_router(official.router)
    app.include_router(teams.router)
    app.include_router(predictions.router)
    app.include_router(tickets.router)
    app.include_router(agents.router)
    app.include_router(enrichment.router)
    app.include_router(ops.router)
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
```

- [ ] **Step 5: Commit**

```bash
git add requirements.txt .env.local apps/backend/src/app.py
git commit -m "feat(auth): add bcrypt dep, env config, register auth router/middleware"
```

---