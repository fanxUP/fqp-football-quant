from __future__ import annotations

from scripts.model_prediction_run_loader import load_latest_prediction_group


class _Cursor:
    def __init__(self, rows):
        self.rows = rows
        self.query = ""
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query, params):
        self.query = query
        self.params = params

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self, results):
        self.results = iter(results)
        self.cursors = []

    def cursor(self):
        cursor = _Cursor(next(self.results))
        self.cursors.append(cursor)
        return cursor


def test_loader_chooses_complete_group_before_loading_its_rows():
    conn = _Connection(
        [
            [
                (
                    "group-2",
                    "run-2",
                    901,
                    22,
                    "spf",
                    "",
                    "2026-10-23T10:00:00",
                    ["3", "1", "0"],
                    {"3": 0.5, "1": 0.25, "0": 0.25},
                    "f" * 64,
                    "complete",
                )
            ],
            [
                (100, "3", 0.5, 0.4, 600, 77, "2026-10-23T10:00:00", "spf"),
                (101, "1", 0.25, 0.3, 601, 77, "2026-10-23T10:00:00", "spf"),
                (102, "0", 0.25, 0.3, 602, 77, "2026-10-23T10:00:00", "spf"),
            ],
        ]
    )

    loaded = load_latest_prediction_group(conn, match_id=901, model_version_id=22, play_type="spf")

    assert loaded["group_id"] == "group-2"
    assert [row["option_code"] for row in loaded["options"]] == ["3", "1", "0"]
    assert "group_status = 'complete'" in conn.cursors[0].query
    assert "run_status IN" in conn.cursors[0].query
    assert "'completed','partial'" in conn.cursors[0].query.replace(" ", "").replace("\n", "")
    assert "model_prediction_group_options" in conn.cursors[1].query


def test_loader_does_not_fall_back_to_legacy_after_a_complete_group_exists():
    conn = _Connection(
        [
            [
                (
                    "group-2",
                    "run-2",
                    901,
                    22,
                    "spf",
                    "",
                    "2026-10-23T10:00:00",
                    ["3", "1", "0"],
                    {"3": 0.5, "1": 0.25, "0": 0.25},
                    "f" * 64,
                    "complete",
                )
            ],
            [],
        ]
    )

    loaded = load_latest_prediction_group(conn, match_id=901, model_version_id=22, play_type="spf")

    assert loaded["options"] == []
    assert loaded["status"] == "incomplete_group"
    assert len(conn.cursors) == 2
    assert "FROM model_predictions" not in conn.cursors[1].query
