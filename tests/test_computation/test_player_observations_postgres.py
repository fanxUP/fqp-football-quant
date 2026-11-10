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
from scripts.player_appearance_facts import build_actual_appearance_facts
from scripts.player_identity_bridge import (
    resolve_player_identity,
    resolve_verified_player_identity,
    upsert_player_identity_link,
)
from scripts.player_observations import (
    has_fresh_team_checks,
    record_player_acquisition_failure,
    store_actual_appearance_observations,
    store_lineup_observation,
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


def _appearance_source_player(source_player_id, minutes, name="Shared Name"):
    games = {} if minutes == "missing" else {"minutes": minutes}
    return {"player": {"id": source_player_id, "name": name}, "statistics": [{"games": games}]}


def _appearance_fixture_payload(match, *, fixture_id, home_api_id, away_api_id, home, away):
    summary = {
        "fixture": {
            "id": fixture_id,
            "status": {"short": "FT", "elapsed": 90, "extra": None},
        },
        "teams": {"home": {"id": home_api_id}, "away": {"id": away_api_id}},
    }
    response = [
        {"team": {"id": home_api_id}, "players": home},
        {"team": {"id": away_api_id}, "players": away},
    ]
    binding = {
        "match_id": match["id"],
        "api_fixture_id": fixture_id,
        "fixture_link_status": "linked",
        "home_team_id": match["home_team_id"],
        "away_team_id": match["away_team_id"],
        "api_home_team_id": home_api_id,
        "api_away_team_id": away_api_id,
    }
    return binding, summary, response


def _verified_appearance_player(pg, source_player_id):
    tag = uuid4().hex
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO players(player_code) VALUES (%s) RETURNING id", ("p108-04-" + tag,)
        )
        canonical_id = cur.fetchone()[0]
    upsert_player_identity_link(
        pg,
        source_name="apifootball",
        external_player_id=str(source_player_id),
        player_id=canonical_id,
        status="verified",
        evidence_refs=["fixed-response/P108-04/" + tag],
        matching_method="fixed_fixture_test",
        confidence=1,
        reviewed_by="fixed-test-reviewer",
        reviewed_at=datetime.now(UTC),
    )
    return canonical_id


