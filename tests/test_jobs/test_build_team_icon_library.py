from scripts.jobs.build_team_icon_library import normalize_team_name, resolve_team_icons


def test_resolves_team_icon_through_manual_provider_name_variant():
    entries, missing = resolve_team_icons(
        [{"id": 29, "name_cn": "奥斯陆KFUM", "name_en": "", "short_name": "", "aliases": []}],
        {"kfum奥斯陆": {"id": "5263", "name": "KFUM奥斯陆"}},
    )

    assert missing == []
    assert entries[0]["logoUrl"] == "/team-crests/500-5263.png"
    assert entries[0]["source"] == "500com"


def test_normalizes_name_spacing_and_punctuation_for_provider_matching():
    assert normalize_team_name("AIK·索尔纳") == normalize_team_name("AIK 索尔纳")
