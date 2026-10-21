from __future__ import annotations

from pathlib import Path

import pytest

from ops.server import publish_frontend


def make_build(root: Path, *, index: str | None = None) -> Path:
    source = root / "dist"
    assets = source / "assets"
    assets.mkdir(parents=True)
    (assets / "app.js").write_text("new js", encoding="utf-8")
    (assets / "app.css").write_text("new css", encoding="utf-8")
    (source / "index.html").write_text(
        index
        or '<script type="module" src="/assets/app.js"></script>'
        '<link rel="stylesheet" href="/assets/app.css">',
        encoding="utf-8",
    )
    return source


def test_publish_copies_assets_before_switching_index_and_retains_old_assets(tmp_path):
    source = make_build(tmp_path)
    web_root = tmp_path / "web"
    (web_root / "assets").mkdir(parents=True)
    (web_root / "index.html").write_text("old index", encoding="utf-8")
    (web_root / "old-hash.js").write_text("old asset", encoding="utf-8")
    (web_root / "assets/app.js").write_text("old js", encoding="utf-8")

    updated = publish_frontend.publish(source, web_root, expected_web_root=web_root)

    assert updated == 2
    assert (web_root / "assets/app.js").read_text(encoding="utf-8") == "new js"
    assert (web_root / "assets/app.css").read_text(encoding="utf-8") == "new css"
    assert (web_root / "index.html").read_text(encoding="utf-8") == (
        source / "index.html"
    ).read_text(encoding="utf-8")
    assert (web_root / "old-hash.js").read_text(encoding="utf-8") == "old asset"
    assert not list(web_root.rglob("*.tmp"))


def test_missing_entry_asset_does_not_switch_index(tmp_path):
    source = make_build(
        tmp_path,
        index='<script type="module" src="/assets/missing.js"></script>',
    )
    web_root = tmp_path / "web"
    web_root.mkdir()
    old_index = web_root / "index.html"
    old_index.write_text("old index", encoding="utf-8")

    with pytest.raises(SystemExit, match="missing a regular entry asset"):
        publish_frontend.publish(source, web_root, expected_web_root=web_root)

    assert old_index.read_text(encoding="utf-8") == "old index"


def test_external_entry_urls_are_not_treated_as_local_files(tmp_path):
    source = make_build(
        tmp_path,
        index=(
            '<script src="https://cdn.example/app.js"></script>'
            '<link rel="stylesheet" href="//cdn.example/app.css">'
            '<script type="module" src="/assets/app.js"></script>'
        ),
    )
    web_root = tmp_path / "web"
    web_root.mkdir()

    publish_frontend.publish(source, web_root, expected_web_root=web_root)

    assert (web_root / "index.html").is_file()


def test_source_symlink_is_rejected(tmp_path):
    source = make_build(tmp_path)
    outside = tmp_path / "outside.js"
    outside.write_text("outside", encoding="utf-8")
    (source / "assets/app.js").unlink()
    (source / "assets/app.js").symlink_to(outside)
    web_root = tmp_path / "web"
    web_root.mkdir()

    with pytest.raises(SystemExit, match="Symlink in frontend build"):
        publish_frontend.publish(source, web_root, expected_web_root=web_root)


def test_destination_symlink_is_rejected(tmp_path):
    source = make_build(tmp_path)
    web_root = tmp_path / "web"
    (web_root / "assets").mkdir(parents=True)
    outside = tmp_path / "outside.js"
    outside.write_text("outside", encoding="utf-8")
    (web_root / "assets/app.js").symlink_to(outside)

    with pytest.raises(SystemExit, match="Symlink target in Nginx web root"):
        publish_frontend.publish(source, web_root, expected_web_root=web_root)

    assert outside.read_text(encoding="utf-8") == "outside"


def test_traversal_entry_reference_is_rejected_without_index_switch(tmp_path):
    source = make_build(
        tmp_path,
        index='<script src="/../outside.js"></script>',
    )
    web_root = tmp_path / "web"
    web_root.mkdir()
    old_index = web_root / "index.html"
    old_index.write_text("old index", encoding="utf-8")

    with pytest.raises(SystemExit, match="Unsafe frontend entry reference"):
        publish_frontend.publish(source, web_root, expected_web_root=web_root)

    assert old_index.read_text(encoding="utf-8") == "old index"


def test_publisher_requires_the_expected_web_root_without_test_override(tmp_path):
    source = make_build(tmp_path)
    web_root = tmp_path / "web"
    web_root.mkdir()

    with pytest.raises(SystemExit, match="Configured Nginx web root"):
        publish_frontend.main([str(source), str(web_root)])


def test_symlink_web_root_is_rejected(tmp_path):
    source = make_build(tmp_path)
    real_root = tmp_path / "real-web"
    real_root.mkdir()
    linked_root = tmp_path / "web"
    linked_root.symlink_to(real_root, target_is_directory=True)

    with pytest.raises(SystemExit, match="Configured Nginx web root"):
        publish_frontend.publish(source, linked_root, expected_web_root=linked_root)


def test_deploy_runner_wires_publish_and_fails_closed_on_restore_error():
    deploy = Path("ops/server/deploy.sh").read_text(encoding="utf-8")

    assert '.venv/bin/python "$SCRIPT_DIR/publish_frontend.py"' in deploy
    publish_mark = deploy.rindex("FRONTEND_PUBLISH_ATTEMPTED=true")
    publish_call = deploy.index("publish_frontend", publish_mark)
    assert publish_mark < publish_call
    assert 'if [[ "$FRONTEND_PUBLISH_ATTEMPTED" == true ]] && ! publish_frontend; then' in deploy
    assert "ROLLBACK_REQUIRED: unable to restore prior frontend files" in deploy
