"""Generate a Codex task prompt from a structured task definition."""

from pathlib import Path

TEMPLATE = Path("templates/codex/general_task_prompt.md")


def render_prompt(task: dict) -> str:
    text = TEMPLATE.read_text(encoding="utf-8")
    for key, value in task.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text


if __name__ == "__main__":
    sample = {
        "task_title": "实现官方赔率快照采集器",
        "task_code": "DATA-ODDS-001",
        "owner_agent": "data_agent",
        "risk_level": "L3",
        "required_docs": "docs/04_官方数据采集与数据治理.md",
        "allowed_files": "scripts/jobs/run_official_odds_snapshot.py, tests/agent_tests/test_odds_snapshot.py",
        "forbidden_files": "sql/生产数据, configs/bankroll_rules.yaml",
        "acceptance_criteria": "新增快照不可覆盖；官方源失败触发熔断；测试通过。",
    }
    print(render_prompt(sample))
