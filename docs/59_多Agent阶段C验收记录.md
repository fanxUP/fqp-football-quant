# 多 Agent 阶段 C 验收记录

> 历史验收事实：本记录验证时使用本机 PostgreSQL，未启动 Docker Desktop、Redis 或 Celery。当前运行方式以 `54_本机运行与DockerDesktop弃用说明.md` 为准。

## 目标

在本机 PostgreSQL 上把数据、特征、模型、推荐、回测、复盘和 QA 任务统一纳入 `ai_job_runs`，形成可追溯的本地任务执行链。

## 已接入任务

| 任务 | job_code | owner_agent |
| --- | --- | --- |
| 官方赛程 | `official_schedule` | `data_agent` |
| 官方赔率快照 | `official_odds_snapshot` | `data_agent` |
| 天气采集 | `weather_collection` | `feature_agent` |
| 阵容采集 | `lineup_collection` | `feature_agent` |
| 伤停采集 | `injury_collection` | `feature_agent` |
| 特征快照 | `feature_snapshot_build` | `feature_agent` |
| 模型预测 | `model_prediction` | `model_agent` |
| 推荐候选 | `recommendation_candidate` | `recommendation_agent` |
| 回测 | `backtest` | `backtest_agent` |
| 每日复盘 | `daily_review` | `review_agent` |
| 证据链校验 | `evidence_chain_validation` | `qa_agent` |
| 数据污染审计 | `data_contamination_audit` | `qa_agent` |

## 执行与失败规则

- 任务启动时写入 `running`，结束时写入结果状态和输出摘要。
- 未捕获异常写入 `failed` 和 `error_message`，异常继续抛出，不隐藏真实失败。
- 只有 `failed` 任务可以重试；默认最多重试 2 次。
- 重试会增加 `retry_count`、清理旧错误并恢复为 `running`。
- dry-run 也记录台账，但不写入生产业务结果。
- 没有官方数据、场馆坐标或可审计票项时安全返回空结果，不制造占位数据。

## 验收证据

- 本地 PostgreSQL 实测生成了官方采集、天气、特征、模型、推荐、回测和 QA 任务记录。
- 失败任务重试实测：`failed -> running`，`retry_count = 1`。
- Python 全量测试：211 passed。
- 运行环境：本机 Python、Node.js、Homebrew PostgreSQL；未启动 Docker Desktop。

## 下一阶段边界

阶段 D 继续补充任务依赖检查、定时调度可视化和 Risk Agent 人工审核闸门；不改变官方赛程唯一口径，不自动发布正式投注建议。
