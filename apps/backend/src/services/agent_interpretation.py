"""Read-only server snapshots for manually triggered business interpretations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

InterpretationSourceType = Literal["pre_match", "post_daily", "post_weekly", "post_monthly"]


class InterpretationSourceError(ValueError):
    """Raised when an immutable business source cannot be prepared."""


@dataclass(frozen=True)
class InterpretationSource:
    source_type: InterpretationSourceType
    source_ref: str
    title: str
    agent_code: str
    prompt: str


def build_interpretation_prompt(
    source_type: str, title: str, snapshot: dict[str, Any], focus_question: str | None,
) -> str:
    labels = {
        "pre_match": "赛前单场解读",
        "post_daily": "赛后日报复盘",
        "post_weekly": "赛后周报复盘",
        "post_monthly": "赛后月报复盘",
    }
    if source_type not in labels:
        raise InterpretationSourceError("不支持的解读来源")
    question = focus_question.strip() if focus_question else ""
    material = json.dumps(snapshot, ensure_ascii=False, default=str, separators=(",", ":"))
    prompt = (
        f"任务：{labels[source_type]}\n标题：{title}\n"
        "以下为后端在本次点击时冻结的业务快照，只能据此解读；"
        "请区分事实、模型信号、不确定性和待人工核验项。不得给出投注指令。\n"
        f"业务快照：{material}"
    )
    if question:
        prompt += f"\n用户关注问题：{question}"
    prompt += "\n输出仅供人工核验，不会写入预测、推荐、风控或结算。"
    return prompt[:8_000]


def build_pre_match_source(conn: Any, match_id: int, focus_question: str | None) -> InterpretationSource:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id, official_match_code, league_name, home_team_name, away_team_name,
                      kickoff_time, match_status, sale_status
               FROM official_matches WHERE id = %s""", (match_id,),
        )
        match = cur.fetchone()
        if not match:
            raise InterpretationSourceError("官方比赛不存在")
        cur.execute(
            """SELECT DISTINCT ON (play_type, option_code) play_type, option_code, sp_value, handicap, snapshot_time
               FROM official_odds_snapshots WHERE match_id = %s AND is_open = true
               ORDER BY play_type, option_code, snapshot_time DESC, id DESC""", (match_id,),
        )
        odds = cur.fetchall()
        cur.execute(
            """SELECT DISTINCT ON (mv.model_name, mp.play_type, mp.option_code)
                      mv.model_name, mp.play_type, mp.option_code, mp.model_probability,
                      mp.market_probability, mp.fair_odds, mp.ev, mp.confidence_score, mp.predict_time
               FROM model_predictions mp JOIN model_versions mv ON mv.id = mp.model_version_id
               WHERE mp.match_id = %s AND mp.validation_status = 'valid' AND mp.predict_time < %s
               ORDER BY mv.model_name, mp.play_type, mp.option_code, mp.predict_time DESC, mp.id DESC""",
            (match_id, match[5]),
        )
        predictions = cur.fetchall()
    title = f"赛前解读：{match[1] or match_id} {match[3]} vs {match[4]}"
    snapshot = {
        "官方比赛": {"id": match[0], "编号": match[1], "联赛": match[2], "主队": match[3], "客队": match[4], "开赛时间": match[5], "状态": match[6], "销售状态": match[7]},
        "官方赔率": [{"玩法": row[0], "选项": row[1], "赔率": row[2], "让球": row[3], "快照时间": row[4]} for row in odds],
        "有效模型预测": [{"模型": row[0], "玩法": row[1], "选项": row[2], "模型概率": row[3], "市场概率": row[4], "公平赔率": row[5], "EV": row[6], "置信度": row[7], "预测时间": row[8]} for row in predictions],
    }
    return InterpretationSource("pre_match", str(match_id), title, "pre_match_interpretation_agent", build_interpretation_prompt("pre_match", title, snapshot, focus_question))


def build_post_match_source(
    conn: Any, source_type: InterpretationSourceType, source_ref: str, focus_question: str | None,
) -> InterpretationSource:
    tables = {
        "post_daily": ("daily_reviews", "review_date", "日报"),
        "post_weekly": ("weekly_reviews", "id", "周报"),
        "post_monthly": ("monthly_reviews", "id", "月报"),
    }
    if source_type not in tables:
        raise InterpretationSourceError("不支持的赛后复盘来源")
    table, key, label = tables[source_type]
    with conn.cursor() as cur:
        cur.execute(f"SELECT to_jsonb(review) FROM {table} review WHERE {key} = %s LIMIT 1", (source_ref,))
        row = cur.fetchone()
    if not row:
        raise InterpretationSourceError(f"{label}不存在")
    title = f"赛后复盘解读：{label} {source_ref}"
    return InterpretationSource(source_type, source_ref, title, "post_match_review_agent", build_interpretation_prompt(source_type, title, {label: row[0]}, focus_question))
