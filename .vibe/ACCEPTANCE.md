# 当前工程验收：P108-05A / P111 / P114 / P105 恢复性能

验收对象是本地未提交工作树；基于 `main` 的 HEAD `037fdbf971924bfc57d9a16c327f4fd2bf2bead3`，树指纹 `e289410aedde3b14abfd25b0faf17b0b45b079f4bf321dfac4514e9d301473a6`。此结果不等同于 GitHub exact-head CI、服务器发布、数据完整或模型效果验收。

## 已通过

- [x] P105 预测任务恢复及预测运行 PostgreSQL 回归：93 passed；仅使用一次性 loopback PostgreSQL 16 `fqp_p106_test_*` 数据库。
- [x] P106/P111/P114 训练 manifest、动态球队候选、backtest/replay 固定样本回归：183 passed；新增覆盖数据库 loader 的 JSON 回执和 ISO 时间戳进入预先声明 final window 并成功评估。
- [x] P111 P106 run/group/replay 隔离 PostgreSQL 集成回归：1 passed，使用 loopback PostgreSQL 16 测试库。
- [x] 本地数据库运行时回归：53 passed。
- [x] 合计 380 项当前树回归通过，无失败或跳过：P105 93、P106/P111/P114 183、P111 PostgreSQL 集成 1、P104/P114 observation PostgreSQL 50、本地运行时 53。
- [x] Ruff 检查全部 93 个变更 Python 文件通过；本轮改动的 3 个 Python 文件格式检查通过；training manifest 与 backtest engine 的 mypy、定向 compileall、`git diff --check` 通过。
- [x] V4 scope：96 个变更文件全部在允许范围内；预算按完整 baseline delta 修正并通过（96/96 文件、4/4 新文件、0 依赖新增、2/2 SQL 迁移文件）。
- [x] 在一次性 PostgreSQL 16 数据库运行迁移器：139 并发索引成功创建，valid/ready 与 checksum ledger 通过；随后只读计划显示无待迁移；down 文件成功移除测试索引。该演练使用最小隔离表和模拟的 135 条既有 migration ledger，不是完整生产副本演练。
- [x] P108 球员 shadow 仍 withheld；P111/P114 不晋升模型、不改正式预测概率。

## 尚未完成

- [ ] 变更仍未提交；当前精确工作树尚无对应的 GitHub CI 结果。已有 `7aeb1fe` CI 属于更早的代码树，不能替代当前树验证。
- [ ] 服务器发布及发布后只读 smoke 未执行；本批没有访问生产数据库或应用迁移 139。
- [ ] A108 球员事实链、A111 真实模型效果、A114 点时样本外效果、A115 前瞻窗口仍需各自的数据证据。
- [ ] 五年回填完整性与关联覆盖率未在本验收中读取或确认。

新增 loader 回归使用数据库 JSONB 输出形态的固定映射和时区 ISO 字符串，实际经过 `load_research_matches` 与固定窗口评估；另外，本轮也在专用隔离 observation PostgreSQL 库重新运行了 50 项 P104/P114 回归。

第一次运行使用 1 GiB tmpfs 的测试 PostgreSQL，容器在预测存储回归中断；改用无该容量限制的隔离容器后，完整 93 项最终通过。一次全变更文件 Ruff format 探测显示 73 个既有文件需要整体重排，因此没有对这些文件做批量格式化；仅执行项目配置的关键文件格式检查，避免扩大 diff。
