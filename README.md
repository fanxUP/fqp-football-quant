# FQP 足球量化研究系统

FQP 用于官方足球数据分析、概率模型研究、虚拟票单、实票记录和赛后复盘。版本来源为根目录 `VERSION`。

## 开发与数据规则

1. 修改前确认当前 Git 工作树、分支和已有差异，保留他人的未提交改动。原因：同一项目可有多个工作树，固定旧电脑路径无法识别当前源码。
2. 将官方比赛、玩法、赔率和赛果作为正式预测与票单的依据，第三方赛程保持补充来源标识。原因：赛事档案包含补充比赛，但补充比赛不能冒充体彩官方可投注比赛。
3. 保留赛前快照、模型版本及计算时间，不使用未来数据生成历史预测。原因：推荐和回测需要能重建当时可用的信息。
4. Codex 负责开发维护，长期任务由 Scheduler/Worker 执行。原因：会话生命周期不能保证定时任务持续运行。
5. 修改 UI 时沿用现有主题 Token、二维操作和路由。原因：当前实现支持多主题和 3D 回退，单一红黑样式已不能代表全部界面。
6. 保持分析、模拟、记录和复盘的产品边界。原因：现有应用没有联网购票、支付或出票链路。
7. 按本次任务授权的范围执行测试，并如实记录未运行项。原因：静态文档检查与应用运行验证提供的证据不同。

## 代码与文档入口

| 目的 | 入口 |
| --- | --- |
| 文档阅读顺序、现行规范与历史资料 | [文档地图](docs/README.md) |
| 项目目标和产品边界 | [项目总览](docs/00_项目总览与边界.md) |
| 项目身份与运行入口 | [项目清单](PROJECT_MANIFEST.md) |
| 开发工作流与模板 | [开发规范](docs/31_Codex开发工作流与提示词模板.md)、`templates/codex/` |
| 后端与业务任务 | `main.py`、`apps/backend/src/`、`scripts/` |
| 前端 | `apps/frontend/src/` |
| 模块与菜单 | `configs/final_module_registry.yaml`、`configs/final_panel_registry.yaml` |
| 数据结构与测试 | `sql/`、`tests/` |

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
