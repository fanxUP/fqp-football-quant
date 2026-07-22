# 唯一工作区、Git 同步与 Docker Desktop 部署规范

## 唯一事实来源

- 唯一工作区：`/Users/fan/Downloads/足球量化`
- 唯一远端：`https://github.com/fanxUP/fqp-football-quant.git`
- 唯一 Docker Compose 文件：`ops/local/docker-compose.local.yml`
- 唯一部署入口：`./ops/local/run_local_stack.sh deploy`
- 唯一版本边界：当前 Git 分支已提交并推送的 SHA

旧 iCloud 副本和其他复制目录不得再修改、提交或启动服务。`ops/docker-compose.yml` 仅保留历史兼容，不用于本机部署；禁止手工执行其他 `docker compose up` 命令。

## 固定访问端口

| 服务 | 宿主机地址 | 容器内部端口 |
| --- | --- | --- |
| 前端 | `http://127.0.0.1:8066` | `3000` |
| 后端 | `http://127.0.0.1:8006` | `8000` |
| Grafana | `http://127.0.0.1:3001` | `3000` |

容器内部端口不是浏览器访问端口。若临时通过 `FQP_FRONTEND_PORT` 或 `FQP_BACKEND_PORT` 覆盖宿主机端口，任务结束后必须恢复默认值，禁止把临时端口写入另一份 Compose 文件。

## 本机开发

```bash
cp .env.local.example .env.local
./ops/local/run_hybrid_dev.sh
```

该模式在本机运行前端和后端，但只使用 Docker 中的 PostgreSQL、Redis、Worker 与 Scheduler。Docker PostgreSQL `127.0.0.1:5433/fqp` 是本项目唯一数据库；不得在宿主机 `5432` 再创建同名数据库。容器中的前后端会自动停止并释放 `8066/8006`，定时任务仍只有一套。

## Docker Desktop 部署

```bash
./ops/local/run_local_stack.sh deploy
```

脚本依次确认工作区没有未提交或未跟踪文件、推送当前分支到 GitHub、比对远端提交 SHA、重建 Compose 服务，并检查 `8006/health` 和 `8066` 前端首页。任何 Git 同步失败都会阻止 Docker 启动。

数据库、Redis 和备份位于宿主机 `data/` 下；不提交 Git，也不会因容器重建而自动删除。

## 防止代码分岔的固定流程

1. 开始修改前进入唯一工作区，运行 `git status --short --branch`，在当前任务分支继续，不复制项目目录。
2. 一次提交只包含一个完整、可运行的业务改动；测试通过后使用中文 Commit Message 提交。
3. 部署时只运行 `./ops/local/run_local_stack.sh deploy`。脚本负责推送当前分支、核对 GitHub SHA、构建和健康检查。
4. 不在容器内改源码，不从 Docker 容器反向复制代码，不在旧目录提交同名分支。
5. 新任务如需切换分支，先保证当前分支已提交并推送；禁止靠复制目录保存未提交改动。

## Docker 清理边界

- 容器和本项目构建镜像是可删除、可重建资源。
- `data/postgres`、`data/redis`、`data/backups` 和 `fqp-local_grafana_data` 是运行数据，除非明确要求清空数据，否则不得删除。
- 只清理 Compose 项目名为 `fqp-local` 或镜像标签 `com.docker.compose.project=fqp-local` 的资源，不影响其他项目。
- 本机 Scheduler/Worker 与 Docker Scheduler/Worker 不得同时运行。
- API 密钥仅保存在被 Git 忽略的 `.env.local` 中。
