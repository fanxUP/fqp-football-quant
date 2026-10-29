import hashlib
import json

import pytest

from scripts.jobs import build_team_icon_library as icons
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


def test_does_not_treat_official_match_id_as_a_500com_crest_id():
    entries, missing = resolve_team_icons(
        [
            {
                "id": None,
                "name_cn": "皇家盐湖城",
                "name_en": "",
                "short_name": "",
                "aliases": [],
                "provider_id": "1663",
            }
        ],
        {},
    )

    assert entries == []
    assert missing == ["皇家盐湖城"]


def test_verified_provider_name_takes_precedence_over_other_sources_numeric_id():
    entries, missing = resolve_team_icons(
        [
            {
                "id": None,
                "name_cn": "阿森纳",
                "name_en": "Arsenal",
                "short_name": "",
                "aliases": [],
                "provider_id": "1",
            }
        ],
        {"阿森纳": {"id": "verified-500-id", "name": "阿森纳"}},
    )

    assert missing == []
    assert entries[0]["logoUrl"] == "/team-crests/500-verified-500-id.png"


@pytest.fixture
def cached_crest_library(tmp_path):
    cache = tmp_path / "cache"
    (cache / "images/teams").mkdir(parents=True)
    body = b"\x89PNG\r\n\x1a\n" + b"test-pinned-asset"
    (cache / "images/teams/19.png").write_bytes(body)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "source": "titan007",
                "entries": [
                    {
                        "source_id": 19,
                        "names": ["阿森纳", "Arsenal", "阿仙奴"],
                        "sha256": hashlib.sha256(body).hexdigest(),
                        "source_url": "https://zq.titan007.com/Image/team/images/19/example.png",
                    }
                ],
            }
        )
    )
    registry = tmp_path / "registry.ts"
    icons.write_registry(
        [
            {
                "names": ["阿森纳", "阿森纳旧别名"],
                "logoUrl": "/team-crests/500-1.png",
                "source": "500com",
            },
            {"names": ["中国"], "logoUrl": "/team-crests/500-426.png", "source": "500com"},
            {"names": ["中国", "CHN"], "logoUrl": "/team-crests/500-426.png", "source": "500com"},
        ],
        registry_path=registry,
    )
    return cache, manifest, registry, tmp_path / "public/team-crests"


def test_cached_refresh_replaces_all_aliases_and_is_idempotent(cached_crest_library):
    cache, manifest, registry, assets = cached_crest_library
    result = icons.sync_cached_crests(
        cache, manifest_path=manifest, registry_path=registry, asset_dir=assets
    )

    assert result["verified_crests"] == 1
    assert (assets / "titan007-19.png").read_bytes() == (cache / "images/teams/19.png").read_bytes()
    text = registry.read_text()
    assert '"source": "titan007"' in text
    assert '"Arsenal"' in text and '"阿仙奴"' in text and '"阿森纳旧别名"' in text
    assert '"logoUrl": "/team-crests/500-426.png"' in text
    assert '"logoUrl": "/team-crests/500-1.png"' not in text

    again = icons.sync_cached_crests(
        cache, manifest_path=manifest, registry_path=registry, asset_dir=assets
    )
    assert again["assets_written"] == 0
    assert registry.read_text() == text


def test_cached_refresh_validates_all_hashes_before_writing(cached_crest_library):
    cache, manifest, registry, assets = cached_crest_library
    data = json.loads(manifest.read_text())
    second = {**data["entries"][0], "source_id": 33, "names": ["托特纳姆热刺"], "sha256": "0" * 64}
    data["entries"].append(second)
    manifest.write_text(json.dumps(data))
    (cache / "images/teams/33.png").write_bytes((cache / "images/teams/19.png").read_bytes())
    original = registry.read_bytes()

    with pytest.raises(ValueError, match="digest"):
        icons.sync_cached_crests(
            cache, manifest_path=manifest, registry_path=registry, asset_dir=assets
        )

    assert registry.read_bytes() == original
    assert not assets.exists()


def test_cached_refresh_rejects_duplicate_alias_ownership(cached_crest_library):
    cache, manifest, registry, assets = cached_crest_library
    data = json.loads(manifest.read_text())
    data["entries"].append({**data["entries"][0], "source_id": 33, "names": ["arsenal"]})
    manifest.write_text(json.dumps(data))
    (cache / "images/teams/33.png").write_bytes((cache / "images/teams/19.png").read_bytes())

    with pytest.raises(ValueError, match="alias"):
        icons.sync_cached_crests(
            cache, manifest_path=manifest, registry_path=registry, asset_dir=assets
        )

    assert not assets.exists()


def test_cached_refresh_rejects_symlink_outside_cache(cached_crest_library, tmp_path):
    cache, manifest, registry, assets = cached_crest_library
    original = cache / "images/teams/19.png"
    outside = tmp_path / "outside.png"
    original.rename(outside)
    original.symlink_to(outside)

    with pytest.raises(ValueError, match="outside"):
        icons.sync_cached_crests(
            cache, manifest_path=manifest, registry_path=registry, asset_dir=assets
        )

    assert not assets.exists()
