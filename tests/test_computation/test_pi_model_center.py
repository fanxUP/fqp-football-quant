from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from time import sleep
from unittest.mock import MagicMock
from urllib.parse import urlparse

import psycopg2
import pytest

from apps.backend.src.services import model_provider_store as store
from apps.backend.src.services import pi_login
from apps.backend.src.services.pi_bridge import PiBridgeError, call_bridge, pi_catalog


@pytest.fixture
def pi_db(monkeypatch):
    url = os.getenv("FQP_PI_TEST_DB", "")
    if not url:
        pytest.skip("Requires explicit isolated FQP_PI_TEST_DB")
    assert urlparse(url).path == "/fqp_pi_test", "Only disposable Pi test database is permitted"
    monkeypatch.setenv(
        "FQP_PROVIDER_ENCRYPTION_KEY", "unit-test-only-private-encryption-key-32-chars"
    )
    conn = psycopg2.connect(url)
    with conn.cursor() as cur:
        cur.execute("TRUNCATE llm_agent_bindings, llm_provider_configs")
    conn.commit()
    try:
        yield conn
    finally:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("TRUNCATE llm_agent_bindings, llm_provider_configs")
        conn.commit()
        conn.close()


def test_bridge_catalog_is_real_and_public() -> None:
    items = pi_catalog()
    assert any(p["id"] == "github-copilot" and "oauth" in p["authMethods"] for p in items)
    assert len(store.provider_models("openrouter", limit=10)["models"]) == 10
    assert all(
        "gpt" in (m["id"] + m["name"]).lower()
        for m in store.provider_models("openai", "gpt")["models"]
    )


def test_bridge_failure_does_not_echo_secret() -> None:
    with pytest.raises(PiBridgeError) as error:
        call_bridge({"operation": "invalid", "secret": "must-not-echo"})
    assert "must-not-echo" not in str(error.value)


def test_login_owner_and_prompt_input_are_enforced(monkeypatch) -> None:
    process = MagicMock()
    process.poll.return_value = None
    session = pi_login.LoginSession("id", "owner", "openai", {}, None, process)
    session.status = "waiting"
    session.prompt = {"id": "1", "type": "select", "options": [{"id": "ok", "label": "OK"}]}
    monkeypatch.setattr(pi_login, "_sessions", {"id": session})
    with pytest.raises(store.ProviderConfigError, match="当前用户"):
        pi_login.login_status("other-owner", "id")
    with pytest.raises(store.ProviderConfigError, match="有效"):
        pi_login.login_status("owner", "id", prompt_id="1", value="invalid")
    result = pi_login.login_status("owner", "id", prompt_id="1", value="ok")
    assert result["prompt"] is None and result["status"] == "working"
    with pytest.raises(store.ProviderConfigError, match="步骤"):
        pi_login.login_status("owner", "id", prompt_id="1", value="ok")
    assert pi_login.login_status("owner", "id", cancel=True)["status"] == "cancelled"
    process.terminate.assert_called_once()


def test_login_expiry_and_url_validation(monkeypatch) -> None:
    session = pi_login.LoginSession("id", "owner", "openai", {}, None, MagicMock())
    session.process.poll.return_value = None
    session.expires = 0
    monkeypatch.setattr(pi_login, "_sessions", {"id": session})
    assert pi_login.login_status("owner", "id")["status"] == "expired"
    assert pi_login._public_event({"type": "auth_url", "url": "javascript:alert(1)"})["url"] is None
    assert (
        pi_login._public_event({"type": "auth_url", "url": "https://user:password@example.test"})[
            "url"
        ]
        is None
    )


def test_additive_migration_preserves_existing_configs_and_keys(pi_db) -> None:
    key = store._cipher().encrypt(b"old-key").decode()
    with pi_db.cursor() as cur:
        cur.execute(
            "INSERT INTO llm_provider_configs (provider_code,display_name,base_url,default_model,api_key_encrypted) VALUES ('openai','OpenAI','https://api.openai.com/v1','gpt-5-mini',%s)",
            (key,),
        )
        cur.execute(Path("sql/106_pi_model_credentials.sql").read_text())
        cur.execute(
            "SELECT api_key_encrypted, auth_type FROM llm_provider_configs WHERE provider_code='openai'"
        )
        assert cur.fetchone() == (key, "api_key")
    pi_db.commit()
    saved = store.save_provider_config(
        pi_db, {"providerCode": "openai", "defaultModel": "gpt-5-mini", "enabled": True}
    )
    assert saved["hasCredential"] and saved["apiKeyMask"] == "••••••••••••"
    assert "old-key" not in json.dumps(saved)
    with pi_db.cursor() as cur:
        cur.execute(
            "SELECT api_key_encrypted FROM llm_provider_configs WHERE provider_code='openai'"
        )
        assert cur.fetchone()[0] == key


