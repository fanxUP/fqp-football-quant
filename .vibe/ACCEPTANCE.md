# P108-05 验收

- [x] 当前比赛的完整 P104 batch 经 hash/cutoff 校验；无 latest-row 替换或重建 cutoff。
- [x] 主客队必须分别有恰好 11 名确认首发，球员 source ID 与 verified canonical ID 一一对应。
- [x] 当前伤停/可用性必须来自该 batch 的完整覆盖报告；未覆盖、过期、未映射或未知状态不被当成健康。
- [x] 赛事赛季只从 cutoff 前已记录的 linked fixture-season 修订中解析，并使用该来源的计划赛季区间；无唯一映射时 withheld。
- [x] 注册资格仅认可在 batch cutoff 前可见、权威源获批、且有效区间覆盖开球日的审查事实。
- [x] 生成版本、match/batch/cutoff/as-of、身份 revision digest、注册/伤停来源证据、coverage 与 missingness。
- [x] 任意必需信号不完整或冲突时，玩家候选为 withheld；基础影子预测仍按旧规则工作。
- [x] shadow 集成前后固定样本概率一致，投影不产生 probability、分值或主观权重。
- [x] 时间泄漏、同名、冲突、完整/不完整 coverage、本地 PostgreSQL 只读行为回归全部通过（104 项通过）。
- [x] Ruff、format、mypy、scope/budget、V4 本地门禁、独立审查和 security review 通过。
- [x] P108-05 实现提交 `186202b6db9ceac00aae6d76297a5cd7b966cf01` 的 GitHub main exact-head CI 已通过（run `42751914384`；`test`、`lint-and-typecheck` 成功）。证据提交自身仍由 V4 发布门禁核验其 exact-head CI。
- [x] 无迁移、外部 API、生产访问/写入、数据导入、调度改动或服务器部署。
