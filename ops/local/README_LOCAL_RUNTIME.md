# FQP 本机运行手册

本项目前端、后端、Worker、Scheduler、PostgreSQL 和 Redis 全部在 macOS 本机运行，无需 Docker Desktop。

## 快速启动

```bash
cp .env.local.example .env.local
./ops/local/setup_local_latest_macos.sh
./ops/local/manage_local_stack.sh start
```

## 管理命令

```bash
./ops/local/manage_local_stack.sh status
./ops/local/manage_local_stack.sh restart
./ops/local/manage_local_stack.sh stop
```

## 数据库

- 唯一数据库：`postgresql://fqp@127.0.0.1:5432/fqp`
- 增量迁移：`./ops/local/apply_local_migrations.sh`
- 备份目录：`data/backups/`
- Redis：`redis://127.0.0.1:6379/0`

## 故障排查

```bash
tail -f .runtime/local-stack.launchd.err.log
tail -f .runtime/local-stack.launchd.out.log
curl -f http://127.0.0.1:8006/health
curl -f http://127.0.0.1:8066/
```

守护进程会独立恢复崩溃的应用子进程。如果数据库或 Redis 不可用，先运行 `brew services list`，再使用 `manage_local_stack.sh restart`。
