# P108-04 验收

- [x] 完赛 FT/AET/PEN 可解析；未完赛、错误 fixture、重复 fixture 或主客队不匹配均拒收。
- [x] 只从 `statistics[].games.minutes` 取非布尔整数；0 保留，null/缺失不制造事实，字符串/布尔/负数/越界分钟拒收。
- [x] 经 verified ID bridge 解析 canonical player ID；unresolved/rejected 只计覆盖缺口；同名不同 source ID 不串人。
- [x] 直接分钟与明确替换出入场事件冲突时拒收；事件不用于反推分钟。换人已知区间使用 ±2 分钟容差并验证边界。
- [x] Titan `legacy-name-substitution/default90-v1` 不能进入适配器。
- [x] 每队事实有来源响应摘要、source/official fixture/team/player IDs、direct-source derivation 与获取时间；历史事实没有 TTL。
- [x] 两队 observation 写入同一 caller-owned transaction；固定 PostgreSQL 测试验证幂等、cutoff replay 与 rollback。
- [x] 固定响应及隔离 PostgreSQL 16 回归 123 项通过（0 skip）；Ruff、format、mypy、scope/budget、V4 quality gate、独立审查和 exact-head GitHub CI 通过。
- [x] 零真实 API 调用、零生产数据库访问、零数据导入、零迁移、零部署、零模型概率变化。
