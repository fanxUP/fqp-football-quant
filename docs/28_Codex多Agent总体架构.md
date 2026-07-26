# 28. Codex 多 Agent 总体架构

## 1. 建设目标

本阶段目标是把 FQP 从“单体开发项目”升级为“Codex 多 Agent 协同开发与自动化维护项目”。Codex 不只是写代码助手，而是项目中的工程执行层：负责拆任务、生成代码、修改代码、运行测试、维护采集脚本、维护模型计算脚本、修复数据异常、生成文档和提交差异。

但必须明确：长期生产任务不能依赖一次性对话后台。生产采集、AI 计算、复盘和报表由系统内的 Scheduler / Worker 执行；Codex 负责开发、维护、审查、受控触发和修复这些任务。

## 2. 总体架构

```text
用户/项目负责人
    ↓
Codex Orchestrator Agent，总控 Agent
    ├── Data Agent，数据采集与清洗
    ├── Feature Agent，多维特征工程
    ├── Model Agent，AI 计算与模型复现
    ├── Backtest Agent，回测与防作弊验证
    ├── Recommendation Agent，推荐票单生成
    ├── Risk Agent，风控熔断与合规检查
    ├── Review Agent，日报周报月报与错因归因
    ├── QA Agent，测试、Lint、类型检查、回归测试
    ├── DevOps Agent，部署、备份、监控、恢复
    └── Doc Agent，文档、数据字典、API 文档同步
```

## 3. 与系统服务的关系

```text
Codex Agent 层：开发、修改、测试、审查、修复、任务拆解
应用服务层：FastAPI、Web、Admin、API Gateway
任务调度层：APScheduler / Celery Beat / Cron
Worker 层：Crawler Worker、Feature Worker、Model Worker、Backtest Worker、Report Worker
数据层：PostgreSQL、Redis、对象存储、日志与审计
```

## 4. 为什么要分 Agent

单个 Agent 同时负责采集、建模、测试、部署，容易产生权限过大和职责混乱。多 Agent 的价值是：

- 数据 Agent 不应该直接发布推荐。
- 模型 Agent 不应该直接修改资金规则。
- 推荐 Agent 不应该绕过风控熔断。
- DevOps Agent 不应该改模型结论。
- QA Agent 不应该自己修复后直接合并，必须生成审查结果。

## 5. 数据流

```text
官方赛程/赔率/赛果
    ↓ Data Agent 维护采集器
官方快照表
    ↓ Feature Agent 生成赛前特征
赛季/球队/球员/伤停/天气/战意/赛制特征
    ↓ Model Agent 运行概率模型
模型预测表
    ↓ Recommendation Agent 生成候选票单
候选推荐
    ↓ Risk Agent 熔断与资金约束
正式推荐/模拟票单
    ↓ Review Agent 赛后复盘
日报/周报/月报/错因归因
```

## 6. Codex 应该完成的工作

### 必须交给 Codex 的工作

- 新建模块代码。
- 修改 SQL 迁移。
- 生成 API 路由和 Pydantic Schema。
- 生成采集 Worker、模型 Worker、报表 Worker。
- 生成单元测试、集成测试、回测测试。
- 运行测试并修复失败。
- 根据错误日志定位问题。
- 生成文档和接口说明。

### 不能直接交给 Codex 自动完成的工作

- 未经审核发布投注推荐。
- 未经审核修改资金上限。
- 未经审核删除数据库。
- 未经审核绕过合规提示。
- 未经审核修改真实实票记录。
- 未经审核将模拟收益包装成真实收益。

## 7. 验收标准

- 每个 Agent 有唯一名称、职责、权限、输入、输出。
- 每个 Agent 的任务都能写入 `agent_tasks`。
- 每次 Agent 修改代码后必须有测试结果。
- 每次推荐发布前必须有 Risk Agent 记录。
- 每次生产任务失败必须生成 Codex 修复任务。
- 每次数据源异常必须进入熔断流程。
