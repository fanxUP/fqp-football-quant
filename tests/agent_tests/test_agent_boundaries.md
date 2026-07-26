# Agent 权限边界测试用例

## 用例 1：推荐发布必须经过 Risk Agent

输入：Recommendation Agent 生成候选票单。
期望：未通过 Risk Agent 时不得写入 final_recommendations。

## 用例 2：官方赔率快照不可覆盖

输入：同一场比赛重复采集赔率。
期望：新增 snapshot 行，不覆盖旧行。

## 用例 3：L4/L5 任务必须人工审核

输入：任务 risk_level=L4。
期望：agent_human_review_gates 创建 pending 记录。

## 用例 4：模型预测必须绑定快照

输入：Model Agent 生成预测。
期望：model_predictions 中 odds_snapshot_id、feature_snapshot_id、model_version_id 不为空。
