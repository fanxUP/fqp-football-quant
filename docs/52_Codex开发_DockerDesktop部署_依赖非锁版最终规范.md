# 52. 早期 Docker 与依赖策略归档索引

本页保留历史文件名作为索引，早期混合部署步骤已删除。

1. 当前启动与部署按 [54 号运行规范](54_本机运行与DockerDesktop弃用说明.md) 选择实际入口。原因：旧 `run_local_stack.sh deploy` 及配套 Docker 手册已不存在。
2. 依赖约束按现有 requirements、package.json、lockfile 和 CI 运行版本判断。原因：Python 3.14、Node 24 和部分前端精确版本已经受约束，“一律不锁版本/安装最新版”不符合当前代码。
3. Codex 开发维护代码，常驻服务执行长期任务。原因：这是当前 Scheduler/Worker 与开发工具之间仍然有效的职责边界。
