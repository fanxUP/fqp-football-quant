"""Archived official selection evidence must retain slot shape and precision."""

from datetime import UTC, datetime

import pytest

from scripts.football_pool_notice import parse_notice

URL = "https://m.lottery.gov.cn/xxgk/tzgg/zctz/20240402/10041560.html"
CAPTURED = datetime(2026, 10, 30, 10, 40, tzinfo=UTC)


def notice(kind="sf", *, merged=True):
    title = {
        "sf": "胜负游戏（14场和任选9场）",
        "bqc": "6场半全场胜负游戏",
        "jq": "4场进球游戏",
    }[kind]
    n = {"sf": 14, "bqc": 12, "jq": 8}[kind]
    headers = ["期号", "赛制", "序号"] + (
        ["球队名称", "比赛日期"] if kind == "jq" else ["主队", "客队", "比赛日期"]
    )
    rows = ["<tr>" + "".join(f"<td>{x}</td>" for x in headers) + "</tr>"]
    for i in range(n):
        row = "<tr>"
        if i == 0:
            row += f'<td rowspan="{n}">第24053期</td><td rowspan="{n}">英超</td>'
        row += f"<td>{i + 1}</td>"
        pair = i // 2
        if kind == "bqc" and merged:
            if i % 2 == 0:
                row += f'<td rowspan="2">H{pair}</td><td rowspan="2">A{pair}</td><td rowspan="2">2024-04-06</td>'
        elif kind == "jq":
            row += f"<td>T{i}</td>"
            if i % 2 == 0:
                row += '<td rowspan="2">2024-04-06</td>'
        else:
            row += f"<td>H{pair}</td><td>A{pair}</td><td>2024-04-06</td>"
        rows.append(row + "</tr>")
    rows.append(
        f'<tr><td colspan="{len(headers)}">开售时间：2024-04-03 20:00 '
        "停售时间：2024-04-06 21:00 开奖日期：2024-04-07</td></tr>"
    )
    return f"<p>附件1.足球彩票{title}第24053期</p><table>{''.join(rows)}</table>"


def parse(html):
    return parse_notice(html, source_url=URL, retrieved_at=CAPTURED)


def test_joint_official_heading_preserves_two_game_memberships_and_date_precision():
    result = parse(notice())
    assert [x["game_type"] for x in result["issues"]] == ["t14c", "r9"]
    for issue in result["issues"]:
        assert len(issue["matches"]) == 14
        assert issue["sale_stop"] == "2024-04-06T21:00:00+08:00"
        assert issue["matches"][0]["match_date"] == "2024-04-06"
        assert issue["matches"][0]["kickoff_time"] is None
        assert issue["matches"][0]["source_match_id"] is None
    assert result["ready_for_database_import"] is False
    assert result["final_revision_verified"] is False
    assert result["retrieved_at"] == CAPTURED.isoformat()


def test_half_full_uses_shared_source_cells_to_restore_six_matches():
    issue = parse(notice("bqc"))["issues"][0]
    assert issue["game_type"] == "bqc6"
    assert issue["source_slots"] == 12
    assert len(issue["matches"]) == 6
    assert issue["matches"][0]["source_slot_orders"] == [1, 2]
    assert issue["matches"][5]["home_team_name"] == "H5"


def test_goals_pairs_eight_team_slots_but_does_not_invent_home_away_orientation():
    issue = parse(notice("jq"))["issues"][0]
    assert issue["game_type"] == "jq4"
    assert len(issue["matches"]) == 4
    match = issue["matches"][0]
    assert match["team_names_in_source_order"] == ["T0", "T1"]
    assert match["home_team_name"] is None
    assert match["away_team_name"] is None
    assert match["orientation_status"] == "source_order_only"


def test_repeated_team_text_without_rowspan_is_not_proof_of_half_full_pairing():
    with pytest.raises(ValueError, match="paired cells"):
        parse(notice("bqc", merged=False))


@pytest.mark.parametrize("changed", ["<td>0</td>", "<td>2</td>", "<td>15</td>"])
def test_non_contiguous_or_duplicate_slots_are_rejected(changed):
    with pytest.raises(ValueError, match="slot orders"):
        parse(notice().replace("<td>1</td>", changed, 1))


def test_heading_issue_and_member_issue_must_agree():
    with pytest.raises(ValueError, match="issue mismatch"):
        parse(notice().replace('rowspan="14">第24053期', 'rowspan="14">第24054期'))


def test_non_official_domain_and_naive_capture_time_are_rejected():
    with pytest.raises(ValueError, match="official source"):
        parse_notice(
            notice(), source_url="https://lottery.gov.cn.example.com/x", retrieved_at=CAPTURED
        )
    with pytest.raises(ValueError, match="timezone"):
        parse_notice(notice(), source_url=URL, retrieved_at=CAPTURED.replace(tzinfo=None))


def test_conflicting_sale_window_is_not_accepted_as_valid_evidence():
    with pytest.raises(ValueError, match="sale window"):
        parse(notice().replace("停售时间：2024-04-06", "停售时间：2024-04-01"))


def test_repeated_material_is_deterministic_and_missing_cutoff_stays_unknown():
    html = notice().replace("停售时间：2024-04-06 21:00", "停售时间：待定")
    assert parse(html) == parse(html)
    assert parse(html)["issues"][0]["sale_stop"] is None


def test_wrong_date_or_truncated_members_are_rejected():
    with pytest.raises(ValueError):
        parse(notice().replace("2024-04-06", "2024-02-30"))
    with pytest.raises(ValueError, match="slot orders"):
        parse(notice().replace("<td>14</td>", "<td>待定</td>"))
