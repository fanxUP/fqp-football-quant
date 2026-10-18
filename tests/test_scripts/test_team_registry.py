import pytest

from scripts.team_registry import official_team_code, resolve_team_alias


def test_official_team_code_is_stable_and_does_not_collide_on_shared_prefix():
    slovakia = official_team_code("斯洛伐克")
    slovakia_u21 = official_team_code("斯洛伐克U21")

    assert slovakia.startswith("sporttery-team:")
    assert slovakia == official_team_code("斯洛伐克")
    assert slovakia != slovakia_u21
    assert len(slovakia) <= 64


def test_shared_alias_resolution_is_source_scoped_and_read_only(mock_conn):
    conn, cur = mock_conn
    cur.fetchall.return_value = [(11,)]
    result = resolve_team_alias(conn, " 测试队 ", source_name="sporttery")
    assert result.resolved_id == 11
    assert result.namespace == "sporttery"
    assert result.requested_key == "测试队"
    query, params = cur.execute.call_args.args
    assert "DISTINCT" in query and "LIMIT 2" in query
    assert params == {"alias_name": "测试队", "source_name": "sporttery"}
    conn.commit.assert_not_called()


def test_shared_alias_resolution_preserves_ambiguity(mock_conn):
    conn, cur = mock_conn
    cur.fetchall.return_value = [(11,), (12,)]
    result = resolve_team_alias(conn, "测试队", source_name="sporttery")
    assert result.status == "ambiguous"
    assert result.resolved_id is None


def test_missing_alias_does_not_guess_from_display_name(mock_conn):
    conn, cur = mock_conn
    cur.fetchall.return_value = []
    result = resolve_team_alias(conn, "测试队U21", source_name="sporttery")
    assert result.status == "unresolved"
    assert "team_name_cn" not in cur.execute.call_args.args[0]


def test_empty_alias_skips_database(mock_conn):
    conn, _ = mock_conn
    assert resolve_team_alias(conn, " ", source_name="sporttery").resolved_id is None
    conn.cursor.assert_not_called()


def test_unknown_alias_namespace_is_rejected_before_query(mock_conn):
    conn, _ = mock_conn
    with pytest.raises(KeyError):
        resolve_team_alias(conn, "测试队", source_name="not_registered")
    conn.cursor.assert_not_called()


def test_registered_source_keeps_existing_database_namespace(mock_conn):
    conn, cur = mock_conn
    cur.fetchall.return_value = [(11,)]
    result = resolve_team_alias(conn, "Example FC", source_name="api_football")
    assert result.namespace == "api_football"
    assert cur.execute.call_args.args[1]["source_name"] == "apifootball"


def test_source_without_alias_support_does_not_query_teams(mock_conn):
    conn, _ = mock_conn
    with pytest.raises(ValueError, match="namespace"):
        resolve_team_alias(conn, "Example FC", source_name="guardian")
    conn.cursor.assert_not_called()