def _appearance_facts(pg, match, *, fixture_id, home_api_id, away_api_id, home, away):
    binding, summary, response = _appearance_fixture_payload(
        match,
        fixture_id=fixture_id,
        home_api_id=home_api_id,
        away_api_id=away_api_id,
        home=home,
        away=away,
    )
    return build_actual_appearance_facts(
        official_match=binding,
        fixture_summary=summary,
        fixture_players=response,
        resolve_player_id=lambda external_id: resolve_verified_player_identity(
            pg, "apifootball", external_id
        ),
        acquired_at=datetime.now(UTC),
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


def injury_receipt_counts(pg, match_id):
    with pg.cursor() as q:
        q.execute(
            "SELECT team_id, count(*) FROM team_squad_snapshots "
            "WHERE raw_json->>'official_match_id'=%s "
            "AND raw_json->>'observation_type'='fixture_injuries' "
            "GROUP BY team_id",
            (str(match_id),),
        )
        return dict(q.fetchall())


def test_confirmed_lineup_updates_whole_projection_and_preserves_old_cutoff(pg, match):
    first = save_lineup(pg, match)
    cutoff = freeze(pg, match)
    second = save_lineup(pg, match, lineup(2))
    assert first == second
    assert counts(pg, match)[:2] == (1, 12)
    assert read(pg, match, "lineup", cutoff)["value"]["players"][0]["source_player_id"] == 1
    assert read(pg, match, "lineup")["value"]["players"][0]["source_player_id"] == 2
    assert read(pg, match, "lineup")["revision"] == 2
    assert read(pg, match, "lineup")["value"]["lineup_status"] == "confirmed"
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


@pytest.mark.parametrize(
    ("lineup_status", "error"),
    [
        ("predicted", "only confirmed lineups"),
        ("unknown", "only confirmed lineups"),
        (None, "explicit supported status"),
    ],
)
def test_only_explicit_confirmed_lineup_can_enter_projection(pg, match, lineup_status, error):
    snapshot = dict(match_id=match["id"], team_id=match["home_team_id"])
    if lineup_status is not None:
        snapshot["lineup_type"] = lineup_status

    with pytest.raises(ValueError, match=error):
        store_lineup_observation(
            pg,
            snapshot,
            [],
            api_fixture_id=900,
            acquired_at=datetime.now(UTC),
        )

    assert counts(pg, match)[:3] == (0, 0, 0)


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


def test_injury_revision_preserves_explicit_status_and_source_dates(pg, match):
    row = injury(
        404,
        effective_at="2026-10-18T12:00:00+08:00",
        published_at="2026-10-19T08:30:00Z",
    )
    row["player"].update(
        type="Questionable",
        reason="Ankle",
        expected_return_date="2026-10-25",
    )

    save_injuries(pg, match, [row])
    fact = read(pg, match, "injuries")["value"]["players"][0]

    assert fact["availability_status"] == "doubtful"
    assert fact["effective_at"] == "2026-10-18T04:00:00+00:00"
    assert fact["published_at"] == "2026-10-19T08:30:00+00:00"
    assert fact["expected_return_date"] == "2026-10-25"


@pytest.mark.parametrize(
    ("reason", "expected_status"),
    [
        ("Suspended 3 matches", "suspended"),
        ("Knee Injury", "injured"),
        ("Personal Reasons", "unknown"),
    ],
)
def test_missing_fixture_reason_is_persisted_without_inventing_injury(
    pg, match, reason, expected_status
):
    row = injury(406)
    row["player"]["reason"] = reason

    save_injuries(pg, match, [row])

    fact = read(pg, match, "injuries")["value"]["players"][0]
    assert fact["availability_status"] == expected_status


def test_repeated_injury_payload_preserves_revision_and_appends_legacy_receipts(pg, match):
    row = injury(407)
    save_injuries(pg, match, [row])
    before = read(pg, match, "injuries")
    before_counts = counts(pg, match)
    before_receipts = injury_receipt_counts(pg, match["id"])

    save_injuries(pg, match, [row])

    after = read(pg, match, "injuries")
    assert after["revision_id"] == before["revision_id"]
    assert after["revision"] == before["revision"]
    assert after["latest_check_id"] > before["latest_check_id"]
    after_counts = counts(pg, match)
    assert after_counts[:4] == before_counts[:4]
    assert after_counts[4] == before_counts[4] + 2
    after_receipts = injury_receipt_counts(pg, match["id"])
    assert (
        set(after_receipts)
        == set(before_receipts)
        == {
            match["home_team_id"],
            match["away_team_id"],
        }
    )
    assert all(after_receipts[team_id] == count + 1 for team_id, count in before_receipts.items())


def test_injury_revision_keeps_unprovided_source_dates_null(pg, match):
    row = injury(405)
    row["updated_at"] = "2026-10-19T08:30:00Z"
    row["fixture"]["date"] = "2026-10-20T20:00:00+08:00"

    save_injuries(pg, match, [row])
    fact = read(pg, match, "injuries")["value"]["players"][0]

    assert fact["effective_at"] is None
    assert fact["published_at"] is None
    assert fact["expected_return_date"] is None


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


def _appearance_cutoff(pg, match):
    cutoff = capture_observation_cutoff(
        pg,
        streams=[
            team_stream(match["id"], team_id, "appearance")
            for team_id in (match["home_team_id"], match["away_team_id"])
        ],
    )
    pg.commit()
    return cutoff


def _appearance_read(pg, match, cutoff, *, away=False):
    team_id = match["away_team_id"] if away else match["home_team_id"]
    return load_observation_as_of(
        pg,
        **team_stream(match["id"], team_id, "appearance"),
        cutoff=cutoff,
    )


def test_actual_appearance_observations_preserve_provenance_zero_minutes_and_revisions(pg, match):
    home_source = 1_000_000 + uuid4().int % 7_000_000_000
    missing_source = home_source + 1
    away_source = home_source + 2
    unresolved_source = home_source + 3
    home_player = _verified_appearance_player(pg, home_source)
    _verified_appearance_player(pg, missing_source)
    away_player = _verified_appearance_player(pg, away_source)
    pg.commit()
    facts = _appearance_facts(
        pg,
        match,
        fixture_id=900_000_000 + uuid4().int % 7_000_000_000,
        home_api_id=10_000 + uuid4().int % 1_000_000,
        away_api_id=20_000 + uuid4().int % 1_000_000,
        home=[
            _appearance_source_player(home_source, 45),
            _appearance_source_player(missing_source, None),
            _appearance_source_player(unresolved_source, 20),
        ],
        away=[_appearance_source_player(away_source, 0)],
    )

    first_refs = store_actual_appearance_observations(pg, facts)
    pg.commit()
    before = _appearance_cutoff(pg, match)
    home = _appearance_read(pg, match, before)
    away = _appearance_read(pg, match, before, away=True)

    assert home["fact_status"] == "value"
    assert home["value"]["team_id"] == match["home_team_id"]
    assert home["value"]["api_fixture_id"] == facts["api_fixture_id"]
    assert home["evidence"]["api_team_id"] == facts["teams"][0]["api_team_id"]
    assert home["value"]["players"] == [
        {
            "source_player_id": str(home_source),
            "player_id": home_player,
            "minutes": 45,
            "source_reported": True,
            "derivation": "direct_source_field",
        }
    ]
    assert home["value"]["missing_minutes_count"] == 1
    assert home["evidence"]["unresolved_player_count"] == 1
    assert home["evidence"]["unresolved_source_player_ids"] == [str(unresolved_source)]
    assert home["evidence"]["source_response_sha256"] == facts["source_response_sha256"]
    assert home["first_acquired_at"] == datetime.fromisoformat(facts["acquired_at"])
    assert away["fact_status"] == "value"
    assert away["value"]["players"][0]["player_id"] == away_player
    assert away["value"]["players"][0]["minutes"] == 0
    assert away["evidence"]["derivation"] == "direct_source_field"

    repeated_refs = store_actual_appearance_observations(pg, facts)
    pg.commit()
    repeated = _appearance_cutoff(pg, match)
    repeated_home = _appearance_read(pg, match, repeated)
    repeated_away = _appearance_read(pg, match, repeated, away=True)
    assert repeated_home["revision_id"] == home["revision_id"]
    assert repeated_away["revision_id"] == away["revision_id"]
    assert repeated_home["latest_check_id"] > home["latest_check_id"]
    assert repeated_refs["home"]["revision"] == first_refs["home"]["revision"]

    corrected = _appearance_facts(
        pg,
        match,
        fixture_id=facts["api_fixture_id"],
        home_api_id=facts["teams"][0]["api_team_id"],
        away_api_id=facts["teams"][1]["api_team_id"],
        home=[
            _appearance_source_player(home_source, 44),
            _appearance_source_player(missing_source, None),
            _appearance_source_player(unresolved_source, 20),
        ],
        away=[_appearance_source_player(away_source, 0)],
    )
    store_actual_appearance_observations(pg, corrected)
    pg.commit()
    current = _appearance_cutoff(pg, match)
    assert _appearance_read(pg, match, before)["value"]["players"][0]["minutes"] == 45
    assert _appearance_read(pg, match, current)["value"]["players"][0]["minutes"] == 44

    with pg.cursor() as cur:
        cur.execute(
            """SELECT count(*),count(*) FILTER (WHERE c.valid_until IS NULL)
                 FROM observation_checks c JOIN observation_streams s ON s.id=c.stream_id
                WHERE s.match_id=%s AND s.source_id='api_football' AND s.domain='appearance'""",
            (match["id"],),
        )
        total_checks, without_expiry = cur.fetchone()
    assert total_checks >= 6
    assert without_expiry == total_checks


def test_actual_appearance_identity_rejects_legacy_player_code_fallback(pg):
    source_player_id = 1_000_000 + uuid4().int % 7_000_000_000
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO players(player_code) VALUES (%s) RETURNING id",
            (f"apifootball:{source_player_id}",),
        )
        canonical_id = cur.fetchone()[0]
    pg.commit()

    assert resolve_player_identity(pg, "apifootball", str(source_player_id)) == canonical_id
    assert resolve_verified_player_identity(pg, "apifootball", str(source_player_id)) is None


