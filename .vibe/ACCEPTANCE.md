# A118：前端构建开发依赖的安全发布与回退

1. 发布分类器只允许 `apps/frontend/package.json` 中 `devDependencies.vite` / `devDependencies.vitest` 的版本变更，以及这两个包依赖闭包内锁文件的 `dev: true` 包变化。
2. 拒绝前端生产 `dependencies`、其他 manifest 配置、非 dev-only 锁项、Python/Node/模型桥接依赖或运行时文件变更。
3. `--plan` 明确标注前端开发依赖刷新；常规依赖变化仍保持拒绝。
4. 部署失败并回退时，在旧提交 checkout 后执行旧锁文件的 `npm ci --ignore-scripts`，再构建旧版本；依赖恢复失败时停止 Nginx，退出并输出 `ROLLBACK_REQUIRED`。
5. 保持当前 release evidence、服务健康、迁移和保护 HTTP 烟测门禁。无待执行迁移时不要求新数据库备份；有迁移时继续要求新鲜备份和副本演练。
6. 分类器的允许/拒绝路径、无关 dev lock 项拒绝、首次暂存目录加载分类器、runner shell 语法、全套 GitHub CI 通过；部署后验证服务、`/health/ready`、release ID 和关键路由。

状态：P118 已随 PR #21 合并。本轮 P119 的验收标准如下。

# A119：发布并回滚 Nginx 前端静态文件

1. `--apply` 在停止服务之前确认 `/var/www/fqp` 可写且不是符号链接；当前 `--plan` 和发布证据、迁移、备份、HTTP 烟测门禁保持不变。
2. 前端构建产物先逐项同步到网页目录，缺失或内容变化的文件通过同目录临时文件和原子替换发布；旧文件保留，不执行删除。
3. 同步完成后检查入口引用的本地 JS/CSS 文件存在，最后原子替换 `index.html`，避免入口先引用尚未发布的资源。
4. 发生发布失败时，回滚逻辑在旧提交重建后恢复其静态资源。若恢复失败，停止 Nginx 并输出 `ROLLBACK_REQUIRED`。
5. 验证范围为 `bash -n ops/server/deploy.sh`、内嵌 Python `ast.parse` 和 `git diff --check`；不运行测试套件，不执行生产部署。
