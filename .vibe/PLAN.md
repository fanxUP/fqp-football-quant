# P138 计划：修复预测赔率时点越界

1. 在现有 `test_run_model_prediction.py` 增加 RED 查询回归；在 `test_prediction_run_postgres.py` 增加真实隔离数据库样本，覆盖 cutoff 前、等于、之后及同秒 ID 平局。
2. 在 `scripts/jobs/run_model_prediction.py` 两条 odds 查询加 `snapshot_time <= predict_time`，并用 `id DESC` 稳定同一时刻排序。
3. 跑 60 项预测 job 单测、隔离 PostgreSQL 精确样本、Ruff 与格式/diff/scope/budget 检查。
4. 核对精确主线 CI 和独立审查；发布前只读确认生产服务/DB负载及计划。无 migration，无生产业务写入；本任务不手动触发生产预测。
5. 如后续部署获准，待自然任务后只读验证新 run 所有 odds 快照时点均不晚于 cutoff；不得把旧 run 标为修复后结果。
