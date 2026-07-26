# 32. 多 Agent 数据库与任务队列设计

## 1. 设计目标

新增数据库用于追踪 Codex 多 Agent 的任务、操作、输出、审查、权限和运行结果，避免 Agent 行为不可追溯。

## 2. 核心表

### agent_registry

记录 Agent 定义。

### agent_tasks

记录每个任务，从创建到完成的全过程。

### agent_task_artifacts

记录任务产生的文件、报告、测试结果、差异摘要。

### agent_audit_logs

记录 Agent 执行的命令、修改的文件、影响的数据表。

### agent_human_review_gates

记录哪些任务必须人工审核。

### ai_job_runs

记录 AI 计算与定时采集任务的实际运行结果。

## 3. 任务状态机

```text
created
queued
assigned
running
waiting_review
blocked
failed
passed_tests
approved
rejected
merged
closed
```

## 4. 风险等级

```text
L1 文档/注释/只读查询
L2 非生产代码修改
L3 数据库迁移/采集脚本/模型脚本
L4 推荐生成/资金逻辑/实票复盘
L5 生产数据写入/删除/预算上限/合规边界
```

L4 和 L5 必须人工审核。

## 5. 数据流

```text
agent_tasks 创建任务
    ↓
Codex Agent 执行
    ↓
agent_audit_logs 记录操作
    ↓
agent_task_artifacts 保存输出
    ↓
QA Agent 写入测试结果
    ↓
Risk Agent 判断是否需要人审
    ↓
人工审核或合并
```

## 6. 验收标准

- 任何 Agent 行为都有 task_id。
- 任何生产写入都有 audit log。
- 任何 L4/L5 任务都有 review gate。
- 任何 AI 计算任务都有输入快照和输出引用。
- 任何失败任务都能由 Codex 自动生成修复任务草案。
