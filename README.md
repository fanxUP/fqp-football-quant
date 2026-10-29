# FQP 足球量化研究系统

FQP 用于官方足球数据分析、概率模型研究、虚拟票单、实票记录和赛后复盘。版本来源为根目录 `VERSION`。

## 开发与数据规则

1. 修改前确认当前 Git 工作树、分支和已有差异，保留未提交改动；本项目只允许 `main` 一个分支，任务按顺序在现有 `main` 工作树中完成。原因：项目由个人维护，单一开发线可避免并行分支产生的漂移和反复合并。
2. 将官方比赛、玩法、赔率和赛果作为正式预测与票单的依据，第三方赛程保持补充来源标识。原因：赛事档案包含补充比赛，但补充比赛不能冒充体彩官方可投注比赛。
3. 保留赛前快照、模型版本及计算时间，不使用未来数据生成历史预测。原因：推荐和回测需要能重建当时可用的信息。
4. Codex 负责开发维护，长期任务由 Scheduler/Worker 执行。原因：会话生命周期不能保证定时任务持续运行。
5. 修改 UI 时使用黑红、极地两套主题的语义 Token，沿用现有二维操作和路由；不新增其他主题或界面设置。原因：两套风格覆盖深浅环境，统一控件可避免各模块独立配色和布局漂移。
6. 保持分析、模拟、记录和复盘的产品边界。原因：现有应用没有联网购票、支付或出票链路。
7. 按本次任务授权的范围执行测试，并如实记录未运行项。原因：静态文档检查与应用运行验证提供的证据不同。

## 代码与文档入口

| 目的 | 入口 |
| --- | --- |
| 文档阅读顺序、现行规范与历史资料 | [文档地图](docs/README.md) |
| 项目目标和产品边界 | [项目总览](docs/00_项目总览与边界.md) |
| 项目身份与运行入口 | [项目清单](PROJECT_MANIFEST.md) |
| 开发工作流与模板 | [Agent 强制规则](AGENTS.md)、[开发规范](docs/31_Codex开发工作流与提示词模板.md)、`templates/codex/` |
| 后端与业务任务 | `main.py`、`apps/backend/src/`、`scripts/` |
| 前端 | `apps/frontend/src/` |
| 模块与菜单 | `configs/final_module_registry.yaml`、`configs/final_panel_registry.yaml` |
| 数据结构与测试 | `sql/`、`tests/` |

## 足球补充数据

已将本地球探采集能力纳入 `scripts/sources/titan007/`；原始缓存保存在忽略的 `data/sources/titan007/`。英超共享 PostgreSQL 导入与现有联赛页已在本机 Docker Desktop 启用：380 场赛程、20 队、总/主/客榜各 20 行，20 队共享队徽已离线核对修正。入口为 `http://127.0.0.1:18066/#/events?view=league`；有界更新入口 `scripts.titan007_refresh` 已将本机参考数据更新至 2026-10-29 15:01（80 场完场），支持冻结回执和零联网重试发布。服务器发布、自动调度和模型输入接通仍属后续。采集方法、请求限制、运行命令见 [足球补充数据](docs/titan007-data-source.md)。

## 运行方式

| 环境 | 代码入口 | 适用范围 |
| --- | --- | --- |
| macOS 原生 | `ops/local/manage_local_stack.sh` | Homebrew PostgreSQL/Redis 与 launchd 应用进程 |
| Ubuntu 服务器 | `ops/server/deploy.sh` | systemd/Nginx 发布流程，默认只生成计划 |
| Docker Desktop | `compose.desktop-test.yml`、`ops/docker-test/README.md` | 本机隔离部署；独立卷和回环端口，发布状态见 Git 记录 |

macOS 安装和管理步骤见 [原生运行手册](ops/local/README_LOCAL_RUNTIME.md)；运行边界见 [运行规范](docs/54_本机运行与DockerDesktop弃用说明.md)。环境和端口以所选入口的实际配置为准。

- 私密环境文件、密钥和持久数据不提交 Git。原因：它们包含凭证及与代码版本独立的数据。
- 初始密码 `admin123` 仅供首次登录，实际使用前通过设置修改。原因：公开默认密码无法保护已部署实例。
- 模型接入需要随机且至少 32 字符的 `FQP_PROVIDER_ENCRYPTION_KEY`；已有凭证后保留原密钥。原因：供应商凭证依赖该密钥加解密，随意更换会使已有凭证不可读。
