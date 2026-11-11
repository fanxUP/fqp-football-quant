# 发布质量门禁：赔率走势第三方品牌对照

- 单分支 `main`；不创建功能分支。
- 固定样本后端/前端回归、Ruff、mypy、TypeScript 和生产构建通过。
- 独立只读审查通过；无迁移、供应商调用或业务数据写入。
- GitHub Actions `CI` 在 `main` 的精确发布提交上通过 `test`、`lint-and-typecheck`。
- 正式发布使用 `ops/server/deploy.sh`；保留回滚提交，确认无待迁移项，执行健康和保护路由只读 smoke。
