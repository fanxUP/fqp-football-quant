"""Session-based authentication for FQP.

Uses Redis for session storage and bcrypt for password verification.
FQP_AUTH_MODE defaults to "session"; "none" is an explicit local-only bypass.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

import bcrypt
import redis.asyncio as aioredis
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from apps.backend.src.deployment_version import RELEASE_ID

COOKIE_NAME = "fqp_session"
DEFAULT_PASSWORD_FILE = Path(__file__).resolve().parents[3] / ".runtime" / "admin-password.hash"
SESSION_TTL = int(os.getenv("FQP_SESSION_TTL", "86400"))
# Keep release markers under the existing session:* Redis ACL namespace. The
# runtime account can then inspect, refresh, and delete both session keys.
SESSION_RELEASE_PREFIX = "session:release:"
_CREATE_SESSION_SCRIPT = """
redis.call("SETEX", KEYS[1], ARGV[1], ARGV[2])
redis.call("SETEX", KEYS[2], ARGV[1], ARGV[3])
return 1
"""


# Singleton Redis connection pool
_redis_pool: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    global _redis_pool
    if _redis_pool is None:
        url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
        _redis_pool = aioredis.from_url(url, decode_responses=True)
    return _redis_pool


def password_file() -> Path:
    return Path(os.getenv("FQP_ADMIN_PASSWORD_FILE") or DEFAULT_PASSWORD_FILE)


def _password_hash() -> str:
    try:
        # A small bounded read also rejects a malformed or unexpectedly large file.
        with password_file().open(encoding="ascii") as source:
            return source.read(256).strip()
    except FileNotFoundError:
        # Existing installations and a new persistent volume bootstrap from env.
        return os.getenv("FQP_ADMIN_PASSWORD_HASH", "")
    except OSError, UnicodeError:
        # Never resurrect a bootstrap password when persistent state is broken.
        return ""


def save_password_hash(new_hash: str) -> None:
    """Publish a complete private hash file; never rewrite application env files."""
    target = password_file()
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".admin-password-", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="ascii") as output:
            output.write(new_hash + "\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
        # Persist the directory entry as well as the file contents.
        directory = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)
    os.environ["FQP_ADMIN_PASSWORD_HASH"] = new_hash


def verify_password(password: str) -> bool:
    """Use the persistent hash after first change, env only for bootstrap."""
    stored_hash = _password_hash()
    if not stored_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))
    except ValueError:
        return False
    except TypeError:
        return False


async def create_session(response: Response) -> str:
    """Create a new session in Redis and set cookie on the response."""
    session_id = str(uuid.uuid4())
    r = await get_redis()
    await r.eval(
        _CREATE_SESSION_SCRIPT,
        2,
        f"session:{session_id}",
        f"{SESSION_RELEASE_PREFIX}{session_id}",
        SESSION_TTL,
        "admin",
        RELEASE_ID,
    )
    response.set_cookie(
        key=COOKIE_NAME,
        value=session_id,
        max_age=SESSION_TTL,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return session_id


async def inspect_session(session_id: str) -> tuple[str | None, bool]:
    """Return the user and whether an existing session belongs to an old release."""
    r = await get_redis()
    raw_user = await r.get(f"session:{session_id}")
    if raw_user is None:
        return None, False

    raw_release = await r.get(f"{SESSION_RELEASE_PREFIX}{session_id}")
    release_id = raw_release.decode() if isinstance(raw_release, bytes) else raw_release
    if release_id != RELEASE_ID:
        # Keep the stale marker until its original TTL expires so /me can tell
        # the user why this session was rejected. Protected routes still fail closed.
        return None, True

    user: str | None = raw_user.decode() if isinstance(raw_user, bytes) else raw_user
    if user is not None:
        # Refresh TTL on each access
        await r.expire(f"session:{session_id}", SESSION_TTL)
        await r.expire(f"{SESSION_RELEASE_PREFIX}{session_id}", SESSION_TTL)
    return user, False


async def validate_session(session_id: str) -> str | None:
    """Validate a session ID and reject sessions created by another release."""
    user, _release_changed = await inspect_session(session_id)
    return user


async def destroy_session(session_id: str) -> None:
    """Delete a session from Redis."""
    r = await get_redis()
    await r.delete(f"session:{session_id}", f"{SESSION_RELEASE_PREFIX}{session_id}")


class AuthMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware that checks session cookie on protected routes.

    When FQP_AUTH_MODE=none, all requests pass through unchecked.
    When FQP_AUTH_MODE=session, protected /api/* routes require a valid session.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        # Fail closed: a missing environment variable must not expose protected APIs.
        auth_mode = os.getenv("FQP_AUTH_MODE", "session")

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
