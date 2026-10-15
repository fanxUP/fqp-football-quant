# Agent 边界文字验收清单

本页描述检查目标，不是已执行的测试结果。

1. generated 票单经 `activate_simulation_ticket` 激活时，没有 approved 审核状态应被拒绝。原因：`model_storage.py` 调用 `assert_recommendation_publishable`，检查的是现有模拟票单激活入口。
2. 重复采集官方赔率时不覆盖历史快照。原因：历史预测和票据需要引用当时赔率；相同快照可按现有去重逻辑跳过。
3. L4/L5 项目任务创建 pending 人审闸门，未解决闸门阻止 approved/merged 转换。原因：这是 `orchestrator.py` 已实现的审核边界。
4. valid 预测保留模型版本、赔率/特征快照及实际验证字段；无效预测不能冒充 valid。原因：`model_storage._validate_prediction_payload` 对有效结果要求完整证据，同时允许记录非 valid 结果。
5. 记录执行命令与结果，未执行时标明未验证。原因：文字验收目标不能证明行为已经通过测试。
