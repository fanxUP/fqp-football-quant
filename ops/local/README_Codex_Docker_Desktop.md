# 本机开发与 Docker Desktop 运行说明

本机工作目录是唯一开发源；Docker Desktop 是可重建的运行环境。每一次部署都必须先把当前分支推送到 GitHub，随后才允许重建容器。

唯一工作区为 `/Users/fan/Downloads/足球量化`，前端访问端口为 `8066`，后端访问端口为 `8006`。完整的 Git 防分岔规则见 `docs/54_本机运行与DockerDesktop弃用说明.md`。

是否启动 Docker 由任务需要决定，不要求用户另行给出特定口令。快速开发和单元测试适合本机环境；完整服务栈、长期任务、发布验收和环境复现适合 Docker。当前推荐使用混合开发：前后端在本机热更新，PostgreSQL、Redis、Worker、Scheduler 留在 Docker。无论采用哪种方式，都必须避免本机与容器中的 Scheduler/Worker 同时运行。

## 运行原则

- 在本机修改、测试并提交代码，不在容器内直接改源码。
- 使用 `./ops/local/run_local_stack.sh deploy` 部署。脚本会拒绝脏工作区，验证 GitHub 分支 SHA，再执行 Compose 重建与健康检查。
- 只使用 `ops/local/docker-compose.local.yml`；`ops/docker-compose.yml` 是历史兼容文件，不用于本机部署。
- `data/postgres`、`data/redis` 与 `data/backups` 是本机持久数据，不提交 Git；升级或清理 Docker 前先备份 `data/backups`。
- 容器带有 Git SHA 标签，可用 `docker inspect` 核对运行版本。
- 不手动执行会绕过 GitHub 校验的 `docker compose up`；这会破坏版本可追溯性。

## 调度与监控边界

- Docker 模式下 Scheduler 负责定时任务，Worker 是赔率高频调度的唯一执行者；`FQP_ODDS_DISPATCH_OWNER=worker` 防止双重轮询。
- 混合开发模式同样只保留 Docker Worker/Scheduler；容器通过 `host.docker.internal:8006` 检查本机后端健康状态。
- 本机热开发模式没有独立 Worker，Scheduler 默认接管赔率调度，保证业务完整。
- Scheduler 与 Worker 分别写入 `.runtime/scheduler_heartbeat.json` 和 `.runtime/worker_heartbeat.json`；数据监控页使用实时心跳，不使用固定“正常”值。
- 容器和 PostgreSQL 使用 UTC，赛程、开赛、停售、竞赛和日报统一以 `Asia/Shanghai` 业务日期计算。

## 日常命令

```bash
# 推荐：本机前后端 + Docker 数据和定时任务
./ops/local/run_hybrid_dev.sh

# 推荐长期使用：注册登录自启并自动恢复前后端进程
./ops/local/manage_hybrid_service.sh start
./ops/local/manage_hybrid_service.sh status
./ops/local/manage_hybrid_service.sh restart

# 停止前后端并取消登录自启
./ops/local/manage_hybrid_service.sh stop

# 仅启动本机前后端（仍连接 Docker PostgreSQL，数据容器需已运行）
./ops/local/run_local_dev.sh

# 推送并同步 Docker Desktop
./ops/local/run_local_stack.sh deploy

# 运行状态、日志、仅停止本项目
./ops/local/run_local_stack.sh status
./ops/local/run_local_stack.sh logs
./ops/local/run_local_stack.sh stop
```

`com.fqp.hybrid` 只管理本机前后端；PostgreSQL、Redis、Worker、Scheduler 仍由
Docker Desktop 管理。因为项目位于 macOS 的“下载”保护目录，必须在“系统设置 →
隐私与安全性 → 完全磁盘访问权限”中启用 `/bin/bash`，否则 launchd 无法读取项目。
不要为了登录自启复制第二份项目，否则会重新引入代码和数据库运行边界错乱。
前后端自动恢复使用 `--no-recreate`，不会重启正在执行任务的 Worker/Scheduler；
容器版本更新只通过显式部署或经过任务空闲检查的同步操作完成。

## 维护

如果新部署异常，先使用 `logs` 保存证据；代码问题通过 Git 提交修复后重新部署，数据问题从 `data/backups` 恢复。不要删除 `data/` 目录或 Docker 卷来替代回滚。
