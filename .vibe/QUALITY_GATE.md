# P108-01 质量门禁

- 只在 `main` 顺序开发，不创建分支或 worktree。
- 仅允许 SCOPE_LOCK 中的 8 个路径；最多 2 个 migration SQL 文件。
- RED/GREEN/REFACTOR；固定 CSV 和隔离 PG16 夹具，不调用付费 API。
- 数据库角色 `fqp` 只能读取映射；down 迁移不得丢弃任何映射或事件。
- 完成本地回归、静态检查、scope/budget、独立只读审查、GitHub exact-head CI 后才进入发布评估。
- 本批不做生产迁移、球员导入或模型 rollout。
