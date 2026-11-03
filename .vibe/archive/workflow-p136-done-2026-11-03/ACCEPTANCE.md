# P136 验收：足球比赛结果事实层

- 新 migration 130 只追加结构，表与来源 MatchId/ID-system/fixture 绑定一致。
- 同源同 payload、解析事实与证据完全一致时重放幂等；同 payload 却有不同解析事实/证据时拒绝静默覆盖；来源 payload 改变时追加新行；摘要由数据库生成。
- 半场/全场分数只能成对出现且非负；状态和 score basis/period 都明确保存。
- 数据库拒绝不存在或映射到其他 fixture 的来源链接。
- 模型候选视图只含日期已知、completed、on_field、regulation、全场比分完整的事实；非标准赛果、未知日期和未知语义均排除。
- 应用角色只能读/追加，不能更新、删除或截断；触发器和权限均有隔离 PG 断言。
- 迁移整笔回滚不留对象，既有表和数据不变；发布策略必须精确 pin migration SHA 与演练报告。
- 本地固定样本及隔离 PostgreSQL 回归零失败零跳过；Ruff、格式、编译、diff、scope 与预算通过。
- 本批没有生产业务 DML、外部 API 请求、依赖增加或公开 API 变更。
