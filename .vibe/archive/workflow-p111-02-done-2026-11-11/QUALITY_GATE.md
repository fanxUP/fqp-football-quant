# P111-02 发布质量门禁

- 单分支 `main`，不创建 topic branch/worktree。
- 跑固定样本单元回归、现有预测组存储回归和经数据库注释标记的 P111-02 隔离 PostgreSQL 端到端回归。
- Ruff、format、mypy、diff 检查通过；V4 scope/budget 通过。
- 独立审查确认 P106 run/model/group/evaluation provenance、事务所有权和 shadow 未激活路径。
- 不调用真实供应商、不运行 shadow 预测、不启用模型；P111 适配器不连接生产库。发布脚本只运行既有健康检查与保护路由的只读 smoke，不写入业务数据、不改服务配置、调度或数据库。
- 提交前完成 GitHub `CI` exact-head 检查；部署前通过 `deploy.sh` 预检并收集回滚、保护路由和当前服务健康证据。
