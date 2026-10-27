"""Authentication endpoints — login, logout, session check."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from starlette.responses import JSONResponse

from apps.backend.src.auth import (
    COOKIE_NAME,
    create_session,
    destroy_session,
    inspect_session,
    save_password_hash,
    verify_password,
)
from apps.backend.src.deployment_version import RELEASE_ID

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    password: str


class LoginResponse(BaseModel):
    ok: bool
    user: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


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
async def logout(request: Request, response: Response) -> dict[str, bool]:
    """Destroy the current session."""
    session_id = request.cookies.get(COOKIE_NAME)
    if session_id:
        await destroy_session(session_id)
    response.delete_cookie(key=COOKIE_NAME, path="/", httponly=True, samesite="lax")
    return {"ok": True}


@router.get("/release")
async def release(response: Response) -> dict[str, str]:
    """Expose a cache-free release identifier for clients to detect deployments."""
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    return {"releaseId": RELEASE_ID}


@router.get("/me", response_model=None)
async def me(request: Request) -> MeResponse | JSONResponse:
    """Return current user if authenticated."""
    session_id = request.cookies.get(COOKIE_NAME)
    user: str | None = None
    release_changed = False
    if session_id:
        user, release_changed = await inspect_session(session_id)
    if release_changed:
        return JSONResponse(status_code=409, content={"code": "deployment_changed"})
    if not user:
        raise HTTPException(status_code=401, detail="未登录")
    return MeResponse(user=user)


@router.post("/change-password")
async def change_password(body: ChangePasswordRequest, request: Request) -> dict[str, bool]:
    """Change the admin password only after its private hash has been saved."""
    if not verify_password(body.old_password):
        raise HTTPException(status_code=401, detail="原密码错误")

    if len(body.new_password) < 4:
        raise HTTPException(status_code=400, detail="密码至少4位")
    if len(body.new_password.encode("utf-8")) > 72:
        raise HTTPException(status_code=400, detail="密码的UTF-8长度不能超过72字节")

    import bcrypt

    new_hash = bcrypt.hashpw(body.new_password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode()

    try:
        save_password_hash(new_hash)
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail="密码保存失败，请检查管理员密码文件的持久化目录及写入权限"
        ) from exc

    return {"ok": True}
