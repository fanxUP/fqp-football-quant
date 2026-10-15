# FQP macOS 原生运行手册

本页仅适用于 `ops/local/` 原生栈。它使用 Homebrew PostgreSQL 18、Redis 和 launchd，默认前端 8066、后端 8080。

## 使用规则

1. 首次安装在项目工作树内准备私密 `.env.local`，再使用下列入口。原因：脚本根据自身位置定位项目及环境文件。
2. 启动、重启和迁移前核对目标数据库及授权范围。原因：`manage_local_stack.sh start` 会执行增量迁移，并非只读操作。
3. 使用同一管理入口控制原生栈，避免另开重复 Scheduler/Worker。原因：`com.fqp.local-stack` 已监管四个应用进程。
4. 初始登录后修改公开默认密码 `admin123`。原因：默认密码只能用于首次配置。
5. 全量备份按显式需要调用 `scripts/jobs/verify_backup.py`，以 `BACKUP_DIR` 或默认 `./backups` 为准。原因：当前代码没有每日全量自动备份任务。

## 安装与启动

```bash
cp .env.local.example .env.local
./ops/local/setup_local_latest_macos.sh
./ops/local/manage_local_stack.sh start
```

## 管理

```bash
./ops/local/manage_local_stack.sh status
./ops/local/manage_local_stack.sh restart
./ops/local/manage_local_stack.sh stop
```

原生入口校验 PostgreSQL 为 `127.0.0.1:5432/fqp`、Redis 为 `127.0.0.1:6379/0`；这些是本入口的约束，不是其他环境的全局地址。

## 排查入口

应用日志：`.runtime/local-stack.launchd.err.log`、`.runtime/local-stack.launchd.out.log`。原生默认健康地址：`http://127.0.0.1:8080/health`，前端：`http://127.0.0.1:8066/`。

- 数据库或 Redis 不可用时先核对依赖状态和日志，再决定是否重启。原因：应用守护进程只能恢复应用子进程，不能修复数据库数据。
- 恢复操作使用已核实的备份和目标库。原因：归档校验与恢复验证是两个独立结果。
