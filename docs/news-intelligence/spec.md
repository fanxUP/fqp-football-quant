# 足球新闻情报系统规格

## 目标

在 FQP 中增加独立的“新闻情报”模块，把可追溯的新闻、伤停、停赛和阵容变化转换为防数据穿越的比赛特征。第一阶段只展示和归档，第二阶段进入影子模型；只有在量化评估达标并经人工批准后，版本化的新闻特征才能进入正式预测。

## 已确认假设

- 当前业务赛程仍以体彩官方有编号比赛为唯一入口。
- PostgreSQL 保存事实、事件、快照和评估；Redis 只用于缓存和限流。
- 新闻聚合接口只负责发现，可信度继承原始发布者，不继承聚合平台。
- LLM 只做结构化提取、翻译和摘要，不能直接修改概率、推荐、投注或风控。
- 新闻增强默认关闭；未完成的阶段不得改变现有预测结果。

## 技术栈与命令

- Python 3.14、FastAPI、psycopg2、APScheduler。
- React 19、TypeScript 6、Vite 8、Vitest。
- 后端测试：.venv/bin/python -m pytest
- Ruff：.venv/bin/ruff check .
- Mypy：.venv/bin/mypy apps scripts
- 前端测试：cd apps/frontend && npm test
- 前端类型检查：cd apps/frontend && npm run typecheck
- 前端构建：cd apps/frontend && npm run build
- 迁移：ops/local/apply_local_migrations.sh

## 模块边界

### 复用

- 官方比赛和体彩编号：现有官方赛程表和比赛映射。
- 伤停与阵容：现有 enrichment 数据表及 API。
- 证据链：复用比赛复盘证据的时间与来源语义。
- 特征快照：通过新版本新闻特征面板接入，不覆盖旧快照。
- 模型：先注册独立新闻影子模型，不修改现有基线模型代码。
- 运维：复用 ai_job_runs、系统监控和 scheduler 单一调度进程。

### 新增数据

- news_sources：原始发布者与信源等级。
- news_articles_raw：不可变原始文章元数据。
- news_events：结构化比赛事件。
- news_event_entities：事件与比赛、球队、球员的关联。
- news_event_evidence：多源证据与核验状态。
- match_news_snapshots：T-24H、T-6H、T-90M、T-45M 冻结快照。
- match_news_features：只包含数值化、可版本化特征。
- news_feature_evaluations：影子模型评估结果。
- news_ingestion_runs：供应商级采集审计。

## 时间与防穿越规则

每条原始信息必须保存 published_at、observed_at、captured_at 和 available_at。任一快照只能读取 available_at 不晚于 snapshot_cutoff 的证据。文章后续编辑不得改写历史快照；更正内容以新版本归档。

## 信源等级

- S：俱乐部、联赛、足协、国家队等官方信源。
- A：经过配置的结构化足球数据供应商。
- B：经过人工维护的可靠媒体。
- C：一般媒体或单一转载。
- D：传闻或来源不明内容，只展示，不进入正式特征。

聚合商不决定等级；同一文章由 URL 规范化和内容哈希去重。

## 结构化事件与特征

第一版事件类型限定为：伤停、停赛、复出、预计首发、官方首发、轮换、主帅变化、赛程压力、内部事件、士气正向、士气负向。事件必须包含方向、可信度、比赛相关性、主体和证据。无法确认的字段保持为空，不允许 LLM 猜测。

第一版特征控制在稳定小集合：主客队缺阵人数、核心球员缺阵影响、停赛影响、预计首发偏离、官方首发强度变化、近七天赛程密度、主帅变动天数、正负面事件强度、可信度、多源确认数、新闻热度异常、新闻方向与临场赔率变化一致性。聚合结果必须限幅，避免单条新闻支配概率。

## 调度

只为体彩官方有编号比赛创建观察任务：T-24H 完整快照、T-6H 临近变化、T-90M 阵容与伤停、T-45M 官方首发与最终赛前快照、T+120M 赛后证据。采用增量游标、内容哈希、缓存、供应商限额和指数退避；不得全网高频轮询。

## API 与页面

- GET /api/news-intelligence/overview
- GET /api/news-intelligence/events
- GET /api/news-intelligence/matches/{match_id}/timeline
- GET /api/news-intelligence/matches/{match_id}/features
- GET /api/news-intelligence/sources
- GET /api/news-intelligence/experiments
- PATCH /api/news-intelligence/sources/{source_id}

核心比赛、实体和特征材料全部由后端组装。导航增加“新闻情报”，包含总览、比赛情报、事件、特征表现、影子实验和信源健康；比赛详情与复盘只显示摘要并跳转。

## 测试策略

- 单元测试：时间截止、URL 去重、可信度、事件归并、影响分和限幅。
- API 测试：未登录、空数据、分页、单场时间线、来源更新权限。
- 数据库测试：唯一约束、不可变快照、迁移与回滚。
- 调度测试：相对开赛时间、幂等、失败退避和供应商限额。
- 前端测试：加载、空数据、失败、筛选、来源标签和窄屏。
- 影子评估：时间切分，比较 Brier、Log Loss、校准、CLV，不以单场或 ROI 单独晋升。

## 开发切片

1. P0：保存规格、集成地图和默认关闭的模块边界。
2. P1：信源、原始文章、只读 API 和新闻情报页面。
3. P2：事件提取、实体关联、多源证据和人工核验状态。
4. P3：冻结快照、数值特征和现有 Feature Snapshot 接口。
5. P4：新闻影子模型、评估面板和完整回放。
6. P5：人工晋升、版本锁定和一键回退；未达标时保持影子状态。

每个切片必须先写失败测试，完成后运行对应测试和静态检查，用中文 Commit 提交。

## 成功标准

- 按体彩比赛追溯原文、来源、发布时间和采集时间。
- 同一事件展示多源证据及核验状态。
- 历史快照不会读到截止时间之后的新闻。
- 新闻采集或 LLM 失败不影响原业务链路。
- 新闻特征在人工晋升前不会进入正式预测。
- 新任务可监控、可补跑、可限流且幂等。
- 后端、前端、迁移、类型检查和生产构建全部通过。

## 永不执行

- 不把模型输出写入比赛官方事实表。
- 不让 LLM 直接选择玩法或投注方向。
- 不自动晋升新闻增强模型。
- 不提交 API Key、原文版权内容或登录凭据。
- 不使用开赛后数据重写赛前快照。

## 外部接口依据

- NewsAPI Everything：https://newsapi.org/docs/endpoints/everything
- GNews Search：https://docs.gnews.io/endpoints/search-endpoint
- API-Football：https://www.api-football.com/documentation
- Sportmonks Fixtures：https://docs.sportmonks.com/v3/endpoints-and-entities/endpoints/fixtures
