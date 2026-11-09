# P108-02 质量门禁

- 仅在 `main` 顺序开发，不建分支或 worktree；严格遵守 7 路径和 2 migration 文件预算。
- RED/GREEN/REFACTOR；只用合成固定样本与显式隔离 PostgreSQL 16。
- `fqp` 对事实表与视图仅读；down 不得丢弃事实。
- 迁移演练验证 up/down/up、记录存在时 down 拒绝、原事实保留、约束/权限及时间截面查询。
- 完成本地回归、lint/format/mypy、scope/budget、独立只读代码和迁移审查、GitHub exact-head CI 后再评估后续发布；本批不发布。
