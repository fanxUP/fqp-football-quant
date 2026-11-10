# P108-04 验收

- [ ] 完赛 FT/AET/PEN 可解析；未完赛、错误 fixture、重复 fixture 或主客队不匹配均拒收。
- [ ] 只从 `statistics[].games.minutes` 取非布尔整数；0 保留，null/缺失不制造事实，字符串/布尔/负数/越界分钟拒收。
- [ ] 经 verified ID bridge 解析 canonical player ID；unresolved/rejected 只计覆盖缺口；同名不同 source ID 不串人。
- [ ] 直接分钟与明确替换出入场事件冲突时拒收；事件不用于反推分钟。
- [ ] Titan `legacy-name-substitution/default90-v1` 不能进入适配器。
- [ ] 每队事实有来源响应摘要、source/official fixture/team/player IDs、direct-source derivation 与获取时间；历史事实没有 TTL。
- [ ] 两队 observation 写入同一 caller-owned transaction；固定 PostgreSQL 测试验证幂等、cutoff replay 与 rollback。
- [ ] 固定响应回归、隔离 PostgreSQL 16 回归、Ruff、format、mypy、scope、budget、V4 quality gate、独立审查和 exact-head CI 均通过且数据库测试无 skip。
- [ ] 零 API 调用、零生产数据库访问、零数据导入、零迁移、零部署、零模型概率变化。