def test_actual_appearance_writer_rejects_duplicate_canonical_player_across_teams(pg, match):
    home_source_id = 1_000_000 + uuid4().int % 7_000_000_000
    away_source_id = home_source_id + 1
    home_player_id = _verified_appearance_player(pg, home_source_id)
    _verified_appearance_player(pg, away_source_id)
    pg.commit()
    facts = _appearance_facts(
        pg,
        match,
        fixture_id=900_000_000 + uuid4().int % 7_000_000_000,
        home_api_id=10_000 + uuid4().int % 1_000_000,
        away_api_id=20_000 + uuid4().int % 1_000_000,
        home=[_appearance_source_player(home_source_id, 90)],
        away=[_appearance_source_player(away_source_id, 90)],
    )
    facts["teams"][1]["players"][0]["player_id"] = home_player_id
    with pytest.raises(ValueError, match="distinct canonical player ID"):
        store_actual_appearance_observations(pg, facts)


def test_empty_appearance_response_remains_unknown_not_confirmed_absent(pg, match):
    facts = _appearance_facts(
        pg,
        match,
        fixture_id=900_000_000 + uuid4().int % 7_000_000_000,
        home_api_id=10_000 + uuid4().int % 1_000_000,
        away_api_id=20_000 + uuid4().int % 1_000_000,
        home=[],
        away=[],
    )

    store_actual_appearance_observations(pg, facts)
    pg.commit()
    cutoff = _appearance_cutoff(pg, match)

    for away in (False, True):
        fact = _appearance_read(pg, match, cutoff, away=away)
        assert fact["fact_status"] == "unknown"
        assert fact["value"] is None
        assert fact["evidence"]["source_reported"] is True


def test_two_team_appearance_write_requires_caller_rollback_after_partial_failure(pg, match):
    facts = _appearance_facts(
        pg,
        match,
        fixture_id=900_000_000 + uuid4().int % 7_000_000_000,
        home_api_id=10_000 + uuid4().int % 1_000_000,
        away_api_id=20_000 + uuid4().int % 1_000_000,
        home=[],
        away=[],
    )
    from scripts import player_observations as adapter

    original_append = adapter.append_observation
    calls = 0

    def fail_second_append(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("fixed second-team failure")
        return original_append(*args, **kwargs)

    with patch("scripts.player_observations.append_observation", side_effect=fail_second_append):
        with pytest.raises(RuntimeError, match="fixed second-team failure"):
            store_actual_appearance_observations(pg, facts)
    pg.rollback()
    cutoff = _appearance_cutoff(pg, match)

    assert _appearance_read(pg, match, cutoff) is None
    assert _appearance_read(pg, match, cutoff, away=True) is None
