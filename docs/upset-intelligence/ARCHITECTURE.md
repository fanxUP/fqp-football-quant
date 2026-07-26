# 冷门研究与决策知识系统架构

## 1. 复用边界

本模块不建立第二套比赛、赔率、预测、彩票、结算和报告体系。

| 现有实体/模块 | 冷门系统用途 |
|---|---|
| `official_matches` | 比赛身份、业务日期、开赛时间 |
| `official_odds_snapshots` | 开盘与开赛前最后有效赔率 |
| `official_results` | 最终赛果与比分 |
| `model_predictions` | 模型赛前概率、Edge、EV和版本 |
| `match_feature_snapshots` | 赛前特征证据链 |
| `simulation_tickets` | Agent 每日虚拟彩票 |
| `real_tickets` | 用户实票 |
| `ticket_settlements` | 彩票级投入、返还和盈亏 |
| `prediction_error_analysis` | 模型误差分析入口 |
| `daily_reviews` / `weekly_reviews` / `monthly_reviews` | 周期报告扩展入口 |
| `scripts/jobs/run_scheduler.py` | 状态驱动任务注册入口 |

## 2. 新模块

```text
scripts/upset/
├── domain.py              # 纯计算和数据结构
├── detector.py            # 数据库读取与幂等检测编排
├── evidence.py            # 证据规范化和时间边界
├── provider_evidence.py   # 第三方赛中事件与技术统计规范化
├── review.py              # 结构化复盘生成与质量校验
├── knowledge.py           # 联赛/球队/球员画像计算
└── hypotheses.py          # 研究假设及晋级状态机

scripts/jobs/
├── detect_upsets.py
├── collect_upset_evidence.py
├── collect_upset_provider_evidence.py
├── generate_upset_reviews.py
├── refresh_upset_knowledge.py
└── validate_upset_hypotheses.py

apps/backend/src/routers/upsets.py
apps/frontend/src/pages/UpsetsPage.tsx
apps/frontend/src/features/upsets/
```

## 3. 数据流

```text
official result confirmed
  → require at least two complete Sporttery snapshots for the same market/line
  → select the first and last complete official market before kickoff
  → calculate normalized market probabilities
  → map official result to actual outcome
  → upsert upset_event and market signals
  → link pre-match predictions and settled tickets
  → collect versioned evidence
  → generate structured review
  → validate facts/time boundaries
  → publish to API/UI and periodic reports
  → update temporal knowledge profiles
  → create research_only hypothesis
  → backtest / out-of-sample / simulation
  → versioned feature-candidate promotion
```

## 4. 数据模型

核心表：

- `upset_rule_versions`
- `upset_events`
- `upset_market_signals`
- `upset_factor_evidence`
- `upset_reviews`
- `upset_report_metrics`
- `league_knowledge_profiles`
- `team_knowledge_profiles`
- `player_knowledge_profiles`
- `research_hypotheses`
- `hypothesis_validation_runs`
- `feature_promotion_audits`

所有衍生表都引用现有 `official_matches.id`，不复制比赛主体。

## 5. 调度顺序

```text
settle_finished_matches
→ settle_tickets
→ detect_upsets
→ collect_upset_provider_evidence
→ collect_upset_evidence
→ generate_upset_reviews
→ generate_daily_review
→ analyze_prediction_errors
→ periodic reviews / knowledge refresh / hypothesis validation
```

各任务必须允许重复执行。前置数据缺失时返回 `waiting_data`，不得写入推测性结果。

## 6. 降级策略

- 无完整官方赔率历史：同一玩法、同一让球线至少需要两个时间点的完整体彩官方盘口；只有单点赔率、不完整盘口或无历史赔率的比赛不判定冷门。
- 无模型预测：仍可识别市场冷门，模型复盘显示不可用。
- 无 `API_FOOTBALL_KEY` 或辅助源失败：发布基础冷门事实，详细复盘保持等待状态；不影响官方赛果、结算和冷门识别。
- API-SPORTS 只能补充赛中事件与赛后技术统计，不能代替体彩官方历史盘口，也不能让不合格比赛获得冷门入库资格。
- 辅助源启用后，仅接受联赛、开赛时间、主队和客队同时唯一匹配的比赛；赛中事件和赛后统计永不进入赛前特征。
- 无用户或 Agent 彩票：投注影响显示“未涉及”。
- 外部 AI 不可用：保留结构化事实，延后生成自然语言总结。
