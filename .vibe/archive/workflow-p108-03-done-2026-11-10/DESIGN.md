# P108-03 设计

- 事实存储继续使用 `observation_revisions`：团队流负责原子批次和 `available_at` 截面，`value.players[]` 保留逐球员状态与来源时间。
- 新增封闭枚举 `PlayerAvailabilityStatus` 和 `LineupStatus`；API-Football 的 `Missing Fixture` 仅表示缺席，必须根据明确的停赛/伤情原因分类；无法识别的缺席原因映射到 `unknown`，不会把缺席直接猜成受伤。
- `store_lineup_observation` 仅接受确认阵容；确认必须有 11 名不同首发。`predicted` 在当前 adapter 中明确拒绝，避免被写成 legacy `confirmed`；没有预测来源时不造预测事实。
- 伤停来源时间按每名球员分别存入 observation JSON。只识别源字段 `effective_at`、`published_at` 和 `expected_return_date`，时间必须带时区，日期必须为 ISO 日历日。`updated_at` 不作为发布时间或生效时间。
- 团队级空响应继续依赖 coverage evidence；不能为没有伤停行的球员插入 returned/available 投影。
- 旧版投影仍在 caller-owned transaction 内与 observation 一同提交，任一异常整体回滚；同一内容复用 observation revision，但每次采集的两队历史回执保持追加。
