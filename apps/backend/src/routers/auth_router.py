"""Authentication endpoints — login, logout, session check."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
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
async def login(body: LoginRequest, request: Request, response: Response) -> LoginResponse:
    """Authenticate with password. Creates a session on success."""
    if not verify_password(body.password):
        raise HTTPException(status_code=401, detail="密码错误")

    # If there's an existing session, destroy it first
    existing = request.cookies.get(COOKIE_NAME)
    if existing:
        await destroy_session(existing)

    await create_session(response)
    return LoginResponse(ok=True, user="admin")


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
