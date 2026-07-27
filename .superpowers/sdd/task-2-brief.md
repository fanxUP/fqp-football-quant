### Task 2: Backend auth module — Session management + middleware

**Files:**
- Create: `apps/backend/src/auth.py`

**Interfaces:**
- Consumes: `FQP_AUTH_MODE`, `FQP_ADMIN_PASSWORD_HASH`, `FQP_SESSION_TTL` env vars, Redis at `REDIS_URL`
- Exports: `AuthMiddleware` (Starlette ASGI middleware), `create_session()`, `validate_session()`, `destroy_session()`

- [ ] **Step 1: Create `apps/backend/src/auth.py`**

```python
"""Session-based authentication for FQP.

Uses Redis for session storage and bcrypt for password verification.
Controlled by FQP_AUTH_MODE env var: "none" bypasses all checks.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import bcrypt
import redis.asyncio as aioredis
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

COOKIE_NAME = "fqp_session"
SESSION_TTL = int(os.getenv("FQP_SESSION_TTL", "86400"))


async def get_redis() -> aioredis.Redis:
    """Return an async Redis connection."""
    url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    return aioredis.from_url(url, decode_responses=True)


def verify_password(password: str) -> bool:
    """Check password against bcrypt hash in env."""
    stored_hash = os.getenv("FQP_ADMIN_PASSWORD_HASH", "")
    if not stored_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


async def create_session(response: Response) -> str:
    """Create a new session in Redis and set cookie on the response."""
    session_id = str(uuid.uuid4())
    r = await get_redis()
    await r.setex(f"session:{session_id}", SESSION_TTL, "admin")
    response.set_cookie(
        key=COOKIE_NAME,
        value=session_id,
        max_age=SESSION_TTL,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return session_id


async def validate_session(session_id: str) -> str | None:
    """Validate a session ID. Returns username if valid, None otherwise."""
    r = await get_redis()
    user: str | None = await r.get(f"session:{session_id}")
    if user is not None:
        # Refresh TTL on each access
        await r.expire(f"session:{session_id}", SESSION_TTL)
    return user


async def destroy_session(session_id: str) -> None:
    """Delete a session from Redis."""
    r = await get_redis()
    await r.delete(f"session:{session_id}")


class AuthMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware that checks session cookie on protected routes.

    When FQP_AUTH_MODE=none, all requests pass through unchecked.
    When FQP_AUTH_MODE=session, protected /api/* routes require a valid session.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        auth_mode = os.getenv("FQP_AUTH_MODE", "none")

        # Mode: none — bypass all auth checks
        if auth_mode == "none":
            return await call_next(request)

        # Public paths — always allowed
        public_prefixes = ("/api/auth/", "/health", "/uploads")
        if request.url.path.startswith(public_prefixes):
            return await call_next(request)

        # Protected paths — require valid session
        session_id = request.cookies.get(COOKIE_NAME)
        if session_id:
            user = await validate_session(session_id)
            if user is not None:
                request.state.user = user
                return await call_next(request)

        return JSONResponse(status_code=401, content={"detail": "未登录"})
```

- [ ] **Step 2: Create `apps/backend/src/routers/auth_router.py`**

```python
"""Authentication endpoints — login, logout, session check."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from apps.backend.src.auth import (
    COOKIE_NAME,
    create_session,
    destroy_session,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    password: str


class LoginResponse(BaseModel):
    ok: bool
    user: str


class MeResponse(BaseModel):
    user: str


@router.post("/login")
async def login(body: LoginRequest, request: Request) -> LoginResponse:
    """Authenticate with password. Creates a session on success."""
    if not verify_password(body.password):
        raise HTTPException(status_code=401, detail="密码错误")

    # If there's an existing session, destroy it first
    existing = request.cookies.get(COOKIE_NAME)
    if existing:
        await destroy_session(existing)

    response = LoginResponse(ok=True, user="admin")
    await create_session(response)
    return response


@router.post("/logout")
async def logout(request: Request) -> dict[str, bool]:
    """Destroy the current session."""
    session_id = request.cookies.get(COOKIE_NAME)
    if session_id:
        await destroy_session(session_id)
    response: dict[str, bool] = {"ok": True}
    return response


@router.get("/me")
async def me(request: Request) -> MeResponse:
    """Return current user if authenticated."""
    user = getattr(request.state, "user", None)
    if not user:
        # Check cookie manually — middleware may not have run for this path
        session_id = request.cookies.get(COOKIE_NAME)
        if session_id:
            from apps.backend.src.auth import validate_session
            user = await validate_session(session_id)
    if not user:
        raise HTTPException(status_code=401, detail="未登录")
    return MeResponse(user=user)
```

- [ ] **Step 3: Register auth_router in `routers/__init__.py`**

```python
"""FQP API routers package."""
```

No change needed — `__init__.py` is empty, routers are registered individually in `app.py`.

- [ ] **Step 4: Commit**

```bash
git add apps/backend/src/auth.py apps/backend/src/routers/auth_router.py
git commit -m "feat(auth): add session management and auth endpoints"
```

---