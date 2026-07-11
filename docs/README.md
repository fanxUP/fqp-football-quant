# FQP 文档导航与优先级

## 先读这里

本文档目录保留了产品设计、实施计划、历史验收和运维记录。为避免把历史结论当作当前操作指令，文档按以下优先级使用：

1. **当前运行与操作**：本文件、[54_本机运行与DockerDesktop弃用说明.md](54_本机运行与DockerDesktop弃用说明.md)、[../ops/local/README_Codex_Docker_Desktop.md](../ops/local/README_Codex_Docker_Desktop.md) 与实际脚本。
2. **当前产品与架构约束**：[00_项目总览与边界.md](00_项目总览与边界.md)、[01_PRD_产品需求文档.md](01_PRD_产品需求文档.md)、[03_系统架构设计.md](03_系统架构设计.md)、[44_最终版架构逻辑体检与冲突修复报告.md](44_最终版架构逻辑体检与冲突修复报告.md)。
3. **实现契约**：`configs/final_*_registry.yaml`、`configs/module_dependencies.yaml`、`api/`、`sql/` 与代码测试。若文档与这些可执行契约冲突，以可执行契约和当前测试为准。
4. **历史设计与验收**：52 号文档以及 58–63 号验收记录。它们保存当时的决策和证据，不构成当前启动指令。

## 当前运行口径

- 源码只在本机工作目录修改、测试、提交；容器内禁止直接改源码。
- 日常热开发使用 `./ops/local/run_local_dev.sh`，依赖本机 Python、Node.js 和 PostgreSQL。
- 需要完整发布运行时，使用 `./ops/local/run_local_stack.sh deploy`。脚本会先校验干净工作区、推送 GitHub 并核对提交 SHA，再重建 Docker Desktop 服务。
- `data/` 是宿主机持久数据，不提交 Git；容器是可重建运行环境，不是源码来源。
- Scheduler/Worker 只能选择一个运行模式：本机开发模式使用 `ops/local/run_local_scheduler.sh` 或 `manage_scheduler.sh`；Docker 发布模式由 Compose 服务运行。不要同时启动两套。

## 文档分组

| 范围 | 文档 |
| --- | --- |
| 产品、数据与风控 | 00–19 |
| 多维赛前数据与模型增强 | 20–27 |
| 多 Agent 与自动化治理 | 28–35、50、57–62 |
| 模块化、页面与 UI | 36–49、55–56、63 |
| 当前运行、监控与验收 | 13–14、51、53–54、`ops/local/`、`tests/` |
| 历史方案 | 45、52 及各阶段验收记录 |

## 文档维护规则

- 改变运行方式、数据边界、模块依赖或推荐安全边界时，同时更新本页和对应的当前规范。
- 不删除历史验收结论；在文首标注其适用日期和与当前口径的关系。
- 不在历史文档中新增操作命令。新增命令只写入 README、54 号文档或 `ops/local/` 的操作手册。
