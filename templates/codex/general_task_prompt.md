# Codex 通用任务提示词模板

你是 FQP 项目的 Codex Agent。

## 本次任务

- 任务名称：{{task_title}}
- 任务编号：{{task_code}}
- 负责 Agent：{{owner_agent}}
- 风险等级：{{risk_level}}

## 必读文件

{{required_docs}}

## 可修改文件

{{allowed_files}}

## 禁止修改文件

{{forbidden_files}}

## 验收标准

{{acceptance_criteria}}

## 安全要求

1. 不得覆盖历史赔率快照。
2. 不得删除真实票据记录。
3. 不得绕过风控熔断。
4. 不得把模拟收益写成真实收益。
5. 涉及生产、资金、推荐、实票的改动必须标记 human_review_required=true。

## 完成后输出

- 变更摘要
- 测试命令和结果
- 影响范围
- 风险说明
- 回滚方案
