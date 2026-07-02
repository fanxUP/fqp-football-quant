# 42 多 Agent 按模块协作与 Codex 任务分配

## 1. 目标

正式项目已引入 Codex 多 Agent，并按模块拆分 Agent 工作，避免所有 Agent 都改同一片代码。

## 2. Agent 按模块分工

| Agent | 负责模块 | 主要任务 |
|---|---|---|
| OfficialDataAgent | official_data | 官方采集、赔率快照、赛果同步 |
| FeatureAgent | feature_store | 多维特征构建、特征快照、数据质量 |
| TeamIntelAgent | season_team/player_lineup/injury | 球队、球员、身价、首发、伤停 |
| EnvironmentAgent | stadium_weather/motivation_tournament | 球场、天气、旅行、战意、赛制博弈 |
| ModelAgent | model_research/model_committee | 模型复现、训练、评估、委员会投票 |
| RecommendationAgent | recommendation | EV、风控、票单、资金分配 |
| ReviewAgent | ticket_review | 实票、复盘、日报周报月报 |
| PoolAgent | pool_lottery | 传统足彩、任九、组合覆盖 |
| FrontendPanelAgent | frontend_panels | 页面、路由、面板、图表 |
| QAAgent | tests | 测试、验收、回归、CI |
| OpsAgent | ops_admin | 部署、备份、监控、报警 |
| SecurityAgent | security/audit | 权限、审计、敏感操作拦截 |

## 3. Codex 任务单标准

每个任务必须包含：

```text
任务ID
模块名
目标文件
允许修改范围
禁止修改范围
输入数据
输出要求
测试命令
验收标准
回滚方式
人工审核人
```

## 4. 影响分析

Codex 修改前必须先读取：

```text
module_registry.yaml
module_dependencies.yaml
panel_registry.yaml
openapi.yaml
相关 SQL migration
相关测试文件
```

## 5. 自动化任务边界

Codex 可以自动完成：

```text
生成代码
补充测试
修复 lint
生成 SQL migration
补充配置
生成面板骨架
更新 OpenAPI
生成文档
```

Codex 不能自动完成：

```text
生产推荐发布
生产数据库破坏性迁移
关闭合规提示
绕过人工审核
修改资金上限为无限制
删除历史赔率快照
删除审计日志
```

## 6. 验收标准

1. 每个 Agent 有明确模块边界。
2. 每个任务有允许修改范围。
3. Codex 输出必须包含测试结果。
4. 高风险任务必须人工审核。
5. Agent 修改前后有审计记录。
