# 新闻情报集成地图

## 现有可复用链路

| 能力 | 现有入口 | 新闻情报接入方式 |
|---|---|---|
| 体彩官方比赛 | `apps/backend/src/routers/official.py` | 只为具有体彩编号的比赛建立观察任务 |
| 伤停与阵容 | `apps/backend/src/routers/enrichment.py` | 作为 A 级结构化证据，不重复建事实表 |
| 特征快照 | `scripts/jobs/run_feature_snapshot_build.py` | P3 追加版本化新闻特征面板 |
| 预测运行 | `scripts/jobs/run_model_prediction.py` | P4 只注册独立影子模型，不修改基线输出 |
| 模型表现 | `apps/backend/src/routers/predictions.py` | P4 展示新闻影子模型指标 |
| 冷门证据 | `sql/48_upset_intelligence_schema.sql` | 只引用已验证新闻事件，不复制原文 |
| 比赛复盘证据 | `apps/backend/src/services/match_review.py` | T+120M 证据进入复盘摘要 |
| 自动报告 | `scripts/jobs/report_generation.py` | 使用冻结证据摘要，不重新抓取历史新闻 |
| 调度审计 | `scripts/jobs/run_scheduler.py`、`ai_job_runs` | 新任务沿用单调度器与运行审计 |
| 运维监控 | `apps/backend/src/services/pipeline_status.py` | 增加采集、快照和影子评估状态 |
| 模型供应商 | `apps/backend/src/services/model_provider_store.py` | 复用加密密钥，由独立新闻提取 Agent 受控调用 |
| 智能工作台 | `apps/backend/src/services/model_invocation_audit.py` | 展示元数据级调用审计，不保存新闻模型正文 |

## 禁止耦合

新闻采集、结构化提取和展示失败时，以下链路必须保持原样运行：

- 官方赛程、赔率和赛果采集。
- 基线预测与推荐候选生成。
- 投注、风控、结算和时光机补录。
- 现有伤停、阵容、冷门和复盘任务。

P4 之前 `run_model_prediction.py` 不读取新闻特征。P5 的人工晋升也只能启用一个新的、
版本锁定的模型版本，并保留一键回退到基线版本的能力。

## 数据所有权

- 官方比赛事实仍由官方数据核心拥有。
- 新闻模块只拥有文章元数据、结构化事件、证据、冻结快照和派生特征。
- LLM 输出属于未验证派生材料，必须带模型、提示词版本和调用审计。
- 前端只读核心新闻材料；唯一写入口是信源启停与人工核验状态。

## 发布开关

- `news_intelligence_module`：控制页面、API 和采集任务，初始可安全关闭。
- `news_feature_shadow_enabled`：控制新闻特征影子计算，默认关闭。
- `news_feature_production_enabled`：控制已批准模型读取新闻特征，默认关闭。

三个开关相互独立。生产特征开关不能由调度器、LLM 或评估任务自动打开。

## 运行配置

- `FQP_NEWS_COLLECTION_ENABLED=true` 才注册外部采集任务，默认关闭。
- `NEWSAPI_API_KEY`、`GNEWS_API_KEY`、`GUARDIAN_API_KEY` 分别启用对应来源；可只配置其中一个。
- 新闻事件提取 Agent 未就绪时继续使用规则；任一外部来源失败时其他来源继续运行。
- 采集任务沿用两小时节奏，单次只覆盖未来 36 小时内的体彩官方编号比赛。
