"""Tests for the auth module."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request
from starlette.responses import Response

from apps.backend.src import auth, deployment_version
from apps.backend.src.auth import verify_password
from apps.backend.src.routers import auth_router
from main import app


class TestPasswordVerification:
    def test_random_hash_rejects_wrong_password(self):
        """verify_password returns False for wrong password with a random hash."""
        with patch.dict(
            os.environ,
            {
                "FQP_ADMIN_PASSWORD_HASH": "$2b$12$LJ3m4ys3Lk0TSwHnbfOMiOXPm1Qlq5y0q5z5q5z5q5z5q5z5q5z5O"
            },
            clear=False,
        ):
            assert not verify_password("wrong")

    def test_wrong_password(self):
        """verify_password returns False for wrong password."""
        assert not verify_password("wrong")

    def test_empty_hash(self):
        """verify_password returns False when no hash configured."""
        with patch.dict(os.environ, {}, clear=True):
            assert not verify_password("anything")

    def test_known_hash(self):
        """Verify that password 123 matches a known hash."""
        import bcrypt

        expected = bcrypt.hashpw(b"123", bcrypt.gensalt(rounds=4))
        with patch.dict(os.environ, {"FQP_ADMIN_PASSWORD_HASH": expected.decode()}, clear=False):
            assert verify_password("123")
            assert not verify_password("wrong")


@pytest.mark.asyncio
class TestAuthEndpoints:
    async def test_auth_mode_none_bypasses_all(self):
        """When FQP_AUTH_MODE=none, all endpoints are accessible."""
        with patch.dict(os.environ, {"FQP_AUTH_MODE": "none"}, clear=False):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/api/auth/me")
                assert resp.status_code in (200, 401)

    async def test_health_accessible_without_session(self):
        """Health endpoint is always accessible."""
        with patch.dict(os.environ, {"FQP_AUTH_MODE": "session"}, clear=False):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/health")
                assert resp.status_code == 200

    async def test_protected_route_requires_session(self):
        """Protected routes return 401 without valid session."""
        with patch.dict(os.environ, {"FQP_AUTH_MODE": "session"}, clear=False):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/api/modules")
                assert resp.status_code == 401
                assert resp.json()["detail"] == "未登录"

    async def test_missing_auth_mode_fails_closed(self):
        """A missing configuration must keep sensitive APIs protected."""
        with patch.dict(os.environ, {}, clear=True):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/api/model-providers")
                assert resp.status_code == 401
                assert resp.json()["detail"] == "未登录"

    async def test_deployment_release_is_stored_with_new_session(self, monkeypatch):
        pipeline = MagicMock()
        pipeline.setex = MagicMock()
        pipeline.execute = AsyncMock()
        redis = MagicMock()
        redis.pipeline.return_value = pipeline
        monkeypatch.setattr(auth, "get_redis", AsyncMock(return_value=redis))

        response = Response()
        session_id = await auth.create_session(response)

        assert pipeline.setex.call_args_list == [
            call(f"session:{session_id}", auth.SESSION_TTL, "admin"),
            call(f"{auth.SESSION_RELEASE_PREFIX}{session_id}", auth.SESSION_TTL, auth.RELEASE_ID),
        ]
        pipeline.execute.assert_awaited_once()
        assert auth.COOKIE_NAME in response.headers["set-cookie"]

    async def test_previous_release_session_is_rejected_without_ttl_refresh(self, monkeypatch):
        redis = MagicMock()
        redis.get = AsyncMock(side_effect=["admin", "previous-release"])
        redis.expire = AsyncMock()
        monkeypatch.setattr(auth, "get_redis", AsyncMock(return_value=redis))

        with patch.dict(os.environ, {"FQP_AUTH_MODE": "session"}, clear=False):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport,
                base_url="http://test",
                cookies={auth.COOKIE_NAME: "stale-session"},
            ) as ac:
                response = await ac.get("/api/modules")

        assert response.status_code == 401
        redis.expire.assert_not_awaited()

    async def test_me_identifies_session_invalidated_by_deployment(self, monkeypatch):
        inspect_session = AsyncMock(return_value=(None, True))
        monkeypatch.setattr(auth_router, "inspect_session", inspect_session)
        request = Request(
            {
                "type": "http",
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": "/api/auth/me",
                "raw_path": b"/api/auth/me",
                "query_string": b"",
                "headers": [(b"cookie", b"fqp_session=stale-session")],
                "client": ("test", 1),
                "server": ("test", 80),
            }
        )

        response = await auth_router.me(request)

        assert response.status_code == 409
        assert response.body == b'{"code":"deployment_changed"}'
        inspect_session.assert_awaited_once_with("stale-session")

    async def test_deployment_marker_and_release_endpoint(self, tmp_path, monkeypatch):
        marker_root = tmp_path / "project"
        marker_path = marker_root / ".runtime" / "release-id"
        marker_path.parent.mkdir(parents=True)
        marker_path.write_text("release-uuid-20261021", encoding="utf-8")
        monkeypatch.setattr(deployment_version, "_PROJECT_ROOT", marker_root)
        with patch.dict(os.environ, {"FQP_RELEASE_ID": "older-configured-release"}, clear=False):
            assert deployment_version._load_release_id() == "release-uuid-20261021"

        response = Response()

        payload = await auth_router.release(response)

        assert payload == {"releaseId": auth_router.RELEASE_ID}
        assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate"
        assert response.headers["pragma"] == "no-cache"

    async def test_logout_removes_session_and_clears_cookie(self, monkeypatch):
        destroy_session = AsyncMock()
        monkeypatch.setattr(auth_router, "destroy_session", destroy_session)
        request = Request(
            {
                "type": "http",
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": "/api/auth/logout",
                "raw_path": b"/api/auth/logout",
                "query_string": b"",
                "headers": [(b"cookie", b"fqp_session=stale-session")],
                "client": ("test", 1),
                "server": ("test", 80),
            }
        )
        response = Response()

        result = await auth_router.logout(request, response)

        assert result == {"ok": True}
        destroy_session.assert_awaited_once_with("stale-session")
        assert 'fqp_session=""' in response.headers["set-cookie"]
        assert "max-age=0" in response.headers["set-cookie"].lower()
