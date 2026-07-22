# FQP 本地个人足球量化系统项目包

当前发布版本为 `1.1.1`，版本事实来源为根目录 `VERSION`；项目身份仍统一使用 FQP，不再以历史目录名中的版本编号区分项目。

当前唯一开发与运行工作区是 `/Users/fan/Downloads/足球量化`。旧 iCloud 目录只保留为待删除历史副本，不得再用于启动服务或修改代码。

## 项目定位

FQP 是一套面向个人本地部署的足球竞彩/足彩量化研究与长期运行系统。系统以中国体育彩票/中国竞彩网官方赛程、官方玩法、官方赔率快照和官方赛果为主数据边界，结合赛季数据库、球队数据库、球员身价、首发阵容、伤停、球场地理、天气、赛制博弈、赔率市场模型、论文复现模型、资金管理和实票复盘，形成可长期运行、可回测、可维护、可扩展的个人量化决策程序。

## 最终执行原则

1. 本地个人部署，不设计复杂多用户登录和用户切换。
2. 模块化只用于后期新增、删除、替换、维护功能，不作为复杂商业权限系统。
3. Codex 多 Agent 用于开发、修复、测试、审查和脚本维护；长期生产任务由本地 Scheduler/Worker 执行。
4. 官方赛程、官方玩法、官方赔率和官方赛果是主数据边界；第三方数据只做补充特征。
5. 所有预测、推荐、复盘、回测都必须绑定赛前快照，禁止赛后数据污染。
6. 前端 UI 采用红黑足球科技风，强调仪表盘、赔率曲线、多维情报、资金曲线和复盘面板。
7. 系统只做数据分析、模拟、记录和复盘，不提供互联网售彩、代购、合买、出票、收款等功能。

## 核心入口文件

- `docs/FQP_本地个人足球量化系统_完整项目总方案.docx`
- `docs/FQP_本地个人足球量化系统_完整项目总方案.pdf`
- `spreadsheets/FQP_本地个人足球量化系统_项目排期_模块面板_逻辑体检.xlsx`
- `PROJECT_MANIFEST.md`

## 目录说明

- `docs/`：完整项目文档、需求、架构、模型、模块化、UI、部署、验收。
- `sql/`：PostgreSQL 数据表结构，包括官方数据、赛季球队、模型、推荐、实票、模块注册、单用户本地模式。
- `api/`：OpenAPI 接口草案。
- `configs/`：本地部署、模块注册、面板注册、Agent、任务调度、红黑 UI 主题配置。
- `scripts/`：采集、模型、特征、Agent、模块加载、部署辅助脚本骨架。
- `apps/`：前端主题与应用骨架。
- `ops/`：本机运行、备份恢复、Codex 环境说明。
- `tests/`：最终逻辑一致性与验收清单。
- `personal_run/`：个人长期运行手册。

## 开发建议

先按 `docs/51_最终开发阶段计划与验收清单.md` 拆阶段执行，再根据 `configs/final_module_registry.yaml` 和 `configs/final_panel_registry.yaml` 控制模块与功能面板上线顺序。

## 运行方式：全本机原生运行

前端、后端、Worker、Scheduler、PostgreSQL 和 Redis 全部在 macOS 本机运行，不需要 Docker Desktop。源码以 Git 提交为准，数据库以本机 `127.0.0.1:5432/fqp` 为唯一事实源。

```bash
cp .env.local.example .env.local
./ops/local/setup_local_latest_macos.sh
./ops/local/manage_local_stack.sh start
```

- 前端：http://127.0.0.1:8066
- 后端：http://127.0.0.1:8006
- PostgreSQL：`127.0.0.1:5432/fqp`
- Redis：`127.0.0.1:6379`
- 本机运行统一使用 Python 3.14 和 Node.js。
- `.env.local` 只保存在本机，不提交 GitHub。

查看、重启与停止：

```bash
./ops/local/manage_local_stack.sh status
./ops/local/manage_local_stack.sh restart
./ops/local/manage_local_stack.sh stop
```

唯一工作区、Git 同步和本机运行规则见 `docs/54_本机运行与DockerDesktop弃用说明.md`；日常命令见 `ops/local/README_LOCAL_RUNTIME.md`。
