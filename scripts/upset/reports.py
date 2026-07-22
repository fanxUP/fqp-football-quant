"""Cold-result daily, weekly, and monthly report generation."""

from __future__ import annotations

import html
from datetime import date
from pathlib import Path
from typing import Any

from psycopg2.extras import Json, RealDictCursor

REPORT_VERSION = "upset-report-v1"


def validate_period(start: str | date, end: str | date) -> tuple[str, str]:
    start_date = date.fromisoformat(str(start))
    end_date = date.fromisoformat(str(end))
    if start_date > end_date:
        raise ValueError("报告开始日期不能晚于结束日期")
    return start_date.isoformat(), end_date.isoformat()


def _money(value: Any) -> str:
    return f"¥{float(value or 0):.2f}"


def _percent(value: Any) -> str:
    return f"{float(value or 0):.1%}"


def render_markdown(
    report_type: str,
    start: str,
    end: str,
    metrics: dict[str, Any],
) -> str:
    """Render one source-backed report while keeping both bankrolls separate."""
    labels = {"daily": "日报", "weekly": "周报", "monthly": "月报"}
    upset = metrics["upsets"]
    user = metrics["user"]
    agent = metrics["agent"]
    cold = metrics["cold_impact"]
    quality = metrics["model_quality"]
    league_lines = "\n".join(
        f"- {row['league']}：{row['count']}场" for row in metrics["by_league"]
    ) or "- 暂无"
    level_lines = "、".join(f"{key}级 {value}" for key, value in metrics["by_level"].items())
    play_lines = "、".join(f"{key.upper()} {value}" for key, value in metrics["by_play"].items())
    return f"""# 冷门研究{labels.get(report_type, '报告')}（{start} 至 {end}）

## 冷门概况

- 冷门事件：{upset['count']}场
- S/A级：{upset['severe_count']}场
- 已结算比赛冷门率：{_percent(upset['rate'])}
- 等级分布：{level_lines or '暂无'}
- 玩法分布：{play_lines or '暂无'}

## 用户实票

- 投入：{_money(user['stake'])}
- 返还：{_money(user['prize'])}
- 盈亏：{_money(user['profit'])}
- ROI：{_percent(user['roi'])}
- 冷门相关盈亏：{_money(cold['user_profit'])}

## Agent虚拟投注

- 投入：{_money(agent['stake'])}
- 返还：{_money(agent['prize'])}
- 盈亏：{_money(agent['profit'])}
- ROI：{_percent(agent['roi'])}
- 冷门相关盈亏：{_money(cold['agent_profit'])}

## 联赛分布

{league_lines}

## 模型质量

- 有效样本：{quality['sample_size']}
- Brier：{quality['brier'] if quality['brier'] is not None else '暂无'}
- Log Loss：{quality['log_loss'] if quality['log_loss'] is not None else '暂无'}

> 用户实票与Agent虚拟资金严格分开统计；盈亏按整张彩票结算，不把串关中的单项命中计作盈利。
"""


def render_html(markdown: str) -> str:
    """Create a dependency-free readable HTML version from report Markdown."""
    lines = []
    for raw in markdown.splitlines():
        escaped = html.escape(raw)
        if raw.startswith("# "):
            lines.append(f"<h1>{html.escape(raw[2:])}</h1>")
        elif raw.startswith("## "):
            lines.append(f"<h2>{html.escape(raw[3:])}</h2>")
        elif raw.startswith("- "):
            lines.append(f"<p>• {html.escape(raw[2:])}</p>")
        elif raw.startswith("> "):
            lines.append(f"<blockquote>{html.escape(raw[2:])}</blockquote>")
        elif raw:
            lines.append(f"<p>{escaped}</p>")
    return "<!doctype html><meta charset='utf-8'><body>" + "\n".join(lines) + "</body>"


