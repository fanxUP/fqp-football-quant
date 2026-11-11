# 当前工程验收：P108-05A / P111 / P114 / P105 恢复性能

验收对象是提交 `a09a702b7928cfa336f63fdfd55fdcadfdbeb298` 上的本地格式修正工作树；业务树指纹 `cc4db7df396ae2fa1a3ffc2c7e1840d5eae0854184454a3a218a5a327230625f`。此结果不等同于后续提交的 GitHub exact-head CI、服务器发布、数据完整或模型效果验收。

## 已通过

- [x] P105 预测任务恢复及预测运行 PostgreSQL 回归：93 passed；仅使用一次性 loopback PostgreSQL 16 `fqp_p106_test_*` 数据库。
- [x] P106/P111/P114 训练 manifest、动态球队候选、backtest/replay 固定样本回归：183 passed；新增覆盖数据库 loader 的 JSON 回执和 ISO 时间戳进入预先声明 final window 并成功评估。
- [x] P111 P106 run/group/replay 隔离 PostgreSQL 集成回归：1 passed，使用 loopback PostgreSQL 16 测试库。
- [x] 本地数据库运行时回归：53 passed。
- [x] 合计 380 项当前树回归通过，无失败或跳过：P105 93、P106/P111/P114 183、P111 PostgreSQL 集成 1、P104/P114 observation PostgreSQL 50、本地运行时 53。
- [x] 全仓库 Ruff check 与 format check 通过；training manifest、动态球队、回测四模块 mypy、定向 compileall、`git diff --check` 通过。为修复 CI 报告的格式门禁，73 个已变更 Python 文件已按项目配置格式化。
- [x] V4 scope：当前检查发现 27 个变更业务文件，均在 96 文件预算内；变更预算通过（27/96 文件、4/4 新文件、0 依赖新增、2/2 SQL 迁移文件）。
- [x] 在一次性 PostgreSQL 16 数据库运行迁移器：139 并发索引成功创建，valid/ready 与 checksum ledger 通过；随后只读计划显示无待迁移；down 文件成功移除测试索引。该演练使用最小隔离表和模拟的 135 条既有 migration ledger，不是完整生产副本演练。
- [x] P108 球员 shadow 仍 withheld；P111/P114 不晋升模型、不改正式预测概率。

## 尚未完成

- [ ] 提交 `a09a702` 已推送，但其 GitHub CI 在 Ruff format check 失败；73 个文件的格式修正尚未提交，修正后的 exact-head CI 待跑。该失败发生在测试阶段之前，当前树本地 380 项回归通过。
- [ ] 服务器发布及发布后只读 smoke 未执行；本批没有访问生产数据库或应用迁移 139。
- [ ] A108 球员事实链、A111 真实模型效果、A114 点时样本外效果、A115 前瞻窗口仍需各自的数据证据。
- [ ] 五年回填完整性与关联覆盖率未在本验收中读取或确认。

新增 loader 回归使用数据库 JSONB 输出形态的固定映射和时区 ISO 字符串，实际经过 `load_research_matches` 与固定窗口评估；另外，本轮也在专用隔离 observation PostgreSQL 库重新运行了 50 项 P104/P114 回归。

第一次运行使用 1 GiB tmpfs 的测试 PostgreSQL，容器在预测存储回归中断；改用无该容量限制的隔离容器后，完整 93 项最终通过。随后 GitHub CI 明确要求全仓库格式检查，现已格式化该门禁指出的 73 个文件并重跑本地回归；修正后的 GitHub CI 仍待提交触发。
