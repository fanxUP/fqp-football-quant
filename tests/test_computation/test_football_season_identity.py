"""Fixed offline official evidence; no network or database."""

import copy
import hashlib
import json

import pytest

from scripts.football_season_identity import prepare_import


def document(*, season=11817, league=72, members=(101,), dates=True):
    value = dict(seasonId=season, uniformLeagueId=league)
    if dates:
        value.update(seasonStartDate="2024-08-16", seasonEndDate="2025-05-26")
    value["matchList"] = [
        dict(matchDate="2025-06-01", subMatchList=[dict(gmMatchId=i) for i in members])
    ]
    body = json.dumps(dict(success=True, errorCode="0", value=value))
    return dict(
        url=f"https://webapi.sporttery.cn/gateway/uniform/football/league/getMatchResultV1.qry?uniformLeagueId={league}&seasonId={season}",
        captured_at="2026-10-30T12:00:00Z",
        sha256=hashlib.sha256(body.encode()).hexdigest(),
        body=body,
    )


def material():
    return dict(
        competition_code="premier-league",
        season_code="premier-league:2024-2025",
        season_name="2024-2025",
        boundary_document=document(members=()),
        member_documents=[document()],
        members=[dict(fixture_id=1, jc_match_id="101")],
    )


def test_explicit_member_outside_planned_dates_is_retained():
    plan = prepare_import(material())
    assert plan["planned_end_date"] == "2025-05-26"
    assert plan["source_season_id"] == "11817"
    assert plan["members"][0]["jc_match_id"] == "101"
    assert plan["members"][0]["evidence"]["historical_prematch_eligible"] is False


def test_boundary_only_never_creates_members():
    data = material()
    data.update(members=[], member_documents=[])
    assert prepare_import(data)["members"] == []


def test_old_boundary_without_echo_ids_is_planning_evidence_only():
    data = material()
    data.update(members=[], member_documents=[])
    doc = data["boundary_document"]
    payload = json.loads(doc["body"])
    del payload["value"]["seasonId"], payload["value"]["uniformLeagueId"]
    doc["body"] = json.dumps(payload)
    doc["sha256"] = hashlib.sha256(doc["body"].encode()).hexdigest()
    plan = prepare_import(data)
    assert plan["evidence"]["binding_basis"] == "request_parameters_only"
    assert all(v is None for v in plan["evidence"]["response_id_echo"].values())
    data["member_documents"] = [doc]
    data["members"] = [dict(fixture_id=1, jc_match_id="101")]
    with pytest.raises(ValueError):
        prepare_import(data)


@pytest.mark.parametrize("kind", ["hash", "host", "endpoint", "query", "clock", "failed"])
def test_invalid_source_refused(kind):
    data = material()
    doc = data["boundary_document"]
    if kind == "hash":
        doc["body"] += " "
    elif kind == "host":
        doc["url"] = doc["url"].replace("webapi.sporttery.cn", "evil.invalid")
    elif kind == "endpoint":
        doc["url"] = doc["url"].replace("getMatchResultV1", "getUniformMatchResultV1")
    elif kind == "query":
        doc["url"] += "&seasonId=999"
    elif kind == "clock":
        doc["captured_at"] = "2024-08-16T00:00:00"
    else:
        payload = json.loads(doc["body"])
        payload["success"] = False
        doc["body"] = json.dumps(payload)
        doc["sha256"] = hashlib.sha256(doc["body"].encode()).hexdigest()
    with pytest.raises(ValueError):
        prepare_import(data)


@pytest.mark.parametrize(
    "change", ["other_season", "other_league", "missing", "duplicate", "legacy_code"]
)
def test_no_date_or_name_inference(change):
    data = material()
    if change == "other_season":
        data["member_documents"] = [document(season=13343)]
    elif change == "other_league":
        data["member_documents"] = [document(league=99)]
    elif change == "missing":
        data["members"][0]["jc_match_id"] = "102"
    elif change == "duplicate":
        data["members"].append(copy.deepcopy(data["members"][0]))
    else:
        data["season_code"] = "2024"
    with pytest.raises(ValueError):
        prepare_import(data)


def test_input_is_not_rewritten():
    data = material()
    original = copy.deepcopy(data)
    prepare_import(data)
    assert data == original


def test_default_cli_preview_never_connects(tmp_path, monkeypatch, capsys):
    from scripts.football_season_identity import main

    path = tmp_path / "input.json"
    path.write_text(json.dumps(material()))
    monkeypatch.delenv("DATABASE_URL", raising=False)

    def reject_connection(*args, **kwargs):
        raise AssertionError("offline preview attempted database access")

    monkeypatch.setattr("scripts.football_season_identity.psycopg2.connect", reject_connection)
    assert main(["--input", str(path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "offline_preview"
    assert result["database_access"] is False