def _settlement_metrics(conn: Any, start: str, end: str) -> dict[str, dict[str, float]]:
    result = {
        "real": {"stake": 0.0, "prize": 0.0, "profit": 0.0, "roi": 0.0},
        "simulation": {"stake": 0.0, "prize": 0.0, "profit": 0.0, "roi": 0.0},
    }
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ticket_source, COALESCE(SUM(stake_amount), 0),
                   COALESCE(SUM(prize_amount), 0), COALESCE(SUM(profit_loss), 0)
            FROM ticket_settlements
            WHERE (settle_time AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai')::date
                  BETWEEN %s AND %s
            GROUP BY ticket_source
            """,
            (start, end),
        )
        for source, stake, prize, profit in cur.fetchall():
            if source not in result:
                continue
            values = result[source]
            values.update(stake=float(stake), prize=float(prize), profit=float(profit))
            values["roi"] = values["profit"] / values["stake"] if values["stake"] else 0.0
    return result


def build_report_metrics(conn: Any, start: str, end: str) -> dict[str, Any]:
    start, end = validate_period(start, end)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            WITH settled AS (
                SELECT COUNT(*) AS count
                FROM official_matches match
                JOIN official_results result ON result.match_id = match.id
                WHERE match.business_date BETWEEN %s AND %s
                  AND result.result_status IN ('final', 'confirmed')
            )
            SELECT COUNT(event.id) AS count,
                   COUNT(event.id) FILTER (WHERE event.upset_level IN ('S', 'A'))
                       AS severe_count,
                   CASE WHEN settled.count > 0
                        THEN COUNT(event.id)::numeric / settled.count ELSE 0 END AS rate
            FROM settled
            LEFT JOIN upset_events event ON event.business_date BETWEEN %s AND %s
            GROUP BY settled.count
            """,
            (start, end, start, end),
        )
        upsets = dict(cur.fetchone())
        cur.execute(
            """SELECT COALESCE(upset_level, '热门未出') AS key, COUNT(*) AS count
               FROM upset_events WHERE business_date BETWEEN %s AND %s
               GROUP BY key ORDER BY key""",
            (start, end),
        )
        by_level = {row["key"]: int(row["count"]) for row in cur.fetchall()}
        cur.execute(
            """SELECT primary_play_type AS key, COUNT(*) AS count
               FROM upset_events WHERE business_date BETWEEN %s AND %s
               GROUP BY key ORDER BY count DESC""",
            (start, end),
        )
        by_play = {row["key"]: int(row["count"]) for row in cur.fetchall()}
        cur.execute(
            """SELECT match.league_name AS league, COUNT(*) AS count
               FROM upset_events event JOIN official_matches match ON match.id=event.match_id
               WHERE event.business_date BETWEEN %s AND %s
               GROUP BY match.league_name ORDER BY count DESC, match.league_name LIMIT 10""",
            (start, end),
        )
        by_league = [dict(row) for row in cur.fetchall()]
        cur.execute(
            """SELECT COUNT(*) FILTER (WHERE brier_score IS NOT NULL) AS sample_size,
                      AVG(brier_score) AS brier, AVG(log_loss) AS log_loss
               FROM market_efficiency_metrics metric
               JOIN official_matches match ON match.id = metric.match_id
               WHERE match.business_date BETWEEN %s AND %s""",
            (start, end),
        )
        quality = dict(cur.fetchone())
        cur.execute(
            """
            SELECT source, COALESCE(SUM(profit_loss), 0) AS profit
            FROM (
                SELECT settlement.ticket_source AS source, settlement.profit_loss
                FROM ticket_settlements settlement
                WHERE settlement.ticket_source = 'real'
                  AND EXISTS (
                    SELECT 1 FROM real_ticket_items item
                    JOIN upset_events event ON event.match_id = item.match_id
                    WHERE item.real_ticket_id = settlement.ticket_id
                      AND event.business_date BETWEEN %s AND %s)
                UNION ALL
                SELECT settlement.ticket_source, settlement.profit_loss
                FROM ticket_settlements settlement
                WHERE settlement.ticket_source = 'simulation'
                  AND EXISTS (
                    SELECT 1 FROM simulation_ticket_items item
                    JOIN upset_events event ON event.match_id = item.match_id
                    WHERE item.ticket_id = settlement.ticket_id
                      AND event.business_date BETWEEN %s AND %s)
            ) involved GROUP BY source
            """,
            (start, end, start, end),
        )
        cold_profit = {row["source"]: float(row["profit"]) for row in cur.fetchall()}
    funds = _settlement_metrics(conn, start, end)
    return {
        "upsets": {
            "count": int(upsets["count"] or 0),
            "severe_count": int(upsets["severe_count"] or 0),
            "rate": float(upsets["rate"] or 0),
        },
        "user": funds["real"],
        "agent": funds["simulation"],
        "cold_impact": {
            "user_profit": cold_profit.get("real", 0.0),
            "agent_profit": cold_profit.get("simulation", 0.0),
        },
        "by_level": by_level,
        "by_play": by_play,
        "by_league": by_league,
        "model_quality": {
            "sample_size": int(quality["sample_size"] or 0),
            "brier": float(quality["brier"]) if quality["brier"] is not None else None,
            "log_loss": (
                float(quality["log_loss"]) if quality["log_loss"] is not None else None
            ),
        },
    }


