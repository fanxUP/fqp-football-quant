# 本机 Scheduler

项目定时任务使用本机 Python 和 PostgreSQL，不使用 Docker Desktop、Redis 或 Celery。

启动：

```bash
./ops/local/run_local_scheduler.sh
```

只检查依赖、不启动长驻进程：

```bash
./ops/local/run_local_scheduler.sh --check
```

后台生命周期管理（通过 macOS `launchd` 托管，Codex/终端退出后仍持续运行）：

```bash
./ops/local/manage_scheduler.sh start
./ops/local/manage_scheduler.sh status
./ops/local/manage_scheduler.sh stop
```

日志写入 `.runtime/scheduler.launchd.out.log` 与 `.runtime/scheduler.launchd.err.log`，PID 写入 `.runtime/scheduler.pid`。首次 `start` 会在当前用户的 `~/Library/LaunchAgents/` 生成 `com.fqp.scheduler.plist`。

> `launchd` 无法读取 iCloud Drive 中的项目目录。若项目仍位于 `Library/Mobile Documents/`，管理脚本会拒绝后台启动，避免无限重启；请先将完整项目迁移到非 iCloud 路径，或在保持打开的交互式终端中运行 `./ops/local/run_local_scheduler.sh`。

脚本会校验：

- 项目 `.venv/bin/python` 为 Python 3.11+
- `.env.local` 存在且 `DATABASE_URL` 指向 `127.0.0.1`
- 本机 PostgreSQL 可连接
- APScheduler 已安装

Scheduler 负责触发任务；任务自身负责写入 `ai_job_runs` 的统一台账，已接入台账的任务不会被 Scheduler 重复包装。
