# 多 Agent 阶段 B 验收记录

阶段 B 将 Codex 开发任务与 QA/Job Run 结果接通：

- `qa-report` 把测试命令、通过数、失败数和摘要写入 `codex_review_reports`。
- `job-start` / `job-finish` 把本地 AI 计算或采集任务写入 `ai_job_runs`。
- 所有记录通过 task_id、agent owner 或 run_id 关联，便于审计。

高风险任务仍必须经过 `agent_human_review_gates`，本模块不发布正式推荐、不修改预算规则、不执行 Docker 部署。