def _write_pdf(path: Path, markdown: str) -> bool:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    except ImportError:
        return False
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    styles = getSampleStyleSheet()
    for style in styles.byName.values():
        style.fontName = "STSong-Light"
    story = []
    for line in markdown.splitlines():
        if not line:
            story.append(Spacer(1, 6))
            continue
        style = styles["Heading1"] if line.startswith("# ") else styles["BodyText"]
        story.append(Paragraph(html.escape(line.lstrip("#> -")), style))
    SimpleDocTemplate(str(path), pagesize=A4).build(story)
    return path.exists() and path.stat().st_size > 0


def generate_report(
    conn: Any,
    *,
    report_type: str,
    start: str,
    end: str,
    output_dir: str | Path = "data/reports/upsets",
) -> dict[str, Any]:
    start, end = validate_period(start, end)
    metrics = build_report_metrics(conn, start, end)
    markdown = render_markdown(report_type, start, end, metrics)
    html_text = render_html(markdown)
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stem = f"{report_type}-{start}-to-{end}"
    markdown_path = directory / f"{stem}.md"
    html_path = directory / f"{stem}.html"
    pdf_path = directory / f"{stem}.pdf"
    markdown_path.write_text(markdown, encoding="utf-8")
    html_path.write_text(html_text, encoding="utf-8")
    pdf_ready = _write_pdf(pdf_path, markdown)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO upset_report_metrics (
                report_type, period_start, period_end, data_cutoff_at,
                detect_rule_version_id, report_version, prompt_version,
                metrics_json, report_markdown, report_html, report_pdf_path,
                validation_status, generated_at
            ) VALUES (
                %s, %s, %s, now(),
                (SELECT id FROM upset_rule_versions WHERE is_active ORDER BY id DESC LIMIT 1),
                %s, 'deterministic-report-v1', %s, %s, %s, %s, %s, now()
            ) ON CONFLICT (report_type, period_start, period_end, report_version)
            DO UPDATE SET data_cutoff_at=now(), metrics_json=EXCLUDED.metrics_json,
                report_markdown=EXCLUDED.report_markdown,
                report_html=EXCLUDED.report_html, report_pdf_path=EXCLUDED.report_pdf_path,
                validation_status=EXCLUDED.validation_status, generated_at=now()
            """,
            (
                report_type,
                start,
                end,
                REPORT_VERSION,
                Json(metrics),
                markdown,
                html_text,
                str(pdf_path.resolve()) if pdf_ready else None,
                "validated" if pdf_ready else "partial_pdf_unavailable",
            ),
        )
    conn.commit()
    return {
        "report_type": report_type,
        "period_start": start,
        "period_end": end,
        "markdown_path": str(markdown_path.resolve()),
        "html_path": str(html_path.resolve()),
        "pdf_path": str(pdf_path.resolve()) if pdf_ready else None,
        "metrics": metrics,
    }
