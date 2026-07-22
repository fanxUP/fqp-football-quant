from bs4 import BeautifulSoup

from scripts.jobs.collect_official_standings import parse_finland, parse_norway


def test_parse_norway_keeps_team_and_table_statistics():
    soup = BeautifulSoup(
        """
        <table><tr><th>#</th><th>Lag</th><th>Kamper</th><th>V</th><th>U</th><th>T</th><th>Mål</th><th>Diff</th><th>Poeng</th></tr>
        <tr><td>1</td><td>Brann</td><td>10</td><td>7</td><td>2</td><td>1</td><td>20</td><td>8</td><td>23</td></tr>
        </table>
        """,
        "html.parser",
    )

    assert parse_norway(soup) == [
        {
            "rank": 1,
            "team_name": "Brann",
            "played": 10,
            "won": 7,
            "drawn": 2,
            "lost": 1,
            "goals_for": 20,
            "goals_against": 8,
            "points": 23,
            "raw": ["1", "Brann", "10", "7", "2", "1", "20", "8", "23"],
        }
    ]


def test_parse_finland_ignores_non_standings_tables():
    soup = BeautifulSoup(
        """
        <table><tr><th>新闻</th></tr><tr><td>ignored</td></tr></table>
        <table><tr><th>Sarjataulukko</th></tr>
        <tr><th>Sija</th><th>#</th><th>Joukkue</th><th>P</th><th>O</th></tr>
        <tr><td>1</td><td>1.</td><td>HJK</td><td>25</td><td>10</td></tr>
        </table>
        """,
        "html.parser",
    )

    rows = parse_finland(soup)
    assert len(rows) == 1
    assert rows[0]["team_name"] == "HJK"
    assert rows[0]["rank"] == 1
    assert rows[0]["points"] == 25
    assert rows[0]["played"] == 10
