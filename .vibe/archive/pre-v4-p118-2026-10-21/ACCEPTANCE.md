# A118：前端构建开发依赖的安全发布与回退

1. 发布分类器只允许 `apps/frontend/package.json` 中 `devDependencies.vite` / `devDependencies.vitest` 的版本变更，以及这两个包依赖闭包内锁文件的 `dev: true` 包变化。
2. 拒绝前端生产 `dependencies`、其他 manifest 配置、非 dev-only 锁项、Python/Node/模型桥接依赖或运行时文件变更。
3. `--plan` 明确标注前端开发依赖刷新；常规依赖变化仍保持拒绝。
4. 部署失败并回退时，在旧提交 checkout 后执行旧锁文件的 `npm ci --ignore-scripts`，再构建旧版本；依赖恢复失败时停止 Nginx，退出并输出 `ROLLBACK_REQUIRED`。
5. 保持当前 release evidence、服务健康、迁移和保护 HTTP 烟测门禁。无待执行迁移时不要求新数据库备份；有迁移时继续要求新鲜备份和副本演练。
6. 分类器的允许/拒绝路径、无关 dev lock 项拒绝、首次暂存目录加载分类器、runner shell 语法、全套 GitHub CI 通过；部署后验证服务、`/health/ready`、release ID 和关键路由。

状态：`implementation_in_progress`；PR #20 已合并。服务器暂未更新。
