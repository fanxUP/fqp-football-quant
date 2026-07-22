import subprocess
import sys

from scripts.official_odds_history import backfill_fixed_bonus_history, parse_fixed_bonus_history


def test_parse_fixed_bonus_history_preserves_each_official_update_time_and_play():
    raw = {
        "value": {
            "oddsHistory": {
                "hadList": [
                    {
                        "updateDate": "2025-06-28",
                        "updateTime": "09:48:36",
                        "h": "1.27",
                        "d": "4.85",
                        "a": "7.35",
                    },
                    {
                        "updateDate": "2025-06-30",
                        "updateTime": "10:19:40",
                        "h": "1.18",
                        "d": "5.55",
                        "a": "9.80",
                    },
                ],
                "hhadList": [
                    {
                        "updateDate": "2025-06-28",
                        "updateTime": "09:48:45",
                        "goalLine": "-1",
                        "h": "1.88",
                        "d": "3.70",
                        "a": "3.06",
                    },
                ],
                "ttgList": [
                    {
                        "updateDate": "2025-06-28",
                        "updateTime": "09:49:00",
                        "s0": "19.00",
                        "s7": "18.00",
                        "s0f": "0",
                    },
                ],
                "hafuList": [
                    {
                        "updateDate": "2025-06-28",
                        "updateTime": "09:49:01",
                        "hh": "1.85",
                        "da": "17.00",
                        "hhf": "0",
                    },
                ],
                "crsList": [
                    {
                        "updateDate": "2025-06-28",
                        "updateTime": "09:49:02",
                        "s01s00": "8.00",
                        "s-1sh": "20.00",
                        "s01s00f": "0",
                    },
                ],
            }
        }
    }

    snapshots = parse_fixed_bonus_history(raw)

    assert len(snapshots) == 15
    spf_home = [
        item for item in snapshots if item["play_type"] == "spf" and item["option_code"] == "h"
    ]
    assert [item["sp_value"] for item in spf_home] == [1.27, 1.18]
    assert spf_home[0]["snapshot_time"] == "2025-06-28T09:48:36"
    rqspf_home = next(
        item for item in snapshots if item["play_type"] == "rqspf" and item["option_code"] == "h"
    )
    assert rqspf_home["handicap"] == -1.0
    assert {item["option_code"] for item in snapshots if item["play_type"] == "zjq"} == {"0", "7"}
    assert (
        next(
            item for item in snapshots if item["play_type"] == "bf" and item["option_code"] == "1:0"
        )["option_name"]
        == "1:0"
    )
    assert (
        next(
            item
            for item in snapshots
            if item["play_type"] == "bf" and item["option_code"] == "other_h"
        )["option_name"]
        == "胜其他"
    )


def test_parse_fixed_bonus_history_skips_flag_fields_and_invalid_update_times():
    raw = {
        "value": {
            "oddsHistory": {
                "hadList": [
                    {
                        "updateDate": "not-a-date",
                        "updateTime": "09:48:36",
                        "h": "1.27",
                        "d": "4.85",
                        "a": "7.35",
                    },
                    {
                        "updateDate": "2025-06-28",
                        "updateTime": "09:48:36",
                        "h": "0",
                        "d": "bad",
                        "a": "7.35",
                        "hf": "1",
                    },
                ]
            }
        }
    }

    snapshots = parse_fixed_bonus_history(raw)

    assert [(item["option_code"], item["sp_value"]) for item in snapshots] == [("a", 7.35)]


def test_direct_script_entrypoint_is_usable_for_local_schedulers():
    result = subprocess.run(
        [sys.executable, "scripts/official_odds_history.py", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Backfill official Sporttery" in result.stdout


def test_backfill_stops_after_consecutive_official_403_responses():
    from unittest.mock import MagicMock, patch

    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [(1, "2035672"), (2, "2035671"), (3, "2035670"), (4, "2035669")]
    client = MagicMock()
    client.get_uniform_fixed_bonus.side_effect = RuntimeError("returned 403 Forbidden")

    with (
        patch("scripts.official_odds_history.get_db") as get_db,
        patch("scripts.official_odds_history.SportteryClient", return_value=client),
    ):
        get_db.return_value.__enter__.return_value = connection

        result = backfill_fixed_bonus_history("2025-07-01", "2025-07-01")

    assert result["status"] == "blocked"
    assert result["matches_processed"] == 3
    assert result["matches_failed"] == 3
    client.get_uniform_fixed_bonus.assert_called_with(2035670)
    assert client.get_uniform_fixed_bonus.call_count == 3
    client.close.assert_called_once()


def test_backfill_pauses_three_minutes_after_each_300_match_batch():
    from unittest.mock import MagicMock, patch

    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [(index, str(2037000 + index)) for index in range(301)]
    client = MagicMock()
    client.get_uniform_fixed_bonus.return_value = {}

    with (
        patch("scripts.official_odds_history.get_db") as get_db,
        patch(
            "scripts.official_odds_history.store_fixed_bonus_history",
            return_value={"inserted": 0, "already_present": 0, "errors": 0},
        ),
        patch("scripts.official_odds_history.time.sleep") as sleep,
        patch("scripts.official_odds_history.SportteryClient", return_value=client),
    ):
        get_db.return_value.__enter__.return_value = connection

        result = backfill_fixed_bonus_history("2025-07-01", "2025-07-01")

    assert result["matches_processed"] == 301
    sleep.assert_called_once_with(180)
