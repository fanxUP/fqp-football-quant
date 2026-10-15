# FQP 项目清单

## 项目定位

FQP 是个人使用的足球量化研究系统，包含官方数据、预测、虚拟竞赛、实票记录和复盘。版本事实来源为根目录 `VERSION`。

## 当前规则

1. 以当前 Git 工作树和实际提交记录识别源码版本；发布时另行核对目标提交与部署版本。原因：未提交修改和已有运行镜像可能对应不同内容。
2. 运行环境按所选入口识别，不固定个人目录、主机 IP 或数据库地址。原因：仓库同时包含原生 macOS、Ubuntu 发布脚本和本地 Docker 测试材料。
3. 在同一业务数据库上只保留一套有效调度链，赔率轮询按 `FQP_ODDS_DISPATCH_OWNER` 指定所有者。原因：Worker 与 Scheduler 均存在调度分支，重复启动会重复采集或执行任务。
4. 全量备份按显式运维需要手动执行，并区分归档校验与实际恢复。原因：`verify_backup.py` 不在自动调度中，校验归档不能证明恢复成功。
5. 保留持久数据和审计证据，不用删除数据目录替代恢复。原因：票据、资金与历史快照无法靠拉取代码重建。

## 实现入口

| 目的 | 入口 |
| --- | --- |
| 文档优先级 | [docs/README.md](docs/README.md) |
| 开发工作流 | [docs/31_Codex开发工作流与提示词模板.md](docs/31_Codex开发工作流与提示词模板.md) |
| 运行方式 | [docs/54_本机运行与DockerDesktop弃用说明.md](docs/54_本机运行与DockerDesktop弃用说明.md) |
| 原生运行、服务器发布、本地容器探针 | `ops/local/`、`ops/server/`、`ops/docker-test/` |
| 模块、面板与依赖 | `configs/final_module_registry.yaml`、`configs/final_panel_registry.yaml`、`configs/module_dependencies.yaml` |
| API 与数据库 | `apps/backend/src/routers/`、`api/`、`sql/` |
| 调度与执行 | `scripts/jobs/run_scheduler.py`、`scripts/official_crawler_stub.py` |
| 手动全量备份 | `scripts/jobs/verify_backup.py` |

完整跟踪文件列表由 `git ls-files` 提供。
