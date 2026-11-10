# P111-02 验收：P106 run/evaluation 接入

- [x] 父 P106 manifest 的 SHA、cutoff 和样本身份先验证；派生季赛清单中的每个 included 样本都来自父 included 集合，父 included 每一行都恰好被纳入或带原因排除。
- [x] 只有证据完整、canonical 赛季匹配、且成员/场地事实不晚于 fit cutoff 的样本进入拟合；目标 fixture 事实与赔率快照不晚于 prediction-as-of，prediction-as-of 严格早于 kickoff。
- [x] 候选工件绑定父/派生 manifest、季赛上下文、P111 candidate SHA、运行时代码；模型版本保持 inactive，rollout mode 为 shadow。
- [x] 模型版本以完整不可变工件参数摘要为键；重复相同工件幂等，排除样本证据变化生成新工件且不混淆候选拟合摘要。
- [x] 每个有效目标输出完整 SPF 3/1/0 组，接受官方 h/d/a 码归一化；快照须来自单一开放市场、同捕获时间与同源摘要，snapshot_time 与数据库 created_at 都不晚于 prediction-as-of、最多 45 分钟新且每项赔率大于 1。P106 group 保存赔率快照 ID/源时间；哈希绑定的 run input manifest 保存 created_at 并按 match_id 关联 group；保留市场基准与完整 artifact identity。
- [x] 预测 run 与 groups 通过现有 P106 存储函数完成、可读回；完整赛果样本可由现有 `evaluate_prediction_replay` 评价，并经现有研究评价存储器保存模型/市场成对指标。
- [x] 数据库守卫同时检查连接 host/hostaddr、实际 database 名称和受信 CI/测试库 comment 标记；两个入口只接受 idle psycopg2 连接，且守卫及只读赔率校验结束后恢复 idle。
- [x] 固定样本测试和隔离 loopback PostgreSQL 回归通过；适配器不连接生产库、不调用供应商、不激活模型、不写入委员会、不新增迁移、依赖或调度。
- [x] 明确未评价的数据留待官方赛果结算后回放；本切片不声称预测效果提升或 P111 完整验收通过。
- [x] GitHub CI exact-head 通过（`996d63a`，run `42786096692`）；仅休眠适配器代码已部署到 `100.121.47.26`，生产模型、调度和正式预测路径仍未连接或启用。
