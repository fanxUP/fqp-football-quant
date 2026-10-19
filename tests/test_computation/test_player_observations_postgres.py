"""Opt-in P104 player groups on the explicitly isolated synthetic database."""

from contextlib import closing
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest

from scripts.data_contracts import AcquisitionStatus
from scripts.feature_storage import (
    get_injuries_for_match,
    get_injury_observation_for_match,
    get_lineup_for_match,
)
from scripts.jobs.collect_injury_data import _process_fixture_injuries
from scripts.jobs.collect_lineup_data import _process_lineup
from scripts.observation_storage import capture_observation_cutoff, load_observation_as_of
from scripts.player_observations import (
    has_fresh_team_checks,
    record_player_acquisition_failure,
    team_stream,
)
from tests.test_computation import test_observation_postgres as obs

connect = obs.connect
pg = obs.pg
match_id = obs.match_id


@pytest.fixture
def match(pg, match_id):
    tag = uuid4().hex
    with pg.cursor() as q:
        q.execute(
            "INSERT INTO teams(team_code,team_name_cn) VALUES (%s,'固定主'),(%s,'固定客') RETURNING id",
            (tag + "h", tag + "a"),
        )
        home, away = [r[0] for r in q.fetchall()]
        q.execute(
            "INSERT INTO competitions(competition_code,competition_type) VALUES (%s,'league') RETURNING id",
            (tag,),
        )
        comp = q.fetchone()[0]
        q.execute(
            "INSERT INTO seasons(season_code,season_name) VALUES (%s,'fixed') RETURNING id", (tag,)
        )
        season = q.fetchone()[0]
        q.execute(
            "INSERT INTO competition_seasons(competition_id,season_id) VALUES (%s,%s) RETURNING id",
            (comp, season),
        )
        cs = q.fetchone()[0]
    pg.commit()
    return dict(id=match_id, home_team_id=home, away_team_id=away, competition_season_id=cs)


def lineup(start=1):
    return dict(
        team=dict(name="Home"),
        formation="4-3-3",
        startXI=[
            dict(player=dict(id=i, name=f"P{i}", pos="G" if i == start else "D"))
            for i in range(start, start + 11)
        ],
        substitutes=[dict(player=dict(id=start + 20, name="Sub", pos="F"))],
    )


def freeze(pg, match):
    cutoff = capture_observation_cutoff(
        pg,
        streams=[
            team_stream(match["id"], team, domain)
            for domain in ("lineup", "injuries")
            for team in (match["home_team_id"], match["away_team_id"])
        ],
    )
    pg.commit()
    return cutoff


def read(pg, match, domain, cutoff=None, away=False):
    cut = cutoff or freeze(pg, match)
    return load_observation_as_of(
        pg,
        **team_stream(
            match["id"], match["away_team_id"] if away else match["home_team_id"], domain
        ),
        cutoff=cut,
    )


def save_lineup(pg, match, payload=None, **kwargs):
    return _process_lineup(
        pg,
        match["id"],
        payload or lineup(),
        match["home_team_id"],
        "2026-10-18T23:30:00",
        api_fixture_id=900,
        **kwargs,
    )


def injury(pid=1, team="Home", **extra):
    return dict(
        team=dict(name=team),
        player=dict(id=pid, name=f"P{pid}", type="Missing Fixture", reason="Back Bruise"),
        fixture=dict(id=900),
        **extra,
    )


def save_injuries(pg, match, rows, **kwargs):
    return _process_fixture_injuries(
        pg,
        match,
        900,
        rows,
        {"Home": match["home_team_id"], "Away": match["away_team_id"]},
        "2026-10-18T23:30:00",
        **kwargs,
    )


def counts(pg, match):
    with pg.cursor() as q:
        q.execute(
            "SELECT (SELECT count(*) FROM match_lineup_snapshots WHERE match_id=%s),(SELECT count(*) FROM match_lineup_players p JOIN match_lineup_snapshots l ON l.id=p.lineup_snapshot_id WHERE l.match_id=%s),(SELECT count(*) FROM observation_streams WHERE match_id=%s),(SELECT count(*) FROM player_availability_snapshots WHERE raw_json->>'official_match_id'=%s),(SELECT count(*) FROM team_squad_snapshots WHERE raw_json->>'official_match_id'=%s)",
            (match["id"], match["id"], match["id"], str(match["id"]), str(match["id"])),
        )
        return q.fetchone()


