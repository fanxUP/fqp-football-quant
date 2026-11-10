# P111-02 局部验收

- [x] P106 父 manifest 的 SHA 和 cutoff 有效，所有 included 行都在派生清单中被保留或逐条解释排除；派生样本保持 P106 原标签与时间，不重新查询/替换赛果。
- [x] 派生清单只含一个经过验证的 competition-season；成员与场地上下文不晚于 fit cutoff，目标上下文和赔率快照不晚于统一 prediction-as-of，as-of 早于所有 kickoff。
- [x] 候选 model version 参数完整可审计且 inactive；P106 model manifest、run manifest、group output identity 相互一致。
- [x] 工件版本摘要覆盖全部不可变参数；同工件重跑复用版本，排除样本证据变化不发生版本冲突。
- [x] P106 storage 读回全部完整 SPF 组；输入支持官方 h/d/a 与规范 3/1/0 码，要求开放、同时间/同源/同市场且 45 分钟内的赔率快照（每项 >1），snapshot_time 和数据库 created_at 都不晚于 prediction-as-of；group 保留 snapshot IDs/times，created_at 保存在按 match_id 关联的哈希 run input manifest 中，并保留比分矩阵。
- [x] 隔离 PostgreSQL 的最终赛果样本可由 `evaluate_prediction_replay` 读取，得到成对 Brier/LogLoss/RPS 并存入 research backtest 记录；未结算样本不计为已评价。
- [x] DB 守卫核实 DSN host/hostaddr、实际数据库名和测试库标记；run/evaluation 要求 idle 连接，不提交/回滚调用者事务；赔率只读校验成功或失败都恢复 idle，允许安全重试。
- [ ] 固定样本和相关现有回归、Ruff/format/mypy、V4 scope/budget、独立审查和 exact-head CI 通过。
- [ ] 不运行活动模型、委员会、正式推荐/预测发布、schema migration 或外部调用；用户授权的代码部署只运行既有健康检查/保护路由只读 smoke，不执行 P111 adapter、不写生产业务数据。
