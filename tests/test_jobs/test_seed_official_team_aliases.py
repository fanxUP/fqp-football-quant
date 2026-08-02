from unittest.mock import MagicMock, patch

from scripts.jobs import seed_official_team_aliases


def test_official_and_sporttery_aliases_share_exact_team_identity():
    connection = MagicMock()
    cursor = MagicMock()
    cursor.fetchone.return_value = (77, False)
    connection.cursor.return_value.__enter__.return_value = cursor
    context = MagicMock()
    context.__enter__.return_value = connection

    with patch.object(seed_official_team_aliases, "get_db", return_value=context):
        result = seed_official_team_aliases.run()

    insert_query = next(
        " ".join(call.args[0].split())
        for call in cursor.execute.call_args_list
        if "INSERT INTO team_aliases" in call.args[0]
    )
    identity_query = next(
        " ".join(call.args[0].split())
        for call in cursor.execute.call_args_list
        if "FROM teams t" in call.args[0]
    )
    alias_sources = {
        call.args[1][1]
        for call in cursor.execute.call_args_list
        if "INSERT INTO team_aliases" in call.args[0]
    }
    assert "t.team_name_cn = %s" in identity_query
    assert "ta.source_name = 'sporttery'" in identity_query
    assert alias_sources == {"official_standings", "sporttery"}
    assert (
        "ON CONFLICT (source_name, alias_name) DO UPDATE SET team_id = EXCLUDED.team_id"
    ) in insert_query
    assert result["aliases_inserted"] == 0
    assert result["aliases_updated"] > 0