def test_confirmed_lineup_updates_whole_projection_and_preserves_old_cutoff(pg, match):
    first = save_lineup(pg, match)
    cutoff = freeze(pg, match)
    second = save_lineup(pg, match, lineup(2))
    assert first == second
    assert counts(pg, match)[:2] == (1, 12)
    assert read(pg, match, "lineup", cutoff)["value"]["players"][0]["source_player_id"] == 1
    assert read(pg, match, "lineup")["value"]["players"][0]["source_player_id"] == 2
    assert read(pg, match, "lineup")["revision"] == 2
    assert (
        get_lineup_for_match(pg, match["id"], match["home_team_id"])["lineup_type"] == "confirmed"
    )


def test_same_roster_refresh_does_not_create_new_revision_or_duplicate_players(pg, match):
    save_lineup(pg, match)
    before = read(pg, match, "lineup")
    save_lineup(pg, match)
    after = read(pg, match, "lineup")
    assert before["revision_id"] == after["revision_id"]
    assert after["latest_check_id"] > before["latest_check_id"]
    assert counts(pg, match)[:2] == (1, 12)


@pytest.mark.parametrize("stage", ["player", "header", "detail", "observation"])
def test_lineup_failures_rollback_every_stage_including_new_players(pg, match, stage):
    target = {
        "player": "scripts.api_football_player.store_player",
        "header": "scripts.player_observations.store_match_lineup_snapshot",
        "detail": "scripts.player_observations.store_match_lineup_player",
        "observation": "scripts.player_observations.append_observation",
    }[stage]
    baseline = counts(pg, match)
    with patch(target, side_effect=RuntimeError("fixed failure")):
        with pytest.raises(RuntimeError, match="fixed failure"):
            save_lineup(pg, match, lineup(10000))
    assert counts(pg, match) == baseline
    with pg.cursor() as q:
        q.execute("SELECT count(*) FROM players WHERE player_code='apifootball:10000'")
        assert q.fetchone() == (0,)


def test_partial_lineup_is_unknown_and_does_not_publish_confirmed_projection(pg, match):
    data = lineup()
    data["startXI"] = data["startXI"][:3]
    assert save_lineup(pg, match, data) is None
    assert counts(pg, match)[:2] == (0, 0)
    assert read(pg, match, "lineup")["fact_status"] == "unknown"


def test_complete_lineup_is_invisible_until_final_commit(pg, connect, match):
    real_commit = pg.commit

    class DeferredCommit:
        def __getattr__(self, name):
            return getattr(pg, name)

        def commit(self):
            pass

    save_lineup(DeferredCommit(), match)
    with closing(connect()) as other:
        assert get_lineup_for_match(other, match["id"], match["home_team_id"]) is None
        with other.cursor() as q:
            q.execute("SELECT count(*) FROM observation_streams WHERE match_id=%s", (match["id"],))
            assert q.fetchone() == (0,)
    real_commit()
    assert get_lineup_for_match(pg, match["id"], match["home_team_id"]) is not None


def test_unverified_empty_injury_query_is_unknown_not_zero_coverage(pg, match):
    save_injuries(pg, match, [])
    for away in (False, True):
        assert read(pg, match, "injuries", away=away)["fact_status"] == "unknown"
    assert get_injury_observation_for_match(pg, match["id"], match["home_team_id"]) is None
    assert get_injuries_for_match(pg, match["id"], match["home_team_id"]) == []


def test_coverage_evidence_can_confirm_absence_without_fabricated_player(pg, match):
    save_injuries(pg, match, [], coverage_evidence="fixed-fixture-coverage/v1")
    assert read(pg, match, "injuries")["fact_status"] == "confirmed_absent"
    assert read(pg, match, "injuries")["value"] is None
    assert (
        get_injury_observation_for_match(pg, match["id"], match["home_team_id"])[
            "injured_players_count"
        ]
        == 0
    )


