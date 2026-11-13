# 回填期间可独立推进的工程切片

## 目标

在五年历史回填尚未完整时，先完成可用本地固定样本和隔离数据库验证的工程链路。工程通过只代表数据契约、读取、隔离和评价工具按预期工作，不代表真实模型效果或历史数据已完整。

## 本批范围

- **P108-05A 球员影子回执**：持久化球员投影的 ready/withheld 证据；当前球员候选保持 `withheld`、`probabilities=null`、`applied_features=[]`，不得影响正式预测。
- **P111 动态球队候选**：依赖 P106 的 manifest、预测 run/group 和 replay 评价链路；按已验证的赛事赛季隔离，输出仅供研究的 shadow 结果，不启用、不晋升。
- **P114 点时赛果标签与评价**：只使用可信官方赛果观测及提交可见回执；没有可信来源时间或 cutoff 证据的历史行继续排除，不使用文件时间或回填时间补造。
- **P105 预测任务恢复性能**：拆分运行中任务所有者与子预测运行的恢复查询，并通过迁移 139 增加并发部分表达式索引，避免扫描大量历史 JSON。迁移不改写业务行；本批不在生产库执行。
- **CI 格式修正**：按项目 Python 3.14/Ruff 配置格式化被 exact-head CI 指出的 73 个 Python 文件；变化只移除多类型 `except` 中冗余括号，不改运行行为。

## 回填不完整时的边界

1. 可完成代码、数据库契约、失败关闭、幂等与固定样本回归。
2. 缺少球员规范身份、名单、伤停或分钟事实时，P108 只能保持 withheld。
3. 缺少可信的点时赛果、同一预测时点赔率和验证赛季归属时，P111/P114 只能完成工程验收，不能给出真实效果结论。
4. P115 前瞻评估要等正式预测和之后的比赛结果，不用历史回填替代未来观察。

## 验收与安全边界

- 使用固定样本和专用 loopback PostgreSQL 16；不连接生产库、付费 API 或正在写入的 Titan SQLite。
- 保持所有模型自动晋升与正式概率变更门关闭。
- 完成当前树的独立审查和 exact-head GitHub CI 后，才进入服务器发布；发布还需要符合发布脚本的服务器状态、迁移和只读 smoke 门禁。
- 本地工程验收、生产发布、数据完整性验收和模型效果验收是不同状态，分别记录。


## 2026-11-11 follow-up status

Static Titan exports were re-counted without opening the active `titan007.db`; the detailed coverage and limitations are recorded in the integrated P108 source-export audit. The existing P107 acceptance and P105/P106/P108/P111/P114 engineering paths remain usable before five-year backfill completes. Real P108 player facts, P114 effectiveness, and P115 prospective results still require new eligible observations.

The local release policy was extended to allow migration 139 alone on the no-backup path after exact SQL pins and a fresh structured non-transactional PostgreSQL rehearsal. The evidence contract requires the runtime owner-query SHA/EXPLAIN JSON, the `ai_job_runs` execution-protocol index condition, valid/ready catalog state, unchanged rows, DOWN/reapply checks, and an Ed25519 host signature over the exact report bytes in a migration-specific namespace. This is a local release-policy change only; no production migration or deployment was performed. Exact-head CI and fresh release evidence remain pending.


## 2026-11-11 local verification closeout

- Dedicated loopback PostgreSQL 16 fixture identity was checked by database comment and non-superuser role; configured P106/P114 regression passed 233 tests. V4 regression test/lint/typecheck all reported 0/0; V4 scope and change budget passed.
- P105 migration 139 release-policy and migration-format regression passed 143 tests; Bash syntax, Ruff/format and `git diff --check` passed. The report-signature provenance finding was closed with exact-byte Ed25519 verification, migration-specific namespaces and both cross-namespace rejection tests; independent follow-up review passed.
- Static P108 CSV audit was recorded outside the code checkout. No NAS SQLite, production database, provider API, server, or deployment was accessed. Exact-head CI for these uncommitted changes and production release evidence remain pending.


## 2026-11-13 release follow-up

Production apply exposed a catalog-format mismatch for the existing recovery index on varchar columns. Keep the valid/ready index in place; do not recreate it or change business data. The validator now strips implicit `::text` casts only outside quoted values and compares the complete pinned predicate. Regression rejects literal changes and extra filters; independent follow-up review passed. The release-policy suite passed 149 tests, the configured isolated P106/P114 suite passed 233 tests, and V4 test/lint/typecheck regression is 0/0. Obtain a fresh isolated rehearsal report and production-host signature bound to the new commit, then retry only after exact-head CI passes. The release fail-safe currently has `fqp-backend`, `fqp-scheduler`, `fqp-worker`, and Nginx stopped; remove and verify the temporary sudoers rule after the retry.