def test_api_key_env_is_encrypted_and_changes_require_verification(pi_db) -> None:
    saved = store.save_provider_config(
        pi_db,
        {
            "providerCode": "openai",
            "defaultModel": "gpt-5-mini",
            "apiKey": "new-key",
            "providerEnv": {"PROJECT_ID": "private-project"},
        },
    )
    assert saved["apiProtocol"] == "auto"
    with pi_db.cursor() as cur:
        cur.execute(
            f"SELECT {store.CONFIG_COLUMNS} FROM llm_provider_configs WHERE provider_code='openai'"
        )
        record = store._config_record(cur.fetchone())
        assert "private-project" not in record["pi_credential_encrypted"]
        assert store._credential(record)["env"] == {"PROJECT_ID": "private-project"}
        cur.execute("UPDATE llm_provider_configs SET last_test_status='passed'")
    pi_db.commit()
    result = store.save_provider_config(
        pi_db,
        {
            "providerCode": "openai",
            "defaultModel": "gpt-5-mini",
            "baseUrl": "https://proxy.example.test/v1",
        },
    )
    assert result["lastTestStatus"] is None
    with pytest.raises(store.ProviderConfigError, match="掩码"):
        store.save_provider_config(
            pi_db,
            {"providerCode": "openai", "defaultModel": "gpt-5-mini", "apiKey": "••••••••••••"},
        )


def _save_oauth(conn):
    credential = {"type": "oauth", "access": "old-access", "refresh": "old-refresh", "expires": 0}
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO llm_provider_configs (provider_code,display_name,base_url,default_model,enabled,auth_type,api_protocol,pi_credential_encrypted,last_test_status) VALUES ('openai','OpenAI','https://api.openai.com/v1','gpt-5-mini',true,'oauth','auto',%s,'passed')",
            (store._encrypted_credential(credential),),
        )
    conn.commit()


def test_failed_completion_preserves_rotated_oauth_credentials(pi_db, monkeypatch) -> None:
    _save_oauth(pi_db)
    rotated = {
        "type": "oauth",
        "access": "rotated-access",
        "refresh": "rotated-refresh",
        "expires": 9999999999999,
    }
    monkeypatch.setattr(
        store,
        "call_bridge",
        lambda *args, **kwargs: {"ok": False, "status": 429, "credential": rotated},
    )
    with pytest.raises(PiBridgeError) as error:
        store.invoke_provider(pi_db, "openai", "prompt", "system")
    assert error.value.code == "MODEL_RATE_LIMITED"
    with pi_db.cursor() as cur:
        cur.execute(
            f"SELECT {store.CONFIG_COLUMNS} FROM llm_provider_configs WHERE provider_code='openai'"
        )
        assert store._credential(store._config_record(cur.fetchone())) == rotated
    assert "rotated-refresh" not in json.dumps(store.list_provider_configs(pi_db))


def test_concurrent_requests_serialize_provider_token_rotation(pi_db, monkeypatch) -> None:
    _save_oauth(pi_db)
    lock = Lock()
    active = 0
    peak = 0
    observed = []

    def bridge(payload, **kwargs):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            observed.append(payload["credential"]["refresh"])
        sleep(0.05)
        with lock:
            active -= 1
        credential = {**payload["credential"], "refresh": "new-refresh"}
        return {"ok": True, "content": "OK", "credential": credential}

    monkeypatch.setattr(store, "call_bridge", bridge)

    def invoke(_):
        with psycopg2.connect(os.environ["FQP_PI_TEST_DB"]) as conn:
            return store.invoke_provider(conn, "openai", "prompt", "system")["content"]

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(invoke, range(2))) == ["OK", "OK"]
    assert peak == 1 and observed == ["old-refresh", "new-refresh"]


