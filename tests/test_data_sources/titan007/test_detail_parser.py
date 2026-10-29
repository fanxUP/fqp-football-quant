from scripts.sources.titan007 import parsers


def test_parse_tech_statistic_data_fallback():
    html = (
        "<script>var techStatisticData = \"[[0,[0,'4','14',22,78],[4,'9','21',30,70]]]\";</script>"
    )
    stats = parsers.parse_tech_statistic_data(html)
    assert stats["角球"] == {"home": "4", "away": "14"}
    assert stats["射门"] == {"home": "9", "away": "21"}


def test_parse_detail_page_uses_tech_fallback():
    html = (
        "<html><script>var techStatisticData = "
        "\"[[0,[0,'4','14',22,78],[4,'9','21',30,70]]]\";</script></html>"
    )
    detail = parsers.parse_detail_page(html, 1)
    assert len(detail["stats"]) == 2
    assert detail["stats"]["射门"]["away"] == "21"


def test_parse_detail_page_reads_weather():
    html = (
        '<html><div class="row"><label></label>'
        "<label>天气：间中有云</label><label>温度：10°C</label></div></html>"
    )
    detail = parsers.parse_detail_page(html, 1)
    assert detail["header"]["weather"] == "间中有云"
    assert detail["header"]["temperature"] == "10°C"


def test_parse_player_photo_map():
    html = '<script>var playerImgData = "166669,images/166669/a.png^235689,images/235689/b.png^12,";</script>'
    photos = parsers.parse_player_photo_map(html)
    assert photos[166669] == "images/166669/a.png"
    assert photos[235689] == "images/235689/b.png"
    assert 12 not in photos


def test_parse_predicted_lineup():
    html = (
        '<div class="homeN"><a class="coach" title="教练甲">(主教练: 甲)</a></div>'
        '<div class="guestN"><a class="coach" title="教练乙">(主教练: 乙)</a></div>'
        '<div id="matchBox2"><div class="plays"><div class="home">'
        '<div class="play"><em class="num">9</em><div class="name"><a>前锋甲</a></div></div>'
        '</div><div class="guest"></div></div></div>'
    )
    data = parsers.parse_predicted_lineup(html)
    assert data["coaches"]["home"] == "教练甲"
    assert data["home"][0]["number"] == "9"
    assert data["home"][0]["player_name"] == "前锋甲"
