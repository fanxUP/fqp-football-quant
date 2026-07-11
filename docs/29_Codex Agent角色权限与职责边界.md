# 29. Codex Agent 角色权限与职责边界

## 1. Agent 清单

| Agent | 核心职责 | 禁止事项 | 主要输出 |
|---|---|---|---|
| Orchestrator Agent | 拆任务、分配任务、汇总结果 | 直接改生产数据 | 任务计划、任务状态 |
| Data Agent | 官方赛程、赔率、赛果、第三方数据采集 | 生成投注推荐 | 采集脚本、数据质量报告 |
| Feature Agent | 赛季、球队、球员、伤停、天气、战意特征 | 绕过快照直接覆盖特征 | match_feature_snapshots |
| Model Agent | Poisson、Dixon-Coles、赔率转换、模型委员会 | 直接发布推荐 | model_predictions |
| Backtest Agent | Walk-forward 回测、防未来函数检查 | 用赛后数据训练赛前模型 | 回测报告 |
| Recommendation Agent | 生成候选推荐、票单组合、预算方案 | 绕过 Risk Agent | candidate_tickets |
| Risk Agent | 熔断、不推荐、资金上限、合规检查 | 修改模型概率以迎合推荐 | risk_decisions |
| Review Agent | 日报、周报、月报、错因归因 | 隐藏亏损样本 | review_reports |
| QA Agent | 单测、集成测试、回归测试、Lint | 未测试直接合并 | test_reports |
| DevOps Agent | Docker、调度、备份、恢复、监控 | 擅自清库 | deployment_reports |
| Doc Agent | 文档、API、数据字典同步 | 夸大模型收益 | docs, changelog |

## 2. 权限分级

```text
P0 只读权限：查看代码、日志、文档、测试结果。
P1 开发权限：修改代码、生成迁移、运行本地测试。
P2 任务执行权限：触发非生产采集、非生产回测、非生产模型计算。
P3 受控生产权限：触发生产任务，但必须记录审计和人工确认。
P4 禁止自动权限：删除生产数据、修改真实票据、发布真实推荐、修改资金上限。
```

## 3. Agent 权限矩阵

| Agent | 读数据库 | 写开发库 | 写生产库 | 触发任务 | 发布推荐 | 修改资金规则 |
|---|---:|---:|---:|---:|---:|---:|
| Data | 是 | 是 | 受控 | 是 | 否 | 否 |
| Feature | 是 | 是 | 受控 | 是 | 否 | 否 |
| Model | 是 | 是 | 受控 | 是 | 否 | 否 |
| Recommendation | 是 | 是 | 受控 | 是 | 候选 | 否 |
| Risk | 是 | 是 | 是 | 是 | 审核 | 否 |
| QA | 是 | 是 | 否 | 是 | 否 | 否 |
| DevOps | 是 | 是 | 受控 | 是 | 否 | 否 |
| Doc | 是 | 是 | 否 | 否 | 否 | 否 |

## 4. 审计要求

每个 Agent 操作必须记录：

```text
agent_name
agent_version
task_id
input_refs
output_refs
files_changed
commands_run
tests_run
risk_level
human_review_required
created_at
```

## 5. 人工审核闸门

以下动作必须人工确认：

- 发布每日正式推荐。
- 修改每日预算上限。
- 修改熔断阈值。
- 删除或覆盖历史赔率快照。
- 修改真实实票记录。
- 执行生产数据库迁移。
- 发布月报中涉及真实盈亏的结论。

## 6. 落地步骤

1. 建立 `agent_registry.yaml`。
2. 建立 `agent_permissions.yaml`。
3. 建立 `agent_tasks` 表。
4. 所有脚本入口统一接受 `--agent-name` 与 `--task-id`。
5. 所有写入动作都写入 `agent_audit_logs`。
6. 合并代码前由 QA Agent 自动跑测试。
7. 推荐前由 Risk Agent 生成 `risk_decision`。
