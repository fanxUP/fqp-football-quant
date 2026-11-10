# P108-04: 实际出场与分钟事实

**状态：完成并已推送 GitHub `main`。** 产品提交 `56ba6c4874d093f60337227bb5ee57e58f73ba74`；本地固定响应与隔离 PostgreSQL 回归 123 项通过，独立审查和 V4 门禁通过；exact-head CI run `42737091008` 的 `lint-and-typecheck`、`test` 均成功。未部署生产。

## 目标

将 API-Football 对已完赛比赛的逐场球员分钟，按已核实比赛、球队和球员身份写入 P104 append-only observation ledger。旧 Titan007 推算分钟不得作为实际分钟。

## 顺序

1. 固定六条产品路径、两个新增文件、零迁移、零依赖预算；复用 migration 107 的观察表。
2. RED：固定 API 样本覆盖完赛/未完赛、fixture 与主客队错配、verified 与 unresolved 身份、直接整数分钟、零/null/缺失、类型和时长边界、换人矛盾及同名不同 ID。
3. GREEN：新增确定性事实解析；扩展显式 `fixtures/players` 客户端方法；将主客队实际分钟作为两个有界 JSON observation 原子写入，caller 管理事务。
4. 扩展现有 P104 隔离 PostgreSQL 测试，验证 provenance、零分钟、幂等、cutoff 和失败回滚。
5. Ruff、format、mypy、scope/budget、V4 quality gate 和 exact-head GitHub CI 通过后，归档本工作流。

## 硬边界

- 不调用真实供应商 API、不连接生产数据库、不导入历史批次、不部署、不接 Scheduler。
- 不按姓名填补身份、不按换人事件估算实际分钟、不使用 Titan default90。
- 缺失或歧义的数据保留为 missing；本切片不改变任何模型概率。
