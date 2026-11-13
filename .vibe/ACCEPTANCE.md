# 当前工程验收：P108-05A / P111 / P114 / P105 恢复性能

验收对象包含主线提交 `1ee8f2a71f3ed3b0e345aca7532476151342e39a` 及当前本地未提交的 P105 139 号迁移免备份发布门禁收口。主线提交的 exact-head CI 已通过；本地门禁变更已补充服务器主机 Ed25519 签名及跨命名空间拒绝测试，独立复核通过，当前改动仍需 exact-head CI。此验收不等同于服务器发布、历史数据完整或模型效果验收。

## 已通过

- [x] P105 预测任务恢复及预测运行 PostgreSQL 回归：93 passed；仅使用一次性 loopback PostgreSQL 16 `fqp_p106_test_*` 数据库。
- [x] P106/P111/P114 训练 manifest、动态球队候选、backtest/replay 固定样本回归：183 passed；新增覆盖数据库 loader 的 JSON 回执和 ISO 时间戳进入预先声明 final window 并成功评估。
- [x] P106/P114 当前配置回归：专用 loopback PostgreSQL 16 fixture 下 233 passed，包含 observation PostgreSQL 用例；没有连接生产库。
- [x] P111 P106 run/group/replay 隔离 PostgreSQL 集成回归：1 passed，使用 loopback PostgreSQL 16 测试库。
- [x] 本地数据库运行时回归：53 passed。
- [x] 此前主线验收组合计 380 项通过：P105 93、P106/P111/P114 183、P111 PostgreSQL 集成 1、P104/P114 observation PostgreSQL 50、本地运行时 53；当前配置回归另行记录为 233 passed。
- [x] 全仓库 Ruff check 与 format check 通过；training manifest、动态球队、回测四模块 mypy、定向 compileall、`git diff --check` 通过。为修复 CI 报告的格式门禁，73 个已变更 Python 文件已按项目配置格式化。
- [x] V4 regression check：test、lint、typecheck 均为 regression=0/0；V4 scope/budget 检查为 33 个变更路径，均在 96 文件预算内；4/4 新文件、0 依赖新增、2/2 SQL 迁移文件，未超预算。
- [x] 在一次性 PostgreSQL 16 数据库运行迁移器：139 并发索引成功创建，valid/ready 与 checksum ledger 通过；随后只读计划显示无待迁移；down 文件成功移除测试索引。该演练使用最小隔离表和模拟的 135 条既有 migration ledger，不是完整生产副本演练。
- [x] P108 球员 shadow 仍 withheld；P111/P114 不晋升模型、不改正式预测概率。
- [x] CI 捕获的源评价测试已校正：未声明绝对日期的滚动末周不标记为正式留出窗口；对应单测本地 1 passed。

## 尚未完成

- [x] 主线提交 `1ee8f2a` 的 exact-head GitHub CI：lint/typecheck 与完整测试两项均通过；测试为 4,062 passed、32 skipped、43 warnings，覆盖率 70.73%。
- [ ] 服务器发布及发布后只读 smoke 未执行；没有访问生产数据库、执行迁移 139 或创建备份。139 的隔离演练报告现要求服务器主机密钥签名；当前尚无本批签名报告，本地未提交改动的独立复核与 exact-head CI 也尚待完成。
- [ ] A108 球员事实链、A111 真实模型效果、A114 点时样本外效果、A115 前瞻窗口仍需各自的数据证据。
- [ ] 五年回填完整性与关联覆盖率未在本验收中读取或确认。

新增 loader 回归使用数据库 JSONB 输出形态的固定映射和时区 ISO 字符串，实际经过 `load_research_matches` 与固定窗口评估；另外，本轮也在专用隔离 observation PostgreSQL 库重新运行了 50 项 P104/P114 回归。

第一次运行使用 1 GiB tmpfs 的测试 PostgreSQL，容器在预测存储回归中断；改用无该容量限制的隔离容器后，完整 93 项最终通过。GitHub CI 在 8b425c4 发现一处过时测试断言；仅更新该断言以匹配显式预声明留出窗口语义。修正提交 5798c06 的 exact-head CI 已通过：4,062 passed、32 skipped、43 warnings，覆盖率 70.73%。


## 2026-11-11 回填期间可推进项的补充

- P107/A107 已有生产验收，不需因五年回填未完成而重做。
- P105 排程与官方通知已部署；仍需等自然比赛任务产生带 P104 回执的预测组。该自然运行闭环不能用手工伪造样本替代。
- P106/P111/P114 的代码、点时校验和评价框架已通过主线 CI；真实效果仍取决于具备时间证据、已验证赛季身份、同一预测时点赔率的样本。
- P108 静态导出覆盖复核已补充；来源导出仍只有短窗口及少量球员事实，只能用于解析/映射候选，不能导入为已验证事实。详见[静态覆盖审计](/Volumes/Nas/FQP/plans/model-modernization-20261016/integrated/P108/07-source-export-sample-audit-20261111/REPORT.md)。回填中的 Titan SQLite 未打开。
- P105 139 免备份门禁与迁移格式回归 **143 passed**。门禁要求精确上下迁移摘要、非事务演练、原始 EXPLAIN JSON 绑定恢复查询 SHA、`ai_job_runs` 扫描与执行协议条件、服务器主机 Ed25519 签名及跨命名空间拒绝、目录状态、业务行不变及 DOWN/重建验证。独立复核通过；本地修改尚未提交/推送，exact-head CI 尚待完成，也未部署。


## 2026-11-13 production release attempt

- The exact `ef1831b64ea5177ab776d0a00a088eaa5d36f116` candidate passed GitHub CI, and the signed migration-139 evidence gate passed before apply. Server preflight found clean `main`, healthy prior services, `/health/ready` with database and Redis OK, and 44% root-disk use. No backup was created.
- The release runner stopped all application services and Nginx, checked out the candidate, installed frontend packages with zero reported vulnerabilities, and built the frontend. Migration 139 then stopped at catalog validation: production `pg_get_expr` renders the `varchar` predicates as `job_code::text` and `status::text`; the validator accepted only the uncast form. The code was restored to server revision `3ed1ba8490fc11a67ce31457644c113050ab02af`; the release fail-safe left all four services inactive.
- Read-only verification found no migration-139 ledger row and found `idx_ai_job_runs_prediction_recovery` valid and ready. Its predicate matches the migration semantically, but its state before the attempt was not captured, so whether the index was pre-existing or created during the failed attempt is unknown. No business-row writes were made.
- The fix now strips implicit `::text` casts only outside quoted values and compares the complete pinned predicate. Regression cases accept the production catalog form and reject altered literals, status values, and extra filters. The release-policy suite passed 149 tests; the configured P106/P114 isolated PostgreSQL suite passed 233 tests; V4 test/lint/typecheck regression is 0/0. Commit `005bc0373b4a21d8345bc4ad11cb67b291f15a7a` passed both GitHub CI jobs.
- The release fail-safe intentionally left all four services stopped and wrote a rollback marker for restored revision `3ed1ba8490fc11a67ce31457644c113050ab02af`. The runner previously required the old services to be active, blocking a safe retry. A recovery-only entry now requires that exact rollback marker, an ancestor target, and all four services inactive; it keeps services stopped on failure and starts the target services and Nginx only on success. The release-policy suite, including the recovery guard test, passed 150 tests; Bash syntax, Ruff, and independent review pass. This follow-up still needs exact-head CI, a fresh target-bound signed release report, and production retry.
