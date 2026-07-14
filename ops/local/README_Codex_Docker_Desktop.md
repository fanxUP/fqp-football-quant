# 本机开发与 Docker Desktop 运行说明

本机工作目录是唯一开发源；Docker Desktop 是可重建的运行环境。每一次部署都必须先把当前分支推送到 GitHub，随后才允许重建容器。

唯一工作区为 `/Users/fan/Downloads/足球量化`，前端访问端口为 `8066`，后端访问端口为 `8006`。完整的 Git 防分岔规则见 `docs/54_本机运行与DockerDesktop弃用说明.md`。

是否启动 Docker 由任务需要决定，不要求用户另行给出特定口令。快速开发和单元测试适合本机环境；完整服务栈、长期任务、发布验收和环境复现适合 Docker。无论采用哪种方式，都必须避免本机与容器中的 Scheduler/Worker 同时运行。

## 运行原则

- 在本机修改、测试并提交代码，不在容器内直接改源码。
- 使用 `./ops/local/run_local_stack.sh deploy` 部署。脚本会拒绝脏工作区，验证 GitHub 分支 SHA，再执行 Compose 重建与健康检查。
- 只使用 `ops/local/docker-compose.local.yml`；`ops/docker-compose.yml` 是历史兼容文件，不用于本机部署。
- `data/postgres`、`data/redis` 与 `data/backups` 是本机持久数据，不提交 Git；升级或清理 Docker 前先备份 `data/backups`。
- 容器带有 Git SHA 标签，可用 `docker inspect` 核对运行版本。
- 不手动执行会绕过 GitHub 校验的 `docker compose up`；这会破坏版本可追溯性。

## 日常命令

```bash
# 本机热开发（不启动 Docker）
./ops/local/run_local_dev.sh

# 推送并同步 Docker Desktop
./ops/local/run_local_stack.sh deploy

# 运行状态、日志、仅停止本项目
./ops/local/run_local_stack.sh status
./ops/local/run_local_stack.sh logs
./ops/local/run_local_stack.sh stop
```

## 维护

如果新部署异常，先使用 `logs` 保存证据；代码问题通过 Git 提交修复后重新部署，数据问题从 `data/backups` 恢复。不要删除 `data/` 目录或 Docker 卷来替代回滚。
