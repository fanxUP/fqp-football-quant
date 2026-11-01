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


def head_document(*, mid=101, season=11817, league=72, uniform_match=5001):
    body = json.dumps(
        dict(
            success=True,
            errorCode="0",
            value=dict(
                sportteryMatchId=mid,
                seasonId=season,
                uniformLeagueId=league,
                uniformMatchId=uniform_match,
            ),
        )
    )
    return dict(
        url=f"https://webapi.sporttery.cn/gateway/uniform/football/getMatchHeadV1.qry?source=web&sportteryMatchId={mid}",
        captured_at="2026-11-01T00:00:00Z",
        sha256=hashlib.sha256(body.encode()).hexdigest(),
        body=body,
    )


def test_head_explicit_membership_with_boundary_without_echo():
    data = material()
    boundary = data["boundary_document"]
    payload = json.loads(boundary["body"])
    del payload["value"]["seasonId"], payload["value"]["uniformLeagueId"]
    boundary["body"] = json.dumps(payload)
    boundary["sha256"] = hashlib.sha256(boundary["body"].encode()).hexdigest()
    data["member_documents"] = [head_document()]
    original = copy.deepcopy(data)
    plan = prepare_import(data)
    assert plan["evidence"]["binding_basis"] == "request_parameters_only"
    proof = plan["members"][0]["evidence"]
    assert proof["sporttery_match_id"] == "101"
    assert proof["uniform_match_id"] == "5001"
    assert proof["binding_basis"] == "explicit_match_head"
    assert proof["historical_prematch_eligible"] is False
    assert "gm_match_id" not in proof
    assert data == original


@pytest.mark.parametrize(
    "kind",
    [
        "wrong_season",
        "wrong_league",
        "wrong_match",
        "missing_match",
        "missing_uniform",
        "missing_season",
        "duplicate_query",
        "missing_source",
        "wrong_source",
        "bad_host",
        "bad_hash",
        "naive_capture",
        "failed",
        "boundary_head",
        "missing_proof",
    ],
)
def test_invalid_head_never_promotes_membership(kind):
    data = material()
    doc = head_document()
    data["member_documents"] = [doc]
    payload = json.loads(doc["body"])
    if kind in ("wrong_season", "wrong_league", "wrong_match"):
        field = {
            "wrong_season": "seasonId",
            "wrong_league": "uniformLeagueId",
            "wrong_match": "sportteryMatchId",
        }[kind]
        payload["value"][field] = 999
    elif kind.startswith("missing_") and kind not in ("missing_source", "missing_proof"):
        field = {
            "missing_match": "sportteryMatchId",
            "missing_uniform": "uniformMatchId",
            "missing_season": "seasonId",
        }[kind]
        del payload["value"][field]
    elif kind == "duplicate_query":
        doc["url"] += "&sportteryMatchId=101"
    elif kind == "missing_source":
        doc["url"] = doc["url"].replace("source=web&", "")
    elif kind == "wrong_source":
        doc["url"] = doc["url"].replace("source=web", "source=other")
    elif kind == "bad_host":
        doc["url"] = doc["url"].replace("webapi.sporttery.cn", "evil.invalid")
    elif kind == "naive_capture":
        doc["captured_at"] = "2026-11-01T00:00:00"
    elif kind == "failed":
        payload["success"] = False
    elif kind == "boundary_head":
        data["boundary_document"] = doc
    elif kind == "missing_proof":
        data["members"][0]["jc_match_id"] = "102"
    doc["body"] = json.dumps(payload)
    doc["sha256"] = hashlib.sha256(doc["body"].encode()).hexdigest()
    if kind == "bad_hash":
        doc["body"] += " "
    with pytest.raises(ValueError):
        prepare_import(data)


def test_mixed_head_and_league_documents_preserve_each_evidence_kind():
    data = material()
    data["member_documents"] = [document(), head_document(mid=102)]
    data["members"].append(dict(fixture_id=2, jc_match_id="102"))
    proofs = {r["jc_match_id"]: r["evidence"] for r in prepare_import(data)["members"]}
    assert proofs["101"]["gm_match_id"] == "101"
    assert proofs["102"]["sporttery_match_id"] == "102"


@pytest.mark.parametrize("head_first", [False, True])
def test_head_proof_is_preserved_in_mixed_documents_regardless_of_order(head_first):
    data = material()
    docs = [document(), head_document()]
    data["member_documents"] = list(reversed(docs)) if head_first else docs
    proof = prepare_import(data)["members"][0]["evidence"]
    assert proof["binding_basis"] == "explicit_match_head"
    assert proof["uniform_match_id"] == "5001"


@pytest.mark.parametrize("second_uniform", [5001, 5002])
def test_all_head_identities_for_same_jc_must_agree(second_uniform):
    data = material()
    data["member_documents"] = [head_document(), head_document(uniform_match=second_uniform)]
    if second_uniform == 5002:
        with pytest.raises(ValueError, match="Conflicting official head uniform"):
            prepare_import(data)
    else:
        assert prepare_import(data)["members"][0]["evidence"]["uniform_match_id"] == "5001"


@pytest.mark.parametrize("second_uniform", [5001, 5002])
def test_selected_distinct_fixtures_cannot_share_one_head_uniform_identity(second_uniform):
    data = material()
    data["member_documents"] = [
        head_document(),
        head_document(mid=102, uniform_match=second_uniform),
    ]
    data["members"].append(dict(fixture_id=2, jc_match_id="102"))
    if second_uniform == 5001:
        with pytest.raises(ValueError, match="Selected head uniform identity"):
            prepare_import(data)
    else:
        assert len(prepare_import(data)["members"]) == 2


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
