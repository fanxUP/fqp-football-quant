# FQP 项目清单

## 项目定位

FQP 是单用户本地使用的足球竞彩与足彩量化研究系统：官方赛程、玩法、赔率快照和赛果构成正式比赛边界；第三方数据只补充赛前特征；系统只提供分析、模拟、记录和复盘，不提供线上售彩或代购。

## 当前运行规则

- 当前发布版本：`1.1.1`；根目录 `VERSION` 是版本事实来源。
- 当前唯一工作区：`/Users/fan/Downloads/足球量化`；旧 iCloud 副本不得再用于开发或启动服务。
- 源码仅在本机工作目录开发、测试、提交；Git 提交是唯一代码版本边界。
- 本机长期运行：`./ops/local/manage_local_stack.sh start`。
- 前端、后端、Worker、Scheduler、PostgreSQL 和 Redis 全部为 macOS 本机进程。
- 本机 PostgreSQL `127.0.0.1:5432/fqp` 是唯一数据库；不再使用 Docker Desktop。
- `data/` 是本机持久数据和备份，不提交 Git，不用删除目录替代恢复。
- Worker 是赔率高频调度的唯一执行者；Scheduler 不重复轮询。

## 文档与实现入口

| 目的 | 入口 |
| --- | --- |
| 文档导航、优先级、历史边界 | `docs/README.md` |
| 当前运行与切换规则 | `docs/54_本机运行与DockerDesktop弃用说明.md` |
| 本机运行操作 | `ops/local/README_LOCAL_RUNTIME.md` |
| 产品边界、架构与阶段计划 | `docs/00_项目总览与边界.md`、`docs/03_系统架构设计.md`、`docs/51_最终开发阶段计划与验收清单.md` |
| 模块、页面与依赖事实来源 | `configs/final_module_registry.yaml`、`configs/final_panel_registry.yaml`、`configs/module_dependencies.yaml` |
| API、数据结构与可验证行为 | `api/`、`sql/`、`tests/`、应用代码 |
| 体彩官方历史回填与覆盖审计 | `docs/64_体彩官方历史比赛回填与审计.md` |

完整文件列表由 Git 管理：使用 `git ls-files` 获取；不在本文件重复维护易过期的文件计数和逐项清单。
