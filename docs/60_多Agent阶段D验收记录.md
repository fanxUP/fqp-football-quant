# 多 Agent 阶段 D 验收记录

> 历史验收事实：本记录中的“未使用 Docker Desktop”仅描述当次本机验收环境；当前运行方式以 `54_本机运行与DockerDesktop弃用说明.md` 为准。
>
> 2026-10-26 重试语义修订（本地待发布）：下述原地重开记录属于历史实现。应用116迁移后的通用重试返回独立 `retry_run_id`，原失败记录不变；同一父记录最多派生一条重试。默认预算2表示沿重试链最多2轮，应重试最新失败的子ID，不能再次重试祖先。`job-finish` 必须使用新ID，避免旧执行结果晚到覆盖下一轮。
>
> `python -m scripts.agents.cli job-retry <failed_id>` 只创建审计记录，不调用业务函数、启动进程或重新获取供应商数据。返回 `retried: false, retry_run_id: None` 表示本次未创建，可能因父状态、预算、已有子记录或专用归属限制；若COMMIT确认丢失，先按 `retry_of_run_id` 查找已提交子记录，不能假定没有创建。`model_prediction`、`backtest` 及带 `execution_protocol` 的任务须走各自正式入口，不允许通用重试复制执行归属。此修订不表示所有通用业务已具有独占执行或安全自动重领能力。
>
> 发布顺序：先应用116再启用新代码。回滚时保留新增列、索引与历史记录；旧代码会恢复原地重开语义，因此应暂停通用 `job-retry` 操作直至修复代码恢复。无需删除新子记录或还原失败父记录。

## 已完成

- Job 启动支持前置依赖检查；缺少前置记录或最新状态不是 `completed` 时阻断启动。
- 实际依赖列表写入 `ai_job_runs.input_snapshot_refs.dependencies`。
- 模型预测、推荐候选、特征快照已接入正式依赖链；dry-run 不消费生产依赖。
- 失败 Job 支持受控重试，默认最多 2 次。
- CLI 支持 `job-retry`、`job-start --depends-on` 和 `review-resolve`。
- L4/L5 任务自动创建人工审核闸门；pending 闸门禁止进入 `approved/merged`。

## 真实本地验收

- `official_schedule` 作为前置 Job 检查通过。
- 故意失败的 Job 经 CLI 从 `failed` 重试为 `running`，`retry_count` 正确增加。
- L4 推荐任务创建 pending 闸门，经 `review-resolve approved` 后成功进入 `approved`。
- 全量 Python 测试：216 passed。
- 运行环境为本机 PostgreSQL，未使用 Docker Desktop。

## 当前边界

阶段 D 已完成任务执行治理和人工审核基础闭环；正式推荐发布仍保持 Risk Agent 和人工审核边界，不自动向外部渠道发布。
