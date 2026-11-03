# P137 设计：可信结果事实的最小导入

读取边界：Titan SQLite `mode=ro`, `query_only=ON`；原始 HTML 只解析，不执行。只有生产中已存在唯一 Titan MatchId → fixture → official match 的链路可被考虑。官方来源的已确认全场与半场比分作为语义校验；任一不一致即排除，不用模糊队名/日期匹配。

事实写入：将精确校验过的来源行作为 `source_payload`，保存 Titan 比赛 ID、实际日期、比分和 P136 事实字段。发布时间保持 NULL。若未确认精确开球时区，`kickoff_time_precision=date_only`、`actual_kickoff_at=NULL`。写入使用受限 runtime role、事务级 lock/statement timeout 和单事务 all-or-nothing。

不会用规范化得分推断延期、取消、提前结束或点球/加时语义；P137 仅导入 `完场` 原文一致且与体彩 `confirmed` 赛果全/半场完全一致的样本。其他项输出分类报告，等待单独证据，不静默丢失。
