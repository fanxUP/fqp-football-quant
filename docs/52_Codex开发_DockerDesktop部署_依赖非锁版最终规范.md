# 52_Codex开发_DockerDesktop部署_依赖非锁版最终规范（历史归档）

> 本文保留原始 Docker Desktop 方案用于历史追溯，已于 2026-07-10 废止，不得用于当前项目启动或部署。当前唯一运行口径为 `docs/54_本机运行与DockerDesktop弃用说明.md` 与 `./ops/local/run_local_dev.sh`。

## 1. 最终要求

本项目作为本地个人足球量化系统，最终采用以下执行规则：

- 使用 Codex 完成项目开发、维护、修复、测试、重构和代码审查。
- 使用 Docker Desktop 作为本地部署和运行入口。
- 运行服务由 Docker Compose 编排，包括 backend、frontend、postgres、redis、worker、scheduler。
- 所需组件依赖不指定固定版本。
- 本地计算机已经安装的组件，优先使用当前本机版本。
- 本地计算机未安装的组件，按官方安装渠道安装当前最新版。
- 所有 AI 计算、特征构建、模型训练、推荐生成、定时数据采集任务，都在本地 Scheduler/Worker 容器中运行；Codex 负责编写、修改、测试、审查这些任务。

## 2. 为什么不锁版本

本项目定位为个人长期使用程序，不追求多人团队生产级版本冻结，而是追求：

- 本地部署简单；
- 后期升级方便；
- 不被旧依赖阻塞；
- Codex 可持续根据最新版依赖修复代码；
- Docker Desktop 一键拉取和运行更顺手。

因此，项目取消以下固定版本写法：

```text
fastapi==0.115.0
postgres:15
redis:7
python:3.11-slim
```

改为：

```text
fastapi
postgres
redis
python
```

## 3. 需要保留的稳定性措施

不锁版本并不等于不记录版本。项目必须记录实际运行环境：

```text
data/runtime_version_snapshot.json
```

该文件记录：

- Docker Desktop / Docker CLI 当前版本；
- Docker Compose 当前版本；
- Python 当前版本；
- Node / npm 当前版本；
- Codex CLI 当前版本；
- 项目启动时间；
- 当前环境缺失组件。

它的作用是排查问题，不是锁死版本。

## 4. Docker Desktop 部署逻辑

本地部署只保留一个主入口：

```bash
cd ops/local
./run_local_stack.sh
```

启动顺序：

```text
1. 检查本机环境；
2. 生成 runtime_version_snapshot.json；
3. 创建本地数据目录；
4. docker compose pull 拉取当前 latest 镜像；
5. docker compose up --build 启动所有服务；
6. backend 暴露 127.0.0.1:8000；
7. frontend 暴露 127.0.0.1:3000；
8. scheduler 和 worker 在本地容器中执行定时任务。
```

## 5. Codex 开发边界

Codex 负责：

- 生成和修改代码；
- 维护 Dockerfile / Compose / 配置；
- 编写采集器；
- 编写模型脚本；
- 编写 Scheduler / Worker 任务；
- 修复依赖升级造成的错误；
- 编写测试；
- 执行代码审查；
- 根据日志定位问题。

Codex 不直接负责：

- 代替长期生产守护进程；
- 未经用户确认删除数据库；
- 未经用户确认改动真实实票记录；
- 绕过官方数据边界；
- 承诺模型盈利。

## 6. AI 计算与定时采集执行方式

所有 AI 计算和定时采集任务进入本地任务队列：

```text
official_data_refresh
odds_snapshot_refresh
feature_snapshot_build
weather_refresh
lineup_injury_refresh
model_prediction_run
recommendation_generation
ticket_settlement
review_generation
backtest_run
```

执行者：

```text
Scheduler：定时触发
Worker：实际运行
Codex：开发、维护、调试、修复任务代码
```

## 7. 冲突修复说明

之前的项目方案中存在“依赖版本固定”和“本地最新依赖优先”的潜在冲突。最终规范以本文件为准：

- 不再固定依赖版本；
- 不再固定 Docker 镜像版本；
- 不再要求 Python 3.11 / PostgreSQL 15 / Redis 7 等固定环境；
- 只要求组件类型正确，版本使用本地当前版本或当前最新版；
- 兼容性问题由 smoke test 和 Codex 修复流程解决。

## 8. 验收标准

本规范完成后，项目必须满足：

- `requirements.txt` 不含 `==` 固定版本；
- Docker Compose 不含 `postgres:15`、`redis:7` 等固定 tag；
- Dockerfile 不含 `python:3.11-slim` 等固定 tag；
- 本地启动脚本会检查环境；
- 本地启动脚本会生成版本快照；
- README 明确 Codex + Docker Desktop + 非锁版依赖策略；
- smoke test 能在 Docker Desktop 中执行。
