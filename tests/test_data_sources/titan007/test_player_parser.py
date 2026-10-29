from scripts.sources.titan007 import parsers


def test_parse_player_tech_extracts_player_id():
    html = """<table><tr><th>号码</th><th>球员</th><th>位置</th><th>评分</th></tr>
    <tr><td>9</td><td><a href="http://zq.titan007.com/cn/team/player.aspx?PlayerID=12345&TeamID=1">前锋甲</a></td>
    <td>前锋</td><td>7.1</td></tr></table>"""
    data = parsers.parse_player_tech(html)
    assert data["home"][0]["player_id"] == 12345
    assert data["home"][0]["球员"] == "前锋甲"
