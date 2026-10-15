# 32. Agent 任务与运行记录

## 当前存储

| 内容 | 表/入口 |
| --- | --- |
| Agent 定义 | `agent_registry` |
| 开发任务 | `agent_tasks` |
| 任务产物 | `agent_task_artifacts` |
| 操作审计 | `agent_audit_logs` |
| 人工审核 | `agent_human_review_gates` |
| QA 报告 | `codex_review_reports` |
| 调度运行 | `ai_job_runs` |

实现位于 `scripts/agent_storage.py`、`scripts/agents/`；基础结构见 `sql/13_multi_agent_codex_schema.sql`。

## 保留规则

1. 开发任务和调度执行分别使用各自记录，不混用状态与 ID。原因：`agent_tasks` 和 `ai_job_runs` 表达不同生命周期。
2. 任务状态以 `agent_storage.TASK_STATUSES` 和实际转换函数为准。原因：旧文档列举的状态不完整，也没有证明每个状态都按线性顺序执行。
3. L4/L5 或显式要求审核的任务创建审核闸门，pending 闸门阻止 approved/merged。原因：这是 `orchestrator.py` 已实现的审核边界。
4. 已接入追踪的任务记录输入、输出、错误和结束状态。原因：页面需要区分运行、完成、失败和中断恢复。
5. 重试受对应函数的次数和依赖条件约束。原因：任务队列直接记录 PostgreSQL，没有独立 Celery 队列自动保证重试。
6. 对未接入审计或自动修复的操作明确记录限制。原因：不能承诺“任意操作都有审计”或“失败都会自动生成修复任务”。
