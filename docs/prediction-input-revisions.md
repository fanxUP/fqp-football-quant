# P105 持久输入修订（显式试点）

本模块保存“当前哪些输入模式可用”，不保存模型概率、不登记模型工件、不创建投注/结算，也不自动切换旧预测。P106负责运行工件与整次预测溯源。原模型/新闻/发布/价格/财务规则仍须独立通过。`recommendation_eligible`只是输入门槛。

## 一次处理

配置固定版本的consumer key，一把key仅对应一个玩法、profile集合与有效期契约；变更契约使用新的受控版本。禁止每请求/每用户/每run生成key。profile来自内部已经验证的配置，`artifact_ready`声明不能替代落盘工件校验。

1. 原有任务显式调用`claim_prediction_input_revisions(conn, consumer_key=..., limit=8)`，然后立即commit。入口先按数据库时间扫描本消费者已到期的当前修订，最多32场，`SKIP LOCKED`递增头一次，再复用109领取。仅对仍在售、未停售且未开球的比赛做有效期重算，避免研究历史循环排队；官方状态或新事实事件仍正常通知。没有定时器、网络或自动重试。
2. 使用P104声明完整来源集，领取后在另一短事务捕获cutoff，再构建完整batch；commit。无需在计算期间持有头锁。新batch必须在当前头`changed_at`之后捕获，禁止用旧cutoff确认新版本。
3. `complete_prediction_input_revision(conn, claim, batch_id=..., play_type='spf', profiles=..., max_age_seconds=60)`复用109短事务围栏，同时追加不可变修订/回执并推进完成位置。调用者commit；失败rollback或按109释放/等待租约。重复完成无论重传参数是什么都返回原修订，不再次发表。
4. 读取确切ID调用`load_prediction_input_revision`或`prematch_feature_dataset`同名wrapper。必须使用顶层`recommendation_eligible`；嵌套`decision`是原始历史决策，不能单独用于当前授权。无缓存路径可绕过该DB读。当前读要求READ COMMITTED和非autocommit，拒绝旧MVCC快照假装当前。调用者及时结束读取事务。
5. 若将来缓存该结果，只可提交后刷新缓存；缓存故障由外层记录，不回滚事实/修订。缓存只能保留ID/展示载荷，执行前仍验证DB当前头和边界。本批未引入Redis，也未修改默认建议/出票读取。

## 持久引用与边界

`prediction_input_revisions`一条记录绑定consumer、match、input_version、play、确切feature_batch/cutoff、模式与完整状态、当时官方上下文、research_only、原因和valid_until。引用校验在应用写入边界执行；消费者是可信内部代码，不是任意SQL插件沙箱。旧记录不可UPDATE/DELETE/TRUNCATE，原输入与旧原因始终留存。读取动态返回`input_version_changed`/`official_context_changed`/`input_expired`/停售/开球等原因，不覆盖旧模式或向量。

官方数据由DB当前单条SELECT读取：官方比赛身份、源内精确team_alias（歧义/缺失不猜）、停售/开球/状态、玩法、赔率。该身份是当前映射，不能冒充历史时点映射。batch的球队/开球声明若不符只作为研究，不能通过输入门槛。仅spf/rqspf试点：唯一对应玩法且市场open、三项SP同一snapshot_time、market_id/handicap一致；缺失/不一致时回退市场待核实。P106将另做完整run与价格批次证明。

110触发器监听官方match关键字段UPDATE、market/odds INSERT/UPDATE/DELETE，同事务只递增已经有109头的比赛；无变化的整行UPDATE不通知。观察写入仍由109创建头，不回填旧数据、不监听batch/revision防止循环。匹配别名改变由当前读上下文比较立即阻止旧输入，通过已有有效期扫描再形成新待办；不宣称已有别名事件流。比赛层失效是有意保守的，同一场其他玩法需要重新处理，不影响其他比赛/历史。

有效期1..300秒，从cutoff而非完成时起算，默认60；并收紧到已选证据的保留策略expiry及已入库但未来available_at/赔率snapshot_time的最早边界。即使没有新INSERT，过期读取仍立即失效；有界领取入口在下次任务调用时重领。这里只处理已声明和已入库的事实，不能发现尚未获取的新闻/转会。来源断开/额度耗尽沿用P104策略：仍在保留有效期的旧成功可以继续使用；过期输入不能硬填，回退非独立市场参考/待核实。

