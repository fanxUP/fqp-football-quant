# 多 Agent 阶段 D 验收记录

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
