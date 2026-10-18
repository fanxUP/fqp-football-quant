# 公共数据契约 v1

当前交付：P101 最小身份入口、公共词汇与静态目录。不新增数据库结构，不开启来源，不激活模型。P102 管特征定义，P104 管不可变观测/时点，P106 管工件/整次预测；这些任务须引用本契约。

## 唯一维护入口

- `scripts/data_contracts.py`：实体、事实/采集状态、用途、身份解析结果和显式时区转换。
- `configs/data_catalog.yaml`：来源家族/命名空间及数据域、维护主责、既有写入方/表/消费者、用途；`scripts/data_catalog.py` 提供隔离副本读取。
- `scripts/team_registry.py::resolve_team_alias`：首个实际消费者；特征构建已复用。其他身份/训练入口按后续切片迁移，不能称全部消费者已统一。
- `configs/data_sources.yaml`：旧运行配置只保留其实际消费者，不扩展为第二份公共目录。旧已删表/套餐描述不是运行事实；本批不静默修改来源开关。

目录的 implementation=existing 只指代码存在；account/coverage verification=unknown 是尚未核实。目录不含密钥、实际余额或运行观测，也不授予来源使用/抓取许可。P103 对真实发送统一管控，许可/配额未知不能自动启用。

## 身份与兼容

内部 PK 复用 teams/players/competitions/seasons/competition_seasons/official_matches，环境间同数字不代表同实体。外部标识键为 **entity_kind + source namespace + external_id**；外部 fixture 和官方可售比赛是不同实体类型，必须显式桥接，不能凭数据商赛程新增可售比赛。

官方历史继续保留 source_match_id、内部 match_id、business_date + official_match_code 及所有票据 FK。展示码按周复用，不能单独作为身份；改期沿用原事件引用而不是覆盖历史票据日期。新完整足球赛程/桥接关系在有实际结构变更的批次评审后增量加入，本批没有迁移。

resolve_team_alias 精确查询指定来源的既有别名，不按 team_name_cn/排序第一条/模糊名称合并。青年/预备/女队不能去后缀合并。同来源不存在→unresolved；两个不同候选→ambiguous；仅一个→resolved。返回最多两个候选已足以识别歧义，不承诺完整候选计数。读取不 commit、不改映射；上层沿用缺失降级。

目录 source_id `api_football` 显式指向旧表实际使用的 `apifootball` 别名命名空间；采集记录的 `api-football` 又是历史来源标签，后续观测适配须显式登记这些映射，不能靠替换连字符猜测。

`source-alias/v1` 是解析策略版本，**mapping_revision=None** 明确当前表没有不可变修订证据。不能把代码版本或当前别名冒充历史 as_of 结果。P104 才增加真实观测/映射修订。其他实体复用这一命名空间形状，具体解析以真实来源 ID/歧义审计为前提，未实现时保持未知。

赛季独立于联赛名称/日历年，competition_season 连接赛事与赛季；现有跨年/改期/中立场的完整适配仍按各任务推进。俱乐部/租借、国家队与分赛事资格是不同关系，可并存且需生效区间；转会不回写过去比赛的所属。P108 负责这些事实，不在当前 players 行上强行写一个全局当前队。

## 值、状态和单位

事实状态和采集状态是两个维度：

| 状态 | 定义 |
|---|---|
| value | 有可引用值；0/false 都是合法值，不能通过真假判断变成缺失 |
| confirmed_absent | 有覆盖/完整查询证据确认无记录，不是媒体没报道 |
| unknown / not_published / not_covered / not_applicable | 未知 / 未公布 / 来源不覆盖 / 不适用分别保留 |
| conflict / stale | 冲突 / 超过该信号有效期；不能隐瞒原值/证据 |
| not_requested / success / unavailable / quota_exhausted / forbidden / failed | 只说明采集过程，不直接证明有值或“无伤停” |

本批定义公共词汇，不把现存 NULL 批量标为某状态，也不伪造原始观测。P102 逐字段声明 units/语义版本/合法范围及模型子集；概率为 [0,1]，覆盖分为 [0,100]，距离 km，时长 minute/day，金额必须币种+估值日期且未知允许空。历史 market_value 概率代理不能在原版本内改名为真实金额；语义不兼容需新版本/工件兼容检查。

保留现行十维覆盖；覆盖、新鲜度、落盘可读、模型可用性分别记录。不能用目录注册或成功 HTTP 提高覆盖；技术连通不证明数据真实或预测提升。

## 时间与可用性

统一接口新时间使用带时区时间。`to_utc` 对 naive 时间必须显式提供原生产者 timezone；现有比赛北京时间 TIMESTAMP 用 Asia/Shanghai，审计 UTC-naive 需明确 UTC，不能按列类型统一推断。当前仅提供转换工具，没有回填/修改旧时间。

夏令时跳过/重叠的本地 naive 时间仍不能唯一确定时刻，转换拒绝并要求带偏移的 aware 时间。

P104 的事实记录至少区分 event/effective、published、first_available、verified、ingested、revision；读过去 cutoff 受真实可用时间约束。晚到旧公告不倒灌过去。刷新核验不伪造新发布时间；未重建的历史标明不可重放/研究重建。

共同读取后续沿用 environment + 标准实体 + cutoff + contract/feature/observation/run version + missingness/coverage + purpose/release status；一次返回有界批量，完整批次可见。当前 resolver 仅返回明确标注的当前身份，不假冒完整 match_context。

## 用途和读写矩阵

| 数据域 | 写入责任 | 可声明用途/限制 |
|---|---|---|
| 官方比赛/市场/赛果 | 现有官方存储 | 研究/预测/展示/结算/运维，第三方不能覆盖官方身份/结算 |
| 外部观测/特征/球员 | 已登记来源/构建任务 | 模型/模块共享获准事实，按截止/来源/版本读 |
| 新闻 | 现有核验/发布链 | 候选/影子/正式分离，不能绕过发布门槛 |
| 模型输出/工件 | 已登记训练/推理任务 | 按活动/影子与用途读，不因 active 就获准正式 |
| 资金/票据 | 原资金/票据事务 | 仅对应授权业务读取，通用模型/LLM 不可取得原始账本 |
| provider 凭据/会话 | 原 provider store | 仅凭据管理内部路径，不进入共享返回 |

`get_data_product(purpose=...)` 只检查元数据声明，调用者自报用途不是身份认证。当前数据库角色仍有广泛权限，P107 须在真实服务/API/角色上实施边界；不能宣称本批已完成运行时权限隔离。没有新增 HTTP 接口或 DB 授权。

## 后续变更与恢复

首次结构变更必须当批审账本/实际表、PK/FK/历史、索引/锁/体积，并在隔离副本 dry-run/恢复验证；不改已应用迁移。本批不修改 SQL/数据，无 schema rollback 需求。应用可回到基线 b2a2d0b0；历史工件/资金不受改写。

公共契约演进保持单入口。P102/P104/P106 在同一契约版本链上扩展，禁止各写私有库、来源配额、特征列表或评价 SQL；模型差异存在算法层。新增可选数据缺失不能阻断已满足输入的基础模式。