完成前再次检查DB时间和官方上下文。晚于停售/开球/过期、身份/市场/名单证据不满足时，保存research_only及原因。研究记录随后即使恢复销售状态仍不可复活；必须有新输入版本/新修订并重新满足全部既有业务门槛。本模块不强迫使用赛后信息重建P104已禁止的运行时批次，只能保存已有赛前批次的迟到研究修订。赛后重建属于独立研究范围。

## 锁、权限与恢复

109完成锁head→consumer后只读官方行；官方写事务锁官方行后由触发器写head。完成回调禁止再写观察/官方行，避免逆序锁。相遇时官方写会等待短发布事务，成功后递增头使刚生成的旧输入失效。出现锁超时由原任务有界处理，不在模块重试。

110 up包含新空表、索引和触发器，lock_timeout=2秒、statement_timeout=15秒，整体事务；不改已有业务行。触发函数SECURITY DEFINER固定pg_catalog搜索路径/固定public表、撤销PUBLIC EXECUTE。源事实writer无新增UPDATE权限；隔离CI消费者只可读官方/观察/批次、写队列位置和INSERT修订，不能改事实/历史。CI schema clone因省略ACL必须再次显式撤权。

空修订表可down移除110功能；有修订时down拒绝，生产恢复策略为应用回滚、留存所有事实/修订。109有队列数据同样不可drop。生产部署还需独立审查、真实CI、角色/恢复/锁风险与部署证据；本地合成数据恢复演练不授权生产迁移。

固定样本：`tests/test_computation/test_prediction_input_revisions_postgres.py`，复用严格显式PG16 DSN/marker守卫。只在自有network=none、无映射端口、限额容器内运行。测试用短pg_sleep跨自然边界，没有新外部依赖或付费调用。
# P105/04：现有消费者的事件版本围栏

`run_model_prediction` 在读取特征和赔率前捕获 `PredictionInputFence`，派生玩法继承同一个 token。`model_storage` 先按 official match → odds FK key → input head 的顺序取锁，在插入事务核对版本；期间新事实到达则抛出 `InputUpdateSuperseded`，任务仅跳过该场/玩法，其他场继续。绝不在计算后重抓版本冒充重新计算。

`recommendation_prediction_loader` 使用共享 SQL 按 DB 当前头读取。已经有头的比赛必须有准确绑定的完整 token；畸形/缺失/错误版本仅排除相应预测，不对 JSON 强转。尚无头的旧消费者保留兼容；首次观测建立头后，旧的无头输出立即退出候选。删除头也不能复活曾绑定非空版本的预测。READ COMMITTED 以外的快照不能授权当前候选。

当日 Agent 历史票涉及过期输入时，推荐任务返回 `quality_status=input_invalidated`，保留旧票和预算记录，本次不重新分配全天虚拟预算。此处未删除票、改写资金/结算、撤销真实购买，也未声称前端所有历史视图或最终出票事务已迁移。当前候选检查仍是单次 SQL 的时间点，不提供对未来事实的保证。

这个 token **只证明计算期间没有跨过已留存的事件版本**，不是 P104 特征批次消费证明，也不是 P106 完整 run、工件或发布证明。原模型的特征读取并未自动切为观测版；P105/03 的模式修订仍由显式 pilot 使用，P106/P107 后续负责模型/消费者迁移。不能靠给旧模型加 token 宣称它已理解伤停、转会或使用当前球员特征。

运行角色需具有官方 match/odds 的 SELECT 与行锁所需 UPDATE 权限，以及 dirty head 的 SELECT/UPDATE 行锁权限；消费者不执行事实更新。生产最小权限与锁风险必须在切换前核准。109/110须先迁移再部署代码；本批没有新增SQL、依赖、HTTP或调度器。回退应用不能删除109/110的事实或修订。

发布行锁使用事务局部 `lock_timeout<=500ms`（保留更短的原配置，提交/回滚自动恢复），锁竞争或版本变化时仅回滚跳过该场/玩法，job报告 `input_updates_skipped`。候选的销售/开球比较使用本次 SQL 的 `statement_timestamp()`，不会因事务较早开始而停在旧的 `NOW()`。尚未完成的整次计算可能已经提交部分历史行，候选版本门槛会排除已过期行；整次run原子身份仍由P106建设。