def test_corrected_injuries_replace_only_current_projection_and_keep_history(pg, match):
    save_injuries(pg, match, [injury(101)])
    cutoff = freeze(pg, match)
    save_injuries(pg, match, [], coverage_evidence="fixed-fixture-coverage/v1")
    assert get_injuries_for_match(pg, match["id"], match["home_team_id"]) == []
    assert read(pg, match, "injuries", cutoff)["value"]["players"][0]["source_player_id"] == 101
    assert read(pg, match, "injuries")["fact_status"] == "confirmed_absent"


@pytest.mark.parametrize("stage", ["player", "coverage", "detail", "observation"])
def test_injury_failures_never_leave_partial_coverage(pg, match, stage):
    target = {
        "player": "scripts.api_football_player.store_player",
        "coverage": "scripts.player_observations.store_team_squad_snapshot",
        "detail": "scripts.player_observations.store_player_availability_snapshot",
        "observation": "scripts.player_observations.append_observation",
    }[stage]
    baseline = counts(pg, match)
    with patch(target, side_effect=RuntimeError("fixed failure")):
        with pytest.raises(RuntimeError, match="fixed failure"):
            save_injuries(pg, match, [injury(20000)])
    assert counts(pg, match) == baseline
    assert get_injury_observation_for_match(pg, match["id"], match["home_team_id"]) is None


@pytest.mark.parametrize(
    "rows",
    [
        [injury(team="Unmapped")],
        [injury(1), injury(1)],
        [dict(player=dict(name="No ID"), team=dict(name="Home"))],
        [dict(injury(), fixture=dict(id=901))],
    ],
)
def test_malformed_or_unmatched_injuries_do_not_create_false_coverage(pg, match, rows):
    with pytest.raises(ValueError):
        save_injuries(pg, match, rows)
    assert counts(pg, match) == (0, 0, 0, 0, 0)


def test_failure_receipt_preserves_last_fact_and_never_creates_zero(pg, match):
    save_injuries(pg, match, [injury(333)])
    before = read(pg, match, "injuries")
    record_player_acquisition_failure(
        pg,
        match_id=match["id"],
        team_ids=[match["home_team_id"], match["away_team_id"]],
        domain="injuries",
        status=AcquisitionStatus.QUOTA_EXHAUSTED,
        acquired_at=datetime.now(UTC),
    )
    pg.commit()
    after = read(pg, match, "injuries")
    assert after["revision_id"] == before["revision_id"]
    assert after["acquisition_status"] == "quota_exhausted"
    assert get_injuries_for_match(pg, match["id"], match["home_team_id"])[0]["player_id"]


def test_freshness_check_is_bounded_and_old_projections_cannot_skip_new_observations(pg, match):
    args = dict(
        match_id=match["id"],
        team_ids=[match["home_team_id"], match["away_team_id"]],
        domain="injuries",
    )
    assert has_fresh_team_checks(pg, **args) is False
    save_injuries(pg, match, [])
    assert has_fresh_team_checks(pg, **args) is True
    old = datetime.now(UTC) - timedelta(hours=1)
    save_injuries(pg, match, [], acquired_at=old)
    assert has_fresh_team_checks(pg, **args) is False


@pytest.mark.parametrize("domain", ["lineup", "injuries"])
def test_midstream_failure_rolls_back_preceding_detail_and_receipt_writes(pg, match, domain):
    import scripts.player_observations as adapter

    baseline = counts(pg, match)
    name = "store_match_lineup_player" if domain == "lineup" else "store_team_squad_snapshot"
    original = getattr(adapter, name)
    seen = 0

    def later_failure(*args, **kwargs):
        nonlocal seen
        seen += 1
        if seen == 2:
            raise RuntimeError("second write failed")
        return original(*args, **kwargs)

    with patch.object(adapter, name, side_effect=later_failure):
        with pytest.raises(RuntimeError, match="second write"):
            if domain == "lineup":
                save_lineup(pg, match, lineup(30000))
            else:
                save_injuries(
                    pg, match, [injury(30000)], coverage_evidence="fixed-fixture-coverage/v1"
                )
    assert seen == 2
    assert counts(pg, match) == baseline


