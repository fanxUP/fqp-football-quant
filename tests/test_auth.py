"""Tests for the auth module."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlparse

import bcrypt
import pytest
from httpx import ASGITransport, AsyncClient
from redis import Redis
from redis.asyncio import Redis as AsyncRedis
from redis.exceptions import NoPermissionError
from starlette.requests import Request
from starlette.responses import Response

from apps.backend.src import auth, deployment_version
from apps.backend.src.auth import verify_password
from apps.backend.src.routers import auth_router
from main import app


@pytest.fixture(autouse=True)
def isolated_password_file(tmp_path, monkeypatch):
    # Authentication regressions must never read or replace a real login secret.
    target = tmp_path / "runtime" / "admin-password.hash"
    monkeypatch.setattr(auth, "DEFAULT_PASSWORD_FILE", target, raising=False)
    monkeypatch.setenv("FQP_ADMIN_PASSWORD_FILE", str(target))
    return target


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
        redis = MagicMock()
        redis.eval = AsyncMock(return_value=1)
        monkeypatch.setattr(auth, "get_redis", AsyncMock(return_value=redis))

        response = Response()
        session_id = await auth.create_session(response)

        redis.eval.assert_awaited_once_with(
            auth._CREATE_SESSION_SCRIPT,
            2,
            f"session:{session_id}",
            f"{auth.SESSION_RELEASE_PREFIX}{session_id}",
            auth.SESSION_TTL,
            "admin",
            auth.RELEASE_ID,
        )
        assert auth.COOKIE_NAME in response.headers["set-cookie"]

    @pytest.mark.parametrize("prefix", ["/api", "/api/v1"])
    async def test_password_login_with_stale_cookie_uses_acl_scoped_session_keys(
        self, prefix, monkeypatch
    ):
        redis_url = os.getenv("FQP_QUOTA_TEST_REDIS_URL", "")
        if not redis_url:
            pytest.skip("requires the isolated FQP_QUOTA_TEST_REDIS_URL Redis service")
        parsed_url = urlparse(redis_url)
        if parsed_url.hostname not in {"127.0.0.1", "localhost", "::1"}:
            pytest.fail("auth ACL regression must use a loopback Redis service")

        username = f"fqp_auth_test_{uuid.uuid4().hex}"
        password = uuid.uuid4().hex
        stale_session_id = uuid.uuid4().hex
        stale_key = f"session:{stale_session_id}"
        legacy_marker_key = f"session-release:{stale_session_id}"
        admin = Redis.from_url(redis_url, decode_responses=True)
        runtime = AsyncRedis.from_url(
            redis_url,
            username=username,
            password=password,
            decode_responses=True,
        )

        try:
            admin.execute_command(
                "ACL",
                "SETUSER",
                username,
                "reset",
                "on",
                f">{password}",
                "-@all",
                "+ping",
                "+select",
                "+hello",
                "+time",
                "(+get +set +setex +expire +del +eval ~session:*)",
            )
            admin.set(stale_key, "admin", ex=3600)
            admin.set(legacy_marker_key, "previous-release", ex=3600)

            with pytest.raises(NoPermissionError):
                await runtime.delete(stale_key, legacy_marker_key)

            monkeypatch.setattr(auth, "_redis_pool", runtime)
            password_hash = bcrypt.hashpw(b"test-password", bcrypt.gensalt(rounds=4)).decode()
            monkeypatch.setenv("FQP_AUTH_MODE", "session")
            monkeypatch.setenv("FQP_ADMIN_PASSWORD_HASH", password_hash)

            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
                cookies={auth.COOKIE_NAME: stale_session_id},
            ) as client:
                response = await client.post(
                    prefix + "/auth/login", json={"password": "test-password"}
                )

            assert response.status_code == 200
            assert response.json() == {"ok": True, "user": "admin"}
            assert admin.get(stale_key) is None
            assert admin.get(legacy_marker_key) == "previous-release"

            new_session_id = response.cookies[auth.COOKIE_NAME]
            assert admin.get(f"session:{new_session_id}") == "admin"
            assert admin.get(f"session:release:{new_session_id}") == auth.RELEASE_ID
        finally:
            admin.delete(stale_key, legacy_marker_key)
            admin.execute_command("ACL", "DELUSER", username)
            await runtime.aclose()
            admin.close()

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


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", ["/api", "/api/v1"])
async def test_auth_aliases_keep_public_routes_and_protect_business(prefix, monkeypatch):
    monkeypatch.setenv("FQP_AUTH_MODE", "session")
    monkeypatch.setenv("FQP_ADMIN_PASSWORD_HASH", "")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        release = await client.get(f"{prefix}/auth/release")
        assert release.status_code == 200
        assert release.headers["cache-control"].startswith("no-store")
        login = await client.post(f"{prefix}/auth/login", json={"password": "wrong"})
        assert login.status_code == 401 and login.json()["detail"] == "密码错误"
        assert (await client.post(f"{prefix}/auth/logout")).status_code == 200
        assert (await client.get(f"{prefix}/auth/me")).status_code == 401
        for path in ["/modules", "/model-providers", "/predictions"]:
            assert (await client.get(prefix + path)).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", ["/api", "/api/v1"])
async def test_auth_alias_rejects_previous_deployment_session(prefix, monkeypatch):
    monkeypatch.setenv("FQP_AUTH_MODE", "session")
    monkeypatch.setattr(auth_router, "inspect_session", AsyncMock(return_value=(None, True)))
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={auth.COOKIE_NAME: "stale"},
    ) as client:
        response = await client.get(prefix + "/auth/me")
    assert response.status_code == 409
    assert response.json() == {"code": "deployment_changed"}


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", ["/api", "/api/v1"])
async def test_password_change_persists_after_fresh_process(
    prefix, isolated_password_file, tmp_path, monkeypatch
):
    old_hash = bcrypt.hashpw(b"old-password", bcrypt.gensalt(rounds=4)).decode()
    monkeypatch.setenv("FQP_AUTH_MODE", "session")
    monkeypatch.setenv("FQP_ADMIN_PASSWORD_HASH", old_hash)
    old_env = tmp_path / "legacy.env"
    old_env.write_text("UNCHANGED='private-configuration'\n")
    monkeypatch.setenv("ENV_FILE", str(old_env))
    create_session = AsyncMock()
    monkeypatch.setattr(auth_router, "create_session", create_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            prefix + "/auth/change-password",
            json={
                "old_password": "old-password",
                "new_password": "new-password",
            },
        )
        assert (
            await client.post(prefix + "/auth/login", json={"password": "old-password"})
        ).status_code == 401
        assert (
            await client.post(prefix + "/auth/login", json={"password": "new-password"})
        ).status_code == 200
    create_session.assert_awaited_once()
    assert response.status_code == 200
    assert not verify_password("old-password") and verify_password("new-password")
    assert old_env.read_text() == "UNCHANGED='private-configuration'\n"
    assert isolated_password_file.stat().st_mode & 0o777 == 0o600
    stored = isolated_password_file.read_text().strip()
    assert bcrypt.checkpw(b"new-password", stored.encode())
    assert "new-password" not in stored
    # A truly fresh interpreter receives the original image/env hash. The
    # persistent file must remain authoritative without reloading .env.local.
    env = {k: os.environ[k] for k in ["PATH", "LANG"] if k in os.environ}
    env.update(
        FQP_ADMIN_PASSWORD_HASH=old_hash, FQP_ADMIN_PASSWORD_FILE=str(isolated_password_file)
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from apps.backend.src.auth import verify_password; "
            "assert verify_password('new-password'); assert not verify_password('old-password')",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
async def test_password_replace_failure_keeps_old_secret(isolated_password_file, monkeypatch):
    old_hash = bcrypt.hashpw(b"old-password", bcrypt.gensalt(rounds=4)).decode()
    isolated_password_file.parent.mkdir()
    isolated_password_file.write_text(old_hash + "\n")
    monkeypatch.setenv("FQP_AUTH_MODE", "session")
    monkeypatch.setenv("FQP_ADMIN_PASSWORD_HASH", old_hash)

    def reject_replace(*_args):
        raise PermissionError("private-path-with-secret")

    monkeypatch.setattr(os, "replace", reject_replace)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/auth/change-password",
            json={
                "old_password": "old-password",
                "new_password": "new-password",
            },
        )
    assert response.status_code == 500
    assert "private-path-with-secret" not in response.text
    assert isolated_password_file.read_text() == old_hash + "\n"
    assert os.environ["FQP_ADMIN_PASSWORD_HASH"] == old_hash
    assert verify_password("old-password") and not verify_password("new-password")
    assert list(isolated_password_file.parent.iterdir()) == [isolated_password_file]


@pytest.mark.parametrize("kind", ["invalid", "unreadable"])
def test_existing_bad_password_file_never_falls_back_to_bootstrap(
    kind, isolated_password_file, monkeypatch
):
    monkeypatch.setenv(
        "FQP_ADMIN_PASSWORD_HASH", bcrypt.hashpw(b"bootstrap", bcrypt.gensalt(rounds=4)).decode()
    )
    isolated_password_file.parent.mkdir()
    if kind == "invalid":
        isolated_password_file.write_text("not-a-bcrypt-hash\n")
    else:
        isolated_password_file.mkdir()
    assert not verify_password("bootstrap")


@pytest.mark.asyncio
async def test_password_byte_limit_is_a_client_error(isolated_password_file, monkeypatch):
    monkeypatch.setenv(
        "FQP_ADMIN_PASSWORD_HASH", bcrypt.hashpw(b"old-password", bcrypt.gensalt(rounds=4)).decode()
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/auth/change-password",
            json={
                "old_password": "old-password",
                "new_password": "足" * 25,
            },
        )
    assert response.status_code == 400
    assert not isolated_password_file.exists()
