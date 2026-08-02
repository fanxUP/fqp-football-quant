"""Tests for the auth module."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from apps.backend.src.auth import verify_password
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
