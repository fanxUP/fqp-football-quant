"""The imported cache stays private, consistent, and independently usable."""

import sqlite3
from pathlib import Path

import pytest

from scripts.titan007_data import copy_source, inspect_cache, iter_source_rows


def source_tree(root: Path) -> Path:
    data = root / "data"
    data.mkdir(parents=True)
    with sqlite3.connect(data / "titan007.db") as conn:
        conn.execute("CREATE TABLE matches (match_id INTEGER PRIMARY KEY, home_score INTEGER)")
        conn.executemany("INSERT INTO matches VALUES (?, ?)", [(1, 0), (2, None)])
    (data / "images" / "teams").mkdir(parents=True)
    (data / "images" / "teams" / "1.png").write_bytes(b"image fixture")
    return root


def test_snapshot_copies_database_and_assets_without_changing_source(tmp_path):
    src = source_tree(tmp_path / "source")
    before = (src / "data" / "titan007.db").read_bytes()
    dst = tmp_path / "project" / "titan007"
    manifest = copy_source(src, dst)
    assert manifest["database_sha256"]
    assert manifest["images_copied"] == 1
    assert (dst / "images" / "teams" / "1.png").read_bytes() == b"image fixture"
    assert (src / "data" / "titan007.db").read_bytes() == before
    assert list(iter_source_rows(dst, "matches", batch_size=1)) == [
        {"match_id": 1, "home_score": 0},
        {"match_id": 2, "home_score": None},
    ]
    assert inspect_cache(dst)["tables"]["matches"] == 2
    assert (dst / "SOURCE_SNAPSHOT.json").is_file()


def test_snapshot_uses_committed_wal_state_and_does_not_copy_uncommitted_rows(tmp_path):
    src = source_tree(tmp_path / "source")
    with sqlite3.connect(src / "data" / "titan007.db") as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("INSERT INTO matches VALUES (3, 1)")
        writer.commit()
        writer.execute("INSERT INTO matches VALUES (4, 2)")
        dst = tmp_path / "snapshot"
        copy_source(src, dst)
        assert [r["match_id"] for r in iter_source_rows(dst, "matches")] == [1, 2, 3]
        writer.rollback()


def test_repeat_copy_preserves_existing_project_cache(tmp_path):
    src = source_tree(tmp_path / "source")
    dst = tmp_path / "snapshot"
    copy_source(src, dst)
    with sqlite3.connect(dst / "titan007.db") as conn:
        conn.execute("INSERT INTO matches VALUES (9, 4)")
    with pytest.raises(FileExistsError):
        copy_source(src, dst)
    assert inspect_cache(dst)["tables"]["matches"] == 3


def test_missing_cache_read_does_not_create_empty_database(tmp_path):
    dst = tmp_path / "missing"
    with pytest.raises(FileNotFoundError):
        inspect_cache(dst)
    assert not dst.exists()


def test_failed_copy_removes_partial_destination_and_preserves_source(tmp_path, monkeypatch):
    src = source_tree(tmp_path / "source")
    dst = tmp_path / "snapshot"
    monkeypatch.setattr(
        "scripts.titan007_data.shutil.copy2",
        lambda *a, **k: (_ for _ in ()).throw(OSError("copy failed")),
    )
    with pytest.raises(OSError, match="copy failed"):
        copy_source(src, dst)
    assert not dst.exists()
    assert not list(tmp_path.glob(".snapshot-import-*"))
    assert (src / "data" / "titan007.db").exists()


def test_table_selection_rejects_sql_and_keeps_zero_distinct_from_unknown(tmp_path):
    dst = tmp_path / "snapshot"
    copy_source(source_tree(tmp_path / "source"), dst)
    with pytest.raises(ValueError):
        list(iter_source_rows(dst, "matches; DROP TABLE matches;--"))
    with pytest.raises(ValueError):
        list(iter_source_rows(dst, "matches", batch_size=0))
    assert inspect_cache(dst)["tables"]["matches"] == 2


def test_snapshot_cli_completes_each_phase_and_publishes_cache(tmp_path, capsys):
    from scripts.titan007_data import main

    src = source_tree(tmp_path / "source")
    dst = tmp_path / "project-cache"
    assert main(["--data-dir", str(dst), "snapshot", "--source", str(src)]) == 0
    output = capsys.readouterr().out
    assert "数据库复制 100%" in output
    assert "计算数据摘要" in output
    assert "检查数据库完整性" in output
    assert "复制图片" in output
    assert inspect_cache(dst)["tables"]["matches"] == 2


def test_corrupt_database_fails_validation_and_removes_temporary_verification_copy(
    tmp_path, monkeypatch
):
    from scripts.titan007_data import _hash_and_validate

    monkeypatch.setattr("scripts.titan007_data.tempfile.tempdir", str(tmp_path))
    database = tmp_path / "corrupt.db"
    database.write_bytes(b"not a SQLite database")
    with pytest.raises(sqlite3.DatabaseError):
        _hash_and_validate(database)
    assert database.read_bytes() == b"not a SQLite database"
    assert not list(tmp_path.glob("fqp-titan007-verify-*"))
