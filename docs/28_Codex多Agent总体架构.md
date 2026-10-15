# 28. Codex 与长期任务的职责

## 现行规则

1. Codex 承担开发、维护、分析和受控触发；长期采集与计算使用 Scheduler/Worker。原因：已有常驻入口独立于聊天进程运行。
2. 按当前任务需要划分职责，使用项目 Agent 记录时引用 `configs/agent_registry.yaml` 中的身份。原因：开发分工名称与数据库登记的 Agent 名称不能混为一谈。
3. 代码修改限定在任务范围，数据、模型、UI、运维修改分别说明影响。原因：角色分工用于约束改动范围，不能替代授权。
4. 推荐发布和高风险操作遵守实际审核入口。原因：现有审核函数检查状态与任务类型，没有通用的自动 Risk Agent 通知链。
5. 交付时提供实际执行证据，并明确未验证项。原因：任务失败不会自动变成 Codex 修复任务，仍需依据日志判断处理结果。

## 当前实现

| 层次 | 入口 |
| --- | --- |
| Agent 定义、任务与审核 | `scripts/agents/`、`scripts/agent_storage.py` |
| 定时调度 | `scripts/jobs/run_scheduler.py`（APScheduler） |
| 官方采集 Worker | `scripts/official_crawler_stub.py` |
| 应用接口 | `apps/backend/src/app.py`、`apps/backend/src/routers/` |
| 调度运行记录 | `ai_job_runs`，由追踪包装器或任务自身记录 |

任务编排不依赖 Celery Beat、Cron 或独立的 Feature/Model/Report Worker 服务；具体任务仍由当前调度入口调用。
