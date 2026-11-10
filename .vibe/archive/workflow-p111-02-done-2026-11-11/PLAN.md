# P111-02：接入 P106 预测运行与评价

1. 复用 P106 `TrainingManifest`、`training_manifest_sha256`、模型工件身份、预测 run/group 存储和 `evaluate_prediction_replay`；不另建赛果标签或时间 cutoff 规则。
2. 将经过验证的逐场赛季上下文映射到父 P106 manifest 的全部 included 样本。按一个明确的 canonical `competition_id/competition_season_id` 投影出单赛季 P106 清单；保留父清单 SHA，并把缺失、晚于 cutoff、属于其他赛季的样本逐条记入排除原因。不得按名称、年份、球队表现或结果猜映射。
3. 使用投影清单和匹配上下文拟合 P111-01 候选；保留父/派生 manifest、季赛证据、配置、候选 SHA 和运行时源码摘要。
4. 以 `dynamic_team_poisson_shadow`、`is_active=false`、`rollout_mode=shadow` 写入现有 P106 模型工件/训练清单表；生成带完整身份的 P106 prediction run 和 SPF prediction groups，配对同一 prediction-as-of 的完整市场赔率快照。
5. 对已出正式赛果的 run 调用既有 P106 `evaluate_prediction_replay`，并通过 `store_research_evaluation_run` 记录模型与市场基线的配对评价；未结算比赛只保留 run，结算后再评价。
6. 用固定样本和隔离 PostgreSQL 验证完整链路、身份完整性、时间隔离、单赛季约束、失败路径及市场配对。候选不进入活动模型列表，不参与委员会，不改变正式预测。
7. 用户已要求提交并部署。本次只发布休眠适配器代码；适配器只接受带受信测试库标记的 loopback PostgreSQL，生产环境会拒绝执行。部署脚本仅运行现有健康检查和保护路由只读 smoke，不改变服务配置、数据库、调度、委员会或活动模型。

## 明确排除

- 不新增数据库迁移、依赖、供应商 API、P111 生产数据读写、调度配置或正式模型启用；允许用户授权的代码部署，但不在生产执行候选。
- 本切片证明 P106 存储和评价链路能承载候选，不证明来源数据覆盖完整、候选优于当前模型/市场或可正式上线。