def test_login_commit_rejects_changed_config_and_disconnect_clears_bindings(
    pi_db, monkeypatch
) -> None:
    _save_oauth(pi_db)
    monkeypatch.setattr(pi_login, "get_db", lambda: psycopg2.connect(os.environ["FQP_PI_TEST_DB"]))
    session = pi_login.LoginSession(
        "id",
        "owner",
        "openai",
        {"defaultModel": "gpt-5-mini"},
        datetime(2000, 1, 1, tzinfo=UTC),
        MagicMock(),
    )
    with pytest.raises(store.ProviderConfigError, match="变化"):
        pi_login._persist(session, {"type": "oauth", "access": "new"})
    with pi_db.cursor() as cur:
        cur.execute(
            "INSERT INTO llm_agent_bindings (agent_code,provider_code,enabled) VALUES ('review_agent','openai',true)"
        )
    pi_db.commit()
    pi_login.disconnect_provider(pi_db, "openai")
    assert not store.list_provider_configs(pi_db)[0]["hasCredential"]
    assert not next(
        b for b in store.list_agent_model_bindings(pi_db) if b["agentCode"] == "review_agent"
    )["enabled"]


def test_login_without_supported_provider_never_starts_upstream(monkeypatch) -> None:
    start = MagicMock()
    monkeypatch.setattr(pi_login, "start_bridge", start)
    with pytest.raises(store.ProviderConfigError, match="不支持"):
        pi_login.start_login("owner", "deepseek", {"defaultModel": "deepseek-v4-flash"})
    start.assert_not_called()


def test_credential_connection_reuses_private_libpq_password(monkeypatch) -> None:
    caller = MagicMock()
    caller.dsn = "host=example.test password=xxx"
    caller.info.dsn_parameters = {"host": "example.test", "dbname": "isolated", "sslmode": "require"}
    caller.info.password = "unit-test-only-database-password"
    connection = MagicMock()
    connect = MagicMock(return_value=connection)
    monkeypatch.setattr(store.psycopg2, "connect", connect)
    with store.provider_connection(caller) as result:
        assert result is connection
    connect.assert_called_once_with(
        host="example.test",
        dbname="isolated",
        sslmode="require",
        password="unit-test-only-database-password",
        connect_timeout=5,
    )
    connection.close.assert_called_once()


def test_credential_rotation_never_commits_caller_business_writes(pi_db, monkeypatch) -> None:
    _save_oauth(pi_db)
    monkeypatch.setattr(
        store,
        "call_bridge",
        lambda payload, **kwargs: {
            "ok": True,
            "content": "OK",
            "credential": payload["credential"],
        },
    )
    with pi_db.cursor() as cur:
        cur.execute("CREATE TEMP TABLE pending_business_write (value INT) ON COMMIT DROP")
        cur.execute("INSERT INTO pending_business_write VALUES (7)")
    with store.provider_connection(pi_db) as credential_conn:
        store.invoke_provider(credential_conn, "openai", "prompt", "system")
    with pi_db.cursor() as cur:
        cur.execute("SELECT value FROM pending_business_write")
        assert cur.fetchone()[0] == 7
    pi_db.rollback()


def test_successful_oauth_login_persists_only_encrypted_credential(pi_db, monkeypatch) -> None:
    from contextlib import contextmanager

    @contextmanager
    def database():
        conn = psycopg2.connect(os.environ["FQP_PI_TEST_DB"])
        try:
            yield conn
        finally:
            conn.close()

    monkeypatch.setattr(pi_login, "get_db", database)
    session = pi_login.LoginSession(
        "id", "owner", "openai", {"defaultModel": "gpt-5-mini"}, None, MagicMock()
    )
    public = pi_login._persist(
        session,
        {
            "type": "oauth",
            "access": "private-access",
            "refresh": "private-refresh",
            "expires": 9999999999999,
        },
    )
    assert public["authType"] == "oauth" and public["hasCredential"]
    assert public["lastTestStatus"] is None
    assert "private-access" not in json.dumps(public)
    with pi_db.cursor() as cur:
        cur.execute(
            f"SELECT {store.CONFIG_COLUMNS} FROM llm_provider_configs WHERE provider_code='openai'"
        )
        record = store._config_record(cur.fetchone())
        assert "private-refresh" not in record["pi_credential_encrypted"]
        assert store._credential(record)["access"] == "private-access"
