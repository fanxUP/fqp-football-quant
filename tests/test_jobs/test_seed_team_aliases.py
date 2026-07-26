from unittest.mock import MagicMock, patch

from scripts.jobs import seed_team_aliases


def test_verified_api_alias_is_repointed_to_current_sporttery_team():
    connection = MagicMock()
    cursor = MagicMock()
    cursor.fetchone.return_value = (88, False)
    connection.cursor.return_value.__enter__.return_value = cursor
    context = MagicMock()
    context.__enter__.return_value = connection

    with patch.object(seed_team_aliases, "get_db", return_value=context):
        result = seed_team_aliases.run()

    insert_query = next(
        " ".join(call.args[0].split())
        for call in cursor.execute.call_args_list
        if "INSERT INTO team_aliases" in call.args[0]
    )
    assert (
        "ON CONFLICT (source_name, alias_name) DO UPDATE SET "
        "team_id = EXCLUDED.team_id"
    ) in insert_query
    assert result["aliases_added"] == 0
    assert result["aliases_updated"] > 0
