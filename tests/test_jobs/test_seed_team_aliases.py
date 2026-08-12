from unittest.mock import MagicMock, patch

from scripts.jobs import seed_team_aliases
from scripts.jobs.seed_team_aliases import MANUAL_ALIASES


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
        "ON CONFLICT (source_name, alias_name) DO UPDATE SET team_id = EXCLUDED.team_id"
    ) in insert_query
    assert result["aliases_added"] == 0
    assert result["aliases_updated"] > 0


def test_current_official_pool_has_international_news_aliases() -> None:
    expected = {
        "巴黎圣日尔曼": "Paris Saint-Germain",
        "阿斯顿维拉": "Aston Villa",
        "普拉滕斯": "Platense",
        "科金博联": "Coquimbo Unido",
        "帕尔梅拉斯": "Palmeiras",
        "波特诺山丘": "Cerro Porteño",
    }

    for chinese_name, international_name in expected.items():
        assert international_name in MANUAL_ALIASES[chinese_name]
