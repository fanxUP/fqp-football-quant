# P132 质量门禁

- 当前唯一分支必须是 `main`，工作区无未解释改动。
- `vibe scope check`、`vibe budget check` 通过。
- 固定样本与隔离 PostgreSQL 验证迁移前后 view 契约及应用角色权限。
- SQL 129 在 disposable PostgreSQL 上按生产迁移器事务执行、回滚，并证明旧目录数据不变。
- migration policy 对 129 精确 SHA、生效顺序、近期演练报告和无备份授权作 fail-closed 校验。
- 安全审查、独立只读代码审查、main 精确提交 CI 均通过后才能发布。
- 部署后确认服务健康、迁移已应用、alias 表仍为空；不得把 P133 数据写入当作本批已完成。