def test_concurrent_first_rosters_share_new_player_identity_and_exact_details(pg, connect, match):
    from concurrent.futures import ThreadPoolExecutor

    first_source_id = 100000000 + int(uuid4().hex[:7], 16)

    def publish(_):
        with closing(connect()) as conn:
            return save_lineup(conn, match, lineup(first_source_id))

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(publish, range(2)))
    assert ids[0] == ids[1]
    assert counts(pg, match)[:2] == (1, 12)
    assert read(pg, match, "lineup")["revision"] == 1


def test_restricted_projection_writer_can_publish_and_reader_cannot(pg, connect, match):
    with pg.cursor() as q:
        q.execute("SET ROLE fqp_player_writer")
    save_lineup(pg, match, lineup(50000))
    save_injuries(pg, match, [injury(50000)])
    assert read(pg, match, "injuries")["value"]["players"]
    with closing(connect()) as other:
        with other.cursor() as q:
            q.execute("SET ROLE fqp_observation_reader")
        with pytest.raises(Exception, match="permission denied"):
            save_lineup(other, match, lineup(60000))


def test_aware_snapshot_clock_converts_to_existing_beijing_naive_contract(pg, match):
    from scripts.jobs.collect_lineup_data import _process_lineup

    at = datetime(2026, 10, 18, 15, 30, tzinfo=UTC)
    _process_lineup(pg, match["id"], lineup(), match["home_team_id"], at, api_fixture_id=900)
    with pg.cursor() as q:
        q.execute(
            "SELECT snapshot_time FROM match_lineup_snapshots WHERE match_id=%s", (match["id"],)
        )
        assert q.fetchone() == (datetime(2026, 10, 18, 23, 30),)


def test_one_cutoff_can_bind_exact_lineup_and_injury_evidence_to_complete_batch(pg, match):
    from scripts.feature_batch_storage import load_feature_batch, store_feature_batch

    save_lineup(pg, match)
    save_injuries(pg, match, [injury(777)])
    cut = freeze(pg, match)
    features = {
        "home_lineup_confirmed": dict(fact_status="value", value=True, observation_indexes=[0]),
        "home_key_absence_count": dict(fact_status="unknown", value=None, observation_indexes=[2]),
    }
    bid = store_feature_batch(
        pg,
        match_id=match["id"],
        cutoff=cut,
        builder_version="fixed-player-proof/v1",
        required_fields=list(features),
        features=features,
    )
    pg.commit()
    loaded = load_feature_batch(pg, bid)
    assert loaded["cutoff"] == cut
    assert loaded["observations"][0]["revision_id"] == read(pg, match, "lineup", cut)["revision_id"]
    assert (
        loaded["observations"][2]["revision_id"] == read(pg, match, "injuries", cut)["revision_id"]
    )
    assert loaded["features"]["home_key_absence_count"]["value"] is None


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("quota", "quota_exhausted"),
        ("daily_budget", "quota_exhausted"),
        ("plan_denied", "forbidden"),
        ("invalid_response", "unavailable"),
        ("store", "unavailable"),
        ("runtime", "failed"),
    ],
)
def test_real_failure_receipt_translation_never_persists_raw_exception(pg, match, kind, expected):
    from scripts.api_football_client import ApiFootballRateLimitError
    from scripts.player_observations import record_failed_player_query
    from scripts.request_quota import QuotaDenied, QuotaUnavailable
    from scripts.request_transport import ProviderRequestError

    error = (
        ApiFootballRateLimitError("fixture-sentinel-private")
        if kind == "quota"
        else QuotaDenied(kind)
        if kind == "daily_budget"
        else QuotaUnavailable("fixture-sentinel-private")
        if kind == "store"
        else RuntimeError("fixture-sentinel-private")
        if kind == "runtime"
        else ProviderRequestError(kind)
    )
    assert record_failed_player_query(pg, match=match, domain="injuries", error=error)
    loaded = read(pg, match, "injuries")
    assert loaded["acquisition_status"] == expected
    assert loaded["fact_status"] == "unknown" and loaded["value"] is None
    assert "fixture-sentinel-private" not in str(loaded)
