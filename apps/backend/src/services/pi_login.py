"""Short-lived, session-owned Pi OAuth interactions; no credentials in status APIs."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from apps.backend.src.db import get_db
from apps.backend.src.services.model_provider_store import (
    CONFIG_COLUMNS,
    ProviderConfigError,
    _config_record,
    _encrypted_credential,
    _public_config,
    pi_id,
    validate_provider_input,
)
from apps.backend.src.services.pi_bridge import pi_provider, start_bridge

TTL = 300
_lock = threading.RLock()
_sessions: dict[str, LoginSession] = {}
TERMINAL = {"connected", "failed", "cancelled", "expired"}


@dataclass
class LoginSession:
    id: str
    owner: str
    code: str
    payload: dict[str, Any]
    version: Any
    process: Any
    expires: float = field(default_factory=lambda: time.time() + TTL)
    status: str = "working"
    events: list[dict[str, Any]] = field(default_factory=list)
    prompt: dict[str, Any] | None = None
    provider: dict[str, Any] | None = None
    timer: Any = None


def session_owner(cookie: str) -> str:
    return hashlib.sha256(cookie.encode()).hexdigest()


def _snapshot(session: LoginSession) -> dict[str, Any]:
    return {
        "loginId": session.id,
        "providerCode": session.code,
        "status": session.status,
        "expiresAt": session.expires,
        "events": list(session.events),
        "prompt": session.prompt,
        "provider": session.provider,
    }


def _stop(session: LoginSession, status: str) -> None:
    session.status, session.prompt = status, None
    if session.process.poll() is None:
        session.process.terminate()
    if session.timer:
        session.timer.cancel()


def _expire(login_id: str) -> None:
    with _lock:
        session = _sessions.get(login_id)
        if session and session.status not in TERMINAL:
            _stop(session, "expired")


def _safe_url(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) > 12000:
        return None
    parsed = urlparse(value)
    return (
        value
        if parsed.scheme == "https"
        and parsed.netloc
        and not parsed.username
        and not parsed.password
        else None
    )


def _public_event(event: dict[str, Any]) -> dict[str, Any]:
    kind = event.get("type")
    if kind == "auth_url":
        return {
            "type": kind,
            "url": _safe_url(event.get("url")),
            "instructions": str(event.get("instructions", ""))[:1000],
        }
    if kind == "device_code":
        return {
            "type": kind,
            "userCode": str(event.get("userCode", ""))[:100],
            "verificationUri": _safe_url(event.get("verificationUri")),
        }
    return {
        "type": kind if kind in {"info", "progress"} else "info",
        "message": str(event.get("message", ""))[:1000],
    }


def _persist(session: LoginSession, credential: dict[str, Any]) -> dict[str, Any]:
    if credential.get("type") != "oauth" or len(json.dumps(credential)) > 60000:
        raise ProviderConfigError("登录未返回有效的账号凭据")
    provider, base_url, model = validate_provider_input(
        session.code, session.payload.get("baseUrl"), session.payload["defaultModel"]
    )
    encrypted = _encrypted_credential(credential)
    with get_db() as conn, conn.cursor() as cur:
        cur.execute("SET LOCAL lock_timeout = '5s'")
        cur.execute(
            "SELECT updated_at FROM llm_provider_configs WHERE provider_code = %s FOR UPDATE",
            (session.code,),
        )
        row = cur.fetchone()
        if (row[0] if row else None) != session.version:
            raise ProviderConfigError("配置在登录期间已变化，请重新登录")
        cur.execute(
            f"""INSERT INTO llm_provider_configs
                    (provider_code, display_name, base_url, default_model, enabled, auth_type, api_protocol, pi_credential_encrypted, updated_at)
                    VALUES (%s, %s, %s, %s, %s, 'oauth', 'auto', %s, NOW())
                    ON CONFLICT (provider_code) DO UPDATE SET auth_type = 'oauth', api_protocol = 'auto',
                    pi_credential_encrypted = EXCLUDED.pi_credential_encrypted,
                    base_url = EXCLUDED.base_url, default_model = EXCLUDED.default_model, enabled = EXCLUDED.enabled,
                    last_test_at = NULL, last_test_status = NULL, last_test_message = NULL, updated_at = NOW()
                    WHERE llm_provider_configs.updated_at = %s
                    RETURNING {CONFIG_COLUMNS}""",
            (
                session.code,
                provider.name,
                base_url,
                model,
                session.payload.get("enabled", True),
                encrypted,
                session.version,
            ),
        )
        saved = cur.fetchone()
        if not saved:
            raise ProviderConfigError("配置在登录期间已变化，请重新登录")
        result = _public_config(_config_record(saved))
        conn.commit()
        return result


def _read(session: LoginSession) -> None:
    try:
        for line in session.process.stdout:
            if len(line) > 100000:
                raise ValueError("Oversized bridge event")
            value = json.loads(line)
            with _lock:
                if session.status in TERMINAL:
                    break
                kind = value.get("kind")
                if kind == "credential":
                    session.provider = _persist(session, value["credential"])
                    session.status, session.prompt = "connected", None
                    session.timer.cancel()
                elif kind == "prompt":
                    prompt = value["prompt"]
                    if prompt["type"] not in {"text", "secret", "select", "manual_code"}:
                        raise ValueError("Unsupported prompt")
                    session.prompt = {
                        "id": value["promptId"],
                        "type": prompt["type"],
                        "message": str(prompt["message"])[:1000],
                        "options": prompt.get("options", [])[:20],
                    }
                    session.status = "waiting"
                elif kind == "event":
                    session.events = (session.events + [_public_event(value["event"])])[-20:]
                else:
                    raise ValueError("Login failed")
        with _lock:
            if session.status not in TERMINAL:
                _stop(session, "failed")
    except Exception:
        # Upstream messages, tokens, authorization codes and database errors stay private.
        with _lock:
            _stop(session, "failed")
    finally:
        if session.process.poll() is None:
            session.process.terminate()
        try:
            session.process.wait(timeout=3)
        except Exception:
            session.process.kill()
            session.process.wait()
        for stream in (session.process.stdin, session.process.stdout):
            if stream:
                stream.close()


def start_login(owner: str, code: str, payload: dict[str, Any]) -> dict[str, Any]:
    provider, _, model = validate_provider_input(
        code, payload.get("baseUrl"), payload["defaultModel"]
    )
    item = pi_provider(pi_id(provider.code))
    if not item or "oauth" not in item["authMethods"]:
        raise ProviderConfigError("该服务商不支持账号登录")
    if not any(m["id"] == model for m in item["models"]):
        raise ProviderConfigError("账号登录请选择 Pi 目录中的模型")
    # Required before beginning a login so it cannot finish without safe storage.
    _encrypted_credential({"type": "oauth"})
    with get_db() as conn, conn.cursor() as cur:
        cur.execute("SELECT updated_at FROM llm_provider_configs WHERE provider_code = %s", (code,))
        row = cur.fetchone()
        version = row[0] if row else None
    with _lock:
        for key, session in list(_sessions.items()):
            if session.expires < time.time():
                if session.status not in TERMINAL:
                    _stop(session, "expired")
                del _sessions[key]
        active = [s for s in _sessions.values() if s.status not in TERMINAL]
        if len(active) >= 4 or any(s.owner == owner or s.code == code for s in active):
            raise ProviderConfigError("已有登录正在进行，请先完成或取消")
        if len(_sessions) >= 32:
            key = next(k for k, s in _sessions.items() if s.status in TERMINAL)
            del _sessions[key]
        process = start_bridge()
        session = LoginSession(secrets.token_urlsafe(24), owner, code, payload, version, process)
        _sessions[session.id] = session
        device_id = str(
            uuid.uuid5(uuid.NAMESPACE_URL, "fqp-pi:" + os.environ["FQP_PROVIDER_ENCRYPTION_KEY"])
        )
        assert process.stdin is not None
        process.stdin.write(
            json.dumps({"operation": "login", "providerId": pi_id(code), "deviceId": device_id})
            + "\n"
        )
        process.stdin.flush()
        session.timer = threading.Timer(TTL, _expire, args=(session.id,))
        session.timer.daemon = True
        session.timer.start()
        threading.Thread(target=_read, args=(session,), daemon=True).start()
        return _snapshot(session)


def login_status(
    owner: str,
    login_id: str,
    *,
    value: str | None = None,
    prompt_id: str | None = None,
    cancel: bool = False,
) -> dict[str, Any]:
    with _lock:
        session = _sessions.get(login_id)
        if not session or session.owner != owner:
            raise ProviderConfigError("登录会话不存在或不属于当前用户")
        if session.expires < time.time() and session.status not in TERMINAL:
            _stop(session, "expired")
        if cancel and session.status not in TERMINAL:
            _stop(session, "cancelled")
        if value is not None:
            if (
                session.status != "waiting"
                or not session.prompt
                or session.prompt["id"] != prompt_id
            ):
                raise ProviderConfigError("登录步骤已变化，请刷新后重试")
            if session.prompt["type"] == "select" and not any(
                o["id"] == value for o in session.prompt["options"]
            ):
                raise ProviderConfigError("请选择有效的登录选项")
            try:
                session.process.stdin.write(
                    json.dumps({"promptId": prompt_id, "value": value}) + "\n"
                )
                session.process.stdin.flush()
            except OSError as exc:
                _stop(session, "failed")
                raise ProviderConfigError("登录进程已退出，请重新登录") from exc
            session.prompt, session.status = None, "working"
        return _snapshot(session)


def disconnect_provider(conn: Any, code: str) -> None:
    with _lock:
        for session in _sessions.values():
            if session.code == code and session.status not in TERMINAL:
                _stop(session, "cancelled")
        with conn.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout = '5s'")
            cur.execute(
                """UPDATE llm_provider_configs SET api_key_encrypted = NULL, pi_credential_encrypted = NULL,
                       enabled = false, last_test_at = NULL, last_test_status = NULL, last_test_message = NULL,
                       updated_at = NOW() WHERE provider_code = %s""",
                (code,),
            )
            cur.execute(
                "UPDATE llm_agent_bindings SET enabled = false, updated_at = NOW() WHERE provider_code = %s",
                (code,),
            )
        conn.commit()
