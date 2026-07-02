# 50_Codex多Agent本地开发执行规范

## 1. Codex 在 正式项目 中的角色

Codex 是开发和维护工具，不是唯一生产运行时。

Codex 负责：

- 代码生成。
- 脚本修复。
- 单元测试补齐。
- 采集器维护。
- 模型代码复现。
- SQL 迁移草案。
- 文档更新。
- 前端面板开发。
- 配置检查。

本地 Scheduler/Worker 负责：

- 定时采集。
- 定时计算。
- 定时结算。
- 定时报表。
- 长期运行。

## 2. Agent 划分

```text
planner_agent          任务拆解
crawler_agent          数据采集脚本
feature_agent          特征工程
model_agent            模型复现与计算
backtest_agent         回测实验
frontend_agent         红黑科技风前端面板
qa_agent               测试与验收
ops_agent              Docker/备份/调度
review_agent           代码审查和冲突检查
```

## 3. 权限边界

| Agent | 可读 | 可写 | 禁止 |
|---|---|---|---|
| crawler | scripts/jobs, configs/data_sources | 采集脚本 | 直接改模型权重 |
| model | scripts/models, notebooks | 模型代码 | 直接发布推荐 |
| frontend | apps/frontend | UI 代码 | 修改数据库迁移 |
| ops | ops, docker, cron | 部署脚本 | 改推荐策略 |
| qa | tests | 测试用例 | 直接改生产配置 |
| review | 全项目只读 | 审查报告 | 自动删除模块 |

## 4. 人工审核闸门

以下动作必须本地 owner 确认：

- 数据库迁移执行。
- 模块删除。
- 模型版本切换。
- 风控阈值修改。
- 正式推荐发布。
- 备份恢复。
- 批量删除日志或历史数据。

## 5. Codex 任务模板

每个 Codex 任务必须包含：

```text
任务目标
涉及模块
允许修改路径
禁止修改路径
输入数据
输出文件
测试命令
验收标准
回滚方式
```

## 6. 正式项目 边界修复

之前“AI 计算和定时获取数据全部由 Codex 完成”的表述容易误解。正式项目 改为：

```text
Codex 开发、维护、修复 AI 计算与定时采集代码；
本地 Scheduler/Worker 长期执行这些任务；
Codex 可受控触发一次性任务，但不作为常驻生产进程。
```


---

## 最终补充：Codex + Docker Desktop + 非锁版依赖策略
本项目最终执行时以 `docs/52_Codex开发_DockerDesktop部署_依赖非锁版最终规范.md` 为准：项目使用 Codex 开发，Docker Desktop 本地部署；依赖不指定固定版本，优先使用本机已安装版本，缺失时使用当前最新版。所有长期任务由本地 Scheduler/Worker 运行，Codex 负责代码开发、维护、修复和受控触发。
