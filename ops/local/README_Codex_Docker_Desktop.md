# 本机开发与 Docker Desktop 运行说明

本机工作目录是唯一开发源；Docker Desktop 是可重建的运行环境。每一次部署都必须先把当前分支推送到 GitHub，随后才允许重建容器。

## 运行原则

- 在本机修改、测试并提交代码，不在容器内直接改源码。
- 使用 `./ops/local/run_local_stack.sh deploy` 部署。脚本会拒绝脏工作区，验证 GitHub 分支 SHA，再执行 Compose 重建与健康检查。
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
