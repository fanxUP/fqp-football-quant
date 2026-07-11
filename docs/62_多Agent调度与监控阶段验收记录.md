# 多 Agent 调度与监控阶段验收记录

> 历史验收事实：本记录验证的是本机 Scheduler 链路；Docker 发布模式由 Compose Scheduler/Worker 执行任务。当前操作以 `54_本机运行与DockerDesktop弃用说明.md` 为准。

## 本阶段交付

- 本机 Scheduler 启动入口：`ops/local/run_local_scheduler.sh`
- Scheduler 前置检查模式：`run_local_scheduler.sh --check`
- Scheduler 后台生命周期管理：`ops/local/manage_scheduler.sh start|stop|status`
- Scheduler 心跳文件：`.runtime/scheduler_heartbeat.json`
- Scheduler 诊断接口：`GET /api/agent-scheduler-status`
- Agent 总览接口：`GET /api/agent-summary`
- 超时 Job 诊断接口：`GET /api/agent-stale-jobs`
- AgentPanel 总览、审核闸门、超时 Job 和任务执行监控

## 关键治理修复

- 已接入统一 `ai_job_runs` 的任务不会被 Scheduler 重复包装。
- Scheduler 成功状态统一为 `completed`，不再写入旧的 `success`。
- Scheduler 在线状态必须同时满足心跳新鲜和 PID 进程存活。
- 本机调度链路不使用 Docker Desktop、Redis 或 Celery。

## 验收证据

- Scheduler 前置检查：`local scheduler prerequisites: ok`。
- Scheduler 诊断接口能够区分在线、离线、旧心跳和无 PID 状态。
- 超时 Job 接口能够返回 Job 编码、负责人、开始时间、运行分钟数和输入引用。
- 后端全量测试：233 passed。
- 前端完整测试：15 个文件、102 passed。
- 前端生产构建通过。

## 运维边界

- Scheduler 不随前后端服务自动启动，避免未经确认触发外部数据采集。
- 推荐发布仍需 Risk Agent/人工审核批准。
- `start`、`stop`、`status` 只作用于本机 Scheduler 进程。
