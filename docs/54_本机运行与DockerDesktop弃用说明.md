# 唯一工作区与全本机运行规范

## 唯一事实来源

- 唯一工作区：`/Users/fan/Downloads/足球量化`
- 唯一远端：`https://github.com/fanxUP/fqp-football-quant.git`
- 唯一启动入口：`./ops/local/manage_local_stack.sh start`
- 唯一数据库：Homebrew PostgreSQL `127.0.0.1:5432/fqp`
- 唯一代码版本边界：当前 Git 分支已提交并推送的 SHA

旧 iCloud 副本和其他复制目录不得再修改、提交或启动服务。Docker Desktop 已从当前运行架构退役，项目不保留 Compose 启动入口。

## 本机端口

| 服务 | 地址 |
| --- | --- |
| 前端 | `http://127.0.0.1:8066` |
| 后端 | `http://127.0.0.1:8006` |
| PostgreSQL | `127.0.0.1:5432` |
| Redis | `127.0.0.1:6379/0` |

## 首次安装与启动

```bash
cp .env.local.example .env.local
./ops/local/setup_local_latest_macos.sh
./ops/local/manage_local_stack.sh start
```

`com.fqp.local-stack` 使用 launchd 长期运行，监管后端、前端、Worker 和 Scheduler。PostgreSQL 与 Redis 由 Homebrew services 管理。

## 日常操作

```bash
./ops/local/manage_local_stack.sh status
./ops/local/manage_local_stack.sh restart
./ops/local/manage_local_stack.sh stop
```

数据库迁移：

```bash
./ops/local/apply_local_migrations.sh
```

守护进程日志位于 `.runtime/local-stack.launchd.out.log` 和 `.runtime/local-stack.launchd.err.log`。

## 防止分岔和重复任务

1. 修改前进入唯一工作区，运行 `git status --short --branch`，不复制项目目录。
2. 每次提交包含一个完整可运行改动，测试通过后使用中文 Commit Message。
3. Worker 是赔率高频调度的唯一所有者，Scheduler 使用本机心跳；不单独再启动第二套定时任务。
4. `.env.local` 和 `data/` 不提交 Git。数据库结构变更通过 `sql/` 迁移管理。
5. 新任务切换分支前，先确保当前分支已提交并推送，禁止靠复制目录保存未提交改动。

## 数据保护

- `data/backups/` 保留数据库全量备份和 SHA-256 校验文件。
- 删除、升级或恢复前先生成备份，并在独立数据库中验证可恢复性。
- 历史备份和恢复失败记录是审计证据，不为了让监控变绿而删除。
