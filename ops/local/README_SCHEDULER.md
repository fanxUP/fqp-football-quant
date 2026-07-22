# 本机 Scheduler（已停用）

本项目现在只使用 Docker Desktop 中的 PostgreSQL、Worker 与 Scheduler。`run_local_scheduler.sh` 和 `manage_scheduler.sh start` 默认拒绝启动，防止产生第二套采集、结算和模型任务。当前入口见 `../../docs/54_本机运行与DockerDesktop弃用说明.md`。

推荐启动方式：

```bash
./ops/local/run_hybrid_dev.sh
```

如果以前启用过 macOS `launchd` Scheduler，只用下列命令停止或查看：

```bash
./ops/local/manage_scheduler.sh status
./ops/local/manage_scheduler.sh stop
```
