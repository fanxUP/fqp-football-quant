# P137 验收：Titan 实际赛果导入

- 使用 Python 标准库解析原始 Titan HTML，并逐字段核对 `match_id`、日期、状态、主客队、全场比分和半场比分与 SQLite 规范列；仅执行版本化的明确名称规则，不做模糊匹配。
- 状态/比分不完整、来源 ID 不符、原文冲突、比分不是官方已确认记录、fixture/官方比赛映射缺失或歧义的行必须排除并给出确定原因。
- 实际比赛日期来自来源行；无来源发布时间不生成发布时间；不从彩票计划开球时间或旧 `updated_at` 推定实际时间/发布时间。
- 写入前重查 Titan 来源链接及其 evidence、已 Settled 的 `official_matches`、confirmed official results 及原始体彩结果载荷；原始 JC MatchId、半/全场原文比分、派彩/确认状态和已确认分数必须一致，显式无效/退款与非官方来源拒绝。
- 只有 Titan 完场、体彩正式确认且未作废的记录才按官方90分钟（含伤停补时）规则分类；这一分类属于多源结算证据推断，不冒充逐分钟事件验证，并把规则地址及原始体彩JSON摘要写入证据。
- 成功路径仅调用 P136 `store_result_fact`；重放幂等，冲突解释拒绝，全部写入位于一个事务。
- 隔离 PostgreSQL 回归验证 append-only、权限边界、重放、失败回滚、autocommit 拒绝；固定样本覆盖官方原始载荷语义。SQLite 只读导出防止覆盖源库且原子落包，本地扫描和生产预检保留摘要及拒绝原因。
- 生产首批导入后结果表数量与 manifest 一致，所有插入行的来源链接、official result、原始记录摘要可追溯；`official_results` 与传统足彩结算列的行数/摘要保持不变。
- 主线 CI、独立代码/安全审查、V4 scope/budget 与部署后 health/smoke 通过。

## 2026-11-03 验收结果

- P137 完成：固定样本与隔离 PostgreSQL **71/71 通过、0 跳过**；源代码提交 `bc14daa` 的 GitHub CI `41593089049` 与最终证据提交 `dde1913` 的精确头 CI `41595553805` 均通过；独立审查及安全审查通过。
- 生产只读预览 1,085 条中 1,080 条合格；5 条缺少历史批次证据并排除。随后在同一事务中追加 1,080 条，读回全部 1,080 条，均为 model-eligible；排除的 5 个 ID 均未写入。
- `official_results` 维持 4,000 行，`football_pool_issue_matches` 维持 39,552 行；没有建备份，没有重启服务。
- 本批结果和 SHA 摘要见 `/Volumes/Nas/FQP/plans/local-football-data-integration-20261029/P137-RESULT-FACT-IMPORT-20261103.md`。本结论不等于五赛季覆盖完整或模型效果提升。
