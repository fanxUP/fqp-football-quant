# 足球补充数据：球探采集方法与 FQP 接入

本模块来自用户提供的本地采集项目 `/Volumes/Nas/足球数据`。采集、解析、原始缓存和固定样本已复制进 FQP；源目录继续保留。统一入口为 `python -m scripts.titan007_data`，采集实现位于 `scripts/sources/titan007/`。这份文档是 FQP 的现行操作入口，两份附带的原文仅作接口与字段参考。

## 历史明细回填（2026-10-29）

离线工具 `scripts.titan007_history` 清洗来源库中的比赛、技术统计、事件、实际/预计阵容、历史伤停、转会、球员统计、派生出场分钟和第三方赔率。迁移 `119_football_history_backfill.sql` 在同一个共享 PostgreSQL 建立历史批次、来源比赛与分类明细；不另建业务数据库。结构与实际生产启用、逐域数量以本次回填回执为准。

原采集时间缺失不阻止历史事实保存，未知字段保留为空，服务端记录真实入库时间。来源旧脚本会从 `updated_at` 派生 `first_fetched_at`、从替补事件和默认 90 分钟推算出场时间、从 `updated_at` 复制预计阵容的 `announced_at`，也会按伤停原因关键词生成 `kind` 分类；这些字段保留来源解释，不能升级为真实发布时间、采集时间、直接报告的出场分钟或额外的伤停证据。

两份比赛目录中的球队、开球时间或完场比分冲突会隔离该来源比赛及其相关记录。技术统计规范数值和百分比，并区分半场与加时；未完成比赛的赛后明细不回填。实际阵容保存名单完整性；预计阵容始终为预测资料，伤停不自动成为当前缺阵，转会不等于注册资格已核实。赔率全部为第三方市场资料，原字段 `live` 不单独证明滚球状态；缺少年份的变化时间保留原文，`timeline_usable=false`。

### 赔率变化年份补全

迁移 `120_football_history_odds_timeline.sql` 提供共享读取视图 `football_history_odds_timeline`，不修改119号迁移、已发布批次或原始 `value_json`。该视图的独立列 `change_at`、`time_basis`、`time_resolution_reason` 和 `timeline_usable` 是补全结果；原 JSON 内同名字段仍是回填时的原始质量标记，消费者应明确读取视图列。

需同时应用 `121_football_history_odds_parallel_safety.sql`：日期合法性校验包含异常处理，须禁用该查询的并行执行，避免全量读取时发生子事务错误。该修正只调整函数属性，保留已应用的120号迁移摘要。

- `MM-DD HH:mm` 按站点北京时间，枚举开球年份的前一年、当年、后一年；只有开球前180天至后12小时内的唯一有效日历时间可推定。跨年和闰日使用真实日历校验，无法推定的记录继续可查，不阻塞其他数据。
- 以批次、来源比赛、公司、赔率类型及采集来源共同分组，按原 `seq` 校验。允许正序、倒序及相同时间；检查会跨过缺失时间记录。已解析时间出现来回倒序，或序号缺失/重复时，整组不提供可用时间轴，不强行调年份使其顺序成立。
- `time_basis=inferred_year` 表示推定年份，`source_full` 表示来源已有完整日期，`unresolved` 表示未解决。时区假设另由 `change_timezone_basis` 说明。`timeline_usable=true` 只表示通过上述规则，可用于带标识的参考走势；不证明来源当时已发布、模型当时已获取或属于赛前盘，也不允许直接冒充无泄漏回测样本。
- 120/121的基础规则版本为 `titan007-odds-year/v1`。按 `batch_id`、`source_match_id` 查询单场，避免页面请求每次全表扫描；比赛详情的新增参考读取见下文，原有赔率走势页与模型输入仍未切换。

#### 来源年份与延期赛程修正（v2）

在120/121之后应用 `122_football_history_odds_evidence.sql`。v2增加同一共享库内的稀疏证据表 `football_history_odds_time_evidence`，只为已核验的原记录保存时间依据，不复制整套历史事实。证据关联批次、原记录键和精确原值，逐条保留来源URL、响应摘要、实际核验时间与身份信息；证据本身也不可覆盖、删除或清空，应用账户只读。

- 来源已有完整日期，或重新核验到明确年份时，保留为 `source_full`。开球前180天窗口只用于普通缺年推定，不能据此拒用已经明确年份的早期开盘。原始第8字段年份在采集解析时合入 `change_time`，经现有SQLite文本列保存；旧格式仍保留月日原文，非法明确日期继续交由日历检查拒用，不能换年掩盖错误。
- 有官网与相同来源比赛身份共同支持的延期赛程，以独立 `effective_kickoff_at` 提供新参考时间，`kickoff_at` 保留原始回填值，`kickoff_time_basis` 说明依据。同一批次同场不允许矛盾参考时间。不能由赔率最后变化时间反推真实开球，也不能把所有赔率都标为赛前。
- 2022世界杯这一批早盘仅在已核验赛事范围、同组已有窗口内锚点和连续顺序支持下添加逐条证据，仍为 `inferred_year`，原因 `event_sequence_evidence`；没有全局扩大缺年窗口。来源明确年份证据的原因是 `source_year_evidence`。
- 整组顺序检查继续覆盖补正后的时间；证据存在也不能绕过重复序号或来回倒序检查。核验日期不等于原始采集日期，走势可用不等于可进行无泄漏赛前回放。

`scripts.titan007_odds_evidence` 离线核对已冻结响应的摘要、比赛/球队身份、序号和赔率原值后生成证据包，不发送网络请求。导入调用 `import_package` 默认回滚；正式导入前核对已发布批次摘要，冲突原值或既有证据不同会回滚，不静默覆盖。迁移、证据导入和迁移账本可以在同一事务内验证后提交。

```bash
.venv/bin/python -m scripts.titan007_odds_evidence \
  --verification /absolute/evidence/verification.json \
  --batch-content-sha256 <published-batch-sha256> \
  --official-schedules /absolute/evidence/official-schedules.json \
  --output /absolute/evidence/time-evidence-package.json
```

```sql
SELECT source_record_key, value_json->>'change_time' AS original_time,
       change_at, time_basis, time_resolution_reason, group_direction,
       timeline_usable, change_timezone_basis,
       effective_kickoff_at, kickoff_time_basis, time_evidence_url
FROM football_history_odds_timeline
WHERE batch_id = 1 AND source_match_id = 2389577
ORDER BY change_at NULLS LAST, source_record_key;
```

```bash
# 只读来源并生成有摘要的清洗传输包；不连接数据库、不抓取网页。
.venv/bin/python -m scripts.titan007_history --export /absolute/new/package-directory

# 目标库启用 119 后，使用有历史导入权限的账户执行。
# DATABASE_URL 必须明确指定本机回环地址；默认演练并回滚。
.venv/bin/python -m scripts.titan007_history --import-package /absolute/package-directory
.venv/bin/python -m scripts.titan007_history --import-package /absolute/package-directory --apply
```

导入验证压缩文件及解压内容摘要、记录数量、数据库约束后原子发布。重复相同包返回 `unchanged`；失败回滚整个事务，已发布批次不可修改、删除、追加或清空。普通应用账户仅有历史表读取权限，显式导入账户负责写入。未知规范球队、球员和官方比赛身份保留为带命名空间的来源身份，不能按同名强行合并。

后续导出在同源比赛身份、开球和已知赛事一致时，从 `league_results` 保留赛季，元数据注明 `season_source_table`；旧缓存 `matches.season` 可能是短年份或派生值，不能直接视为联赛赛季。两个目录的已知赛事冲突时隔离，不借用另一个赛事的赛季。此修复不改写已发布批次，旧批次缺失的赛季仍为空，不能因此重新全量导入。

历史导入CLI要求显式回环 `DATABASE_URL`，同时拒绝外部 `hostaddr`、service和 `PGHOSTADDR` / `PGSERVICE` / `PGSERVICEFILE` 环境路由；连接时固定数字回环地址，避免DNS或libpq默认路由把写入转向其他主机。通过SSH在目标服务器本机运行同样适用；不会据此连接其他数据库。

迁移 `123_football_history_odds_invalid_timezone.sql` 在122之后加固日期函数：非法时区偏移（如 `+25:00`）返回 `unresolved` / `invalid_timezone_offset`，不让单条坏数据中断其他赔率读取。保留正常候选、视图列和并行禁用属性；119—122已应用摘要保持不变。123已随2026-10-30服务器发布应用，提交`7562775`；未重导原批次。

GitHub CI在隔离集群创建专用 `fqp_history_test_ci`，设置 `FQP_HISTORY_TEST_DSN` 后运行本文件对应回归；JUnit校验要求该模块存在且零跳过。手动测试也必须使用 `127.0.0.1` 上以 `fqp_history_test_` 开头的一次性数据库；缺少DSN时本地数据库用例会跳过，不构成发布验证。

模块可查询 `football_history_available` 视图，按明确的 `batch_id` 与 `domain` 读取，避免多批重复计数。视图只展示已发布批次，并提供已核实的规范球队与官方比赛链接。当前官方结算、旧阵容投影和预测输入链路不自动读取这批历史明细；接入训练/特征时应单独验证字段用途。同场赛后数据不得成为同场赛前特征，但可以在核实后用于后续比赛的历史分析。

### 比赛详情历史参考读取（2026-10-30发布）

现有比赛详情页新增“历史参考”，从共享PostgreSQL读取技术统计、事件、实际阵容、预计阵容、历史伤停和第三方赔率变化。后端共用入口为`scripts.football_history_storage.match_history_reference`；浏览不读取SQLite、不触发采集。该接线已随`6bf375e`发布到服务器，并通过两主题、桌面与手机四组浏览器核验；它只供资料查看，不代表模型已经消费历史数据。

会话保护的`GET /api/matches/{official_match_id}/history-reference`接受`domain`（默认`match_stats`）、`batch_id`、`limit`（1—100，默认50）和`offset`（0—10000）。首次仅从已发布的`titan007`批次、已核实的`official_match_id`链接选取最新批次，同批多个来源身份返回`ambiguous`而不任选；没有映射返回`unmatched`，所选批次没有该比赛则404。页面拿到首个批次后将它固定到分类切换和分页请求，避免新发布过程中混批。

返回来源比赛、批次及内容摘要、该场分类数量、分页记录。每条包含原始`value`与独立`timeline`；赔率采用视图的`change_at/time_basis/time_resolution_reason/timeline_usable`，组内完整顺序校验先于分页。读取限定单场/批次，事务只读且语句上限5秒；结构未就绪或超时返回可重试503。不要对每次页面读取运行全库统计。

入库时间不等于来源发布时间，赛季未知保持未知，真实0保留，预计首发和名单不完整状态独立显示，历史伤停不冒充当前健康信息。`player_transfers`、派生出场分钟与模型训练接线不在此入口内。该页面消费仅供查看核对，不自动改变模型概率或官方结算。

### 历史训练候选清单（本地实现，尚未发布）

`scripts.football_history_training`从同一共享PostgreSQL的已发布批次生成离线候选清单，复用规范球队ID，保留`titan007:match`来源身份。必须指定批次、赛事、研究赛季窗口和带时区的`as_of`；不把所有赛季混在一起，也不根据年份补造来源赛季。窗口最多400天，候选最多5000场，超过上限须缩小范围，不静默截断。

完场、比分、规范球队、来源赛季冲突、同场重复身份、加时/点球和最终球队场次门槛分别检查，清单包含逐场排除原因。0比分正常保留。最低场次默认3，可显式调整；它只是候选检查参数，不改变现行模型要求。移除稀疏对手后会重新计算场次，直到最终样本满足声明条件。

原始公布/采集时间缺失不阻止今天审查历史资料。`label_available_by`保持未知；批次的`imported_at`单独保留，它是创建批次时记录的时间，不是原始发布时间，也不精确证明事务何时提交可见。早于批次创建的`as_of`直接拒绝；晚于创建只通过必要条件检查，仍不证明历史时点已经可用。`as_of`用于候选开球筛选，不赋予赛前重放资格；来源旧`updated_at/first_fetched_at`不会升级为赛前证据。源比分仍为`source_reported_full_match`，尚未证明为体彩90分钟比分，因此清单明确标为非生产就绪、未验证时间重放、未验证SPF标签；不能直接传入现有官方Maher训练器或借此声称模型效果提升。

```bash
# DATABASE_URL须显式配置为本机回环数据库；读取不会抓取、导入或训练。
# 下列时间是显式研究范围示例，as-of需根据实际审查时点填写。
.venv/bin/python -m scripts.football_history_training \
  --batch-id 1 --competition-id 36 --season 2026-2027 \
  --window-start 2026-07-01T00:00:00+08:00 \
  --window-end 2027-07-01T00:00:00+08:00 \
  --as-of 2026-10-30T12:00:00+08:00 \
  --output /absolute/research/history-training-candidates.json
```

读取只接受空闲、非autocommit连接，使用独立的repeatable-read/read-only事务和5秒语句上限，结束后回滚释放快照，不接管调用者已有事务。摘要覆盖批次内容摘要、范围、逐场数据、排除原因和用途限制，可用`verify_history_training_manifest`重算；这是完整性核对，不是外部真实性认证。输出文件为有界研究工件，已存在时拒绝覆盖；不建立第二个业务库。

### 官方比分对照的单模型离线研究（本地实现，尚未发布）

`scripts.football_history_research`额外固定同源已发布的`league_reference_batches`批次，逐场核对来源比赛ID、主客规范球队和开球时刻。核对一致才建立`study_season`，逐行保留证据批次、内容摘要和原始`source_season`；不会把所有“2026”全局替换为“2026–2027”，也不改写历史批次。参考赛程的更新比分不覆盖旧批次中的未完场状态。

只将拥有真实官方比赛/赛果ID、唯一规范球队、相同主客方向及开球时刻、已结算且比分完全一致的记录适配到现有`TrainingDataset`，调用原有`fit_maher_poisson_dataset`。来源ID不会伪装为官方结果ID。常规时间字段名不是充分证据：旧缓存`home_score_rt`会由`derive_match_meta`从总比分复制，因此该入口采用核对一致的`official_results.full_home_goals/full_away_goals`标签；来源独有的比分使用下面独立的来源标签研究入口。

官方子集重新迭代核验每队场次，再生成现有官方训练清单；外层研究包保留来源映射、候选/排除原因、用途限制、相关源文件摘要及拟合状态。`eligible_matches`与成功收敛的`fitted_matches`分开统计；数据不足或不收敛仍输出诊断包，CLI退出码为2，不能称训练成功。成功导出且收敛退出码为0；已有输出拒绝覆盖。

```bash
# 在已核实的本机数据库上执行；不抓取、不写业务表，不保存/启用model_versions。
.venv/bin/python -m scripts.football_history_research \
  --batch-id 1 --reference-batch-id 2 --competition-id 36 --season 2026-2027 \
  --window-start 2026-07-01T00:00:00+08:00 \
  --window-end 2027-07-01T00:00:00+08:00 \
  --as-of 2026-10-30T12:00:00+08:00 \
  --output /absolute/research/history-official-research.json
```

三类输入在同一repeatable-read/read-only快照中读取，随后回滚关闭连接，拟合不持有数据库事务。只读核验历史批次1/参考批次2得到：80场中79候选、1场旧批次未完场；56场官方标签符合核对，覆盖19队、各5—7场，另23场缺官方关联。56场本机离线拟合35次迭代收敛。这只是本批、单赛事、单研究窗口的通路验证，不代表全部历史资料覆盖，更不证明预测能力提升。

56场官方标签发布时间均未知，保持`None`；这不阻止今天的离线研究，但正式清单`cutoff_at=None`，外层明确`point_in_time_replay_verified=false`。不能冒充历史时点回测、把事后阵容当赛前特征或将收敛当效果验收。研究包不生成生产激活身份，不改现行训练器/工件指纹，不改变线上概率。独立时间切分评价仍需区分事后静态排序与真实已知时点验证。

### 来源全场比分的离线研究（本地实现，尚未发布）

`scripts.football_history_source_research`消费上一入口保存的`history`和`official_rows`输入回执，只读本地文件，不再次连接服务器、请求网站或建立新数据库。它使用独立的`fqp.history-source-labels/v1`契约，将研究目标固定为`source_reported_full_match`。逐场标签ID为`titan007:match:<来源ID>`，保留来源/规范球队、原赛季与研究赛季、精确赛程证据、历史批次与摘要以及未知的公布时间。

有官方关联的记录，仍须逐场核对官方身份、状态及比分，成功后标记`official_corroborated`并保留真实官方赛果ID。官方冲突、未结算、关联缺失赛果或缺少核验行会明确排除，不能降级成来源独有数据放行。仅当同一已保存快照中的完整官方LEFT JOIN行为空，且原候选明确无官方关联时，才标记`source_only`。这表示来源身份和标签可追溯，并不证明第三方与官方同等可信。排除后重新迭代检查每队覆盖，摘要和计算数组来自同一有序清单。

数值优化复用现行`_nll_maher_with_gradient`目标；研究适配器使用与官方拟合器一致的初始化、边界及L-BFGS-B设置，并通过同样本参数等价回归。不伪造`TrainingDataset`、官方比赛或赛果ID，不修改现行训练/工件指纹。它仍是无时间权重的基础通路验证，尚未加入转会、阵容或球队动态变化，也不替代后续动态模型。

```bash
# 输入是已有只读查询回执。只在本机拟合，不连接数据库。
.venv/bin/python -m scripts.football_history_source_research \
  --input /absolute/research/history-inputs.json \
  --output /absolute/research/history-source-fit.json
```

输出包含候选、来源标签清单、拟合状态、输入文件及代码摘要和用途限制；输入最多32MiB、候选最多5000场，输出已存在时拒绝覆盖。数据不足、不收敛或非有限优化结果不计入成功拟合，诊断包退出码为2。数值收敛且成功导出才退出0。

2026-10-30真实回执本机拟合结果：79场、20队、每队7—8场，其中56场官方核对、23场来源独有；优化收敛。原批次仍未完场的第80场没有混入。所有来源发布时间仍未知，研究包明确`production_ready=false`、`point_in_time_replay_verified=false`、`spf_regulation_score_verified=false`，没有模型持久化、生产激活或线上概率变化。29项新固定样本/本地CLI回归通过。后续时间切分结果见下；来源全场比分研究的收敛不能当作体彩90分钟模型效果验收。

### 来源比分的时间切分评价（本地实现，尚未发布）

`scripts.football_history_source_evaluation`读取同一份本地输入回执并重建来源标签。复用现有日历窗口生成器、Maher研究拟合、生产同款进球率/比分矩阵转换和Brier/LogLoss/RPS评分，不要求补造官方身份或赔率。默认按北京时间划分两个7天滚动评价段与最新7天留出段；每段训练开球必须严格早于该段起点减24小时。在训练子集内部迭代检查每队至少5场，与现行概率转换门槛一致，不借用全79场参数或未来球队场次。24小时是本研究的开球间隔约定，不是已证实的赛果发布时间。

两个基线分别为胜平负各1/3、该段实际保留训练赛果的加一平滑频率。逐场只在模型能生成概率时成对评分，未见球队、拟合失败、无有效进球率均保留排除原因；空窗口或无评分窗口使整份评价为`incomplete`，CLI导出诊断并退出2。部分覆盖会明确记录候选/评分/排除数量，不冒充完整覆盖。缺赔率仍可独立评分，市场比较标为`not_evaluated`。聚合按各段不同测试行加权，不把段均值简单平均。

```bash
.venv/bin/python -m scripts.football_history_source_evaluation \
  --input /absolute/research/history-inputs.json \
  --output /absolute/research/history-source-evaluation.json
```

CLI只处理本地文件；输入最多32MiB，候选最多5000场，最终规范JSON最多5MB，输出已存在时拒绝覆盖。输出保存逐段训练清单与参数、逐场预测和评分、来源标签/输入/代码摘要、基线与覆盖。没有数据库写入、模型持久化或自动晋级。

本机真实结果：10月6—12日/13—19日/20—26日分别用50/59/69场训练，评分9/10/10场，全部29场有概率、无排除。三个训练均收敛。合计模型LogLoss为1.209688，均匀基线1.098612、频率基线1.093231，越低越好；最后10场模型1.584160，明显差于两基线。最后10场全部有官方比分核对，不能把这段劣化归咎于来源独有标签。21项新回归及实际CLI通过表示实现可运行，不表示模型效果通过。

这仍是当前回填批次的事后时间留出；首次发布时间未知，且79场此前已做全量拟合，没有事先封存盲测集，不能声称严格赛前重放或前瞻优势。最新块本次查看后不能在调参时反复宣称未见。样本仅一个赛季早期，尚无转会/注册/伤停特征；当前基础模型缺少效果优势证据，不据此替换线上模型。后续应在训练侧验证收缩、概率校准与不确定性，再用预先固定的后续新比赛检验，逐步接入有时间证据的阵容变化。


### 训练侧收缩诊断（本地实现，尚未发布）

同一评价脚本新增可选`--development-cutoff`模式，仅用显式北京时间零点之前的开发标签，之后标签不评分。既有Maher目标已经有0.10球队ridge；本模式固定比较额外0/1/5（合计0.10/1.10/5.10），只收缩球队攻防参数，不额外惩罚主场优势与联赛截距。开发集内部再做两个7天窗口、24小时开球间隔和每队至少5场检查。所有候选必须对相同开发行完整评分，至少10条，失败/缺覆盖不选参；主指标预定LogLoss，1e-8内平手取较小收缩，不能事后改用最有利指标选参。选中后只在开发集重拟合，不保存或启用生产工件。

```bash
.venv/bin/python -m scripts.football_history_source_evaluation \
  --input /absolute/research/history-inputs.json \
  --output /absolute/research/history-training-diagnosis.json \
  --development-cutoff 2026-10-19T00:00:00+08:00
```

输出已存在拒绝覆盖，输入32MiB/规范JSON输出5MB界限与原模式一致；诊断不完整或最终重拟合失败退出2。默认不带此参数仍是原时间评价模式。`nll`包含惩罚，不能在不同收缩强度间直接比较；选择只比较开发预测LogLoss。输出保留每个窗口真实训练清单/参数、基线、逐行概率、来源证据、覆盖、选参、描述统计及代码/输入摘要。

2026-10-30本机结果：截止前69场/20队（46官方核对、23来源独有），最后10场未重评。两个开发窗口10月5—11日/12—18日分别用50/55场训练，评分9/10场。19场合计LogLoss：额外0为1.017667、额外1为0.983008、额外5为0.991304；频率基线1.078219。按预定主指标选额外1并在69场重拟合收敛。三个候选各19条，共57条概率/评分重算一致；68项不同关联回归通过，其中18项本轮新增。

这19场是探索选参样本，部分此前已查看，不能将赢家的开发分数当独立效果证明。更强收缩降低了本批球队参数平方范数，但不足以证明上一轮最后10场退化的根因。复用原温度校准100条拟合+至少25条后段验证要求；目前仅19条窗口外预测，明确`insufficient_samples`，没有校准参数或应用。该要求是跨比赛的校准验证门槛，不是每队需125场，也不阻断现有基础预测。球队6—7场、19条预测及高置信数量均为描述统计，不冒充有效样本量或置信区间。后续冻结候选做新比赛前瞻记录，逐步补入真实时间可核验的转会/阵容/伤停信息；没有替换线上模型、生产访问、提交或部署。

## 当前可以做什么

- 一致复制已有 SQLite 数据库和图片；使用 SQLite 在线复制 API 读取已提交状态，包含 WAL 中已提交的数据，不直接复制正在使用的数据库文件。目标已存在时拒绝覆盖，失败清除临时副本。完成后保留内容摘要和校验清单。系统临时盘空间足够时，在同一顺序读取中计算摘要并生成临时校验副本，避免 NAS 上的逐页随机校验；校验副本随后清除，不作为运行数据库。
- 在 FQP 内抓取比分、历史赛果、比赛统计、事件、阵容、联赛赛程/积分榜/射手榜、球队资料、教练、转会、第三方赔率及变化史、伤停报告和图片。具体覆盖取决于来源；接口存在不等于每场都有数据。
- 使用 `inspect_cache`、`open_source` 和 `iter_source_rows` 共用同一份原始缓存。读取只读，不触发采集；缺失库不会被静默创建为空库。
- 每批默认至多 40 次请求，处理上限默认 20 个对象，历史日期每批至多 31 天。请求至少间隔 3 秒，默认再加随机间隔和阶段暂停；同一缓存只允许一个采集/复制进程。
- 遇到 401/403/429 立即停止整个批次，保存冷却记录，后续批次在冷却结束前不发请求。默认限流冷却至少一小时，访问拒绝至少六小时；不自动重试；仅跟随相同已登记域名内至多 3 次重定向，禁止 HTTPS 降级，重定向请求也计入预算。没有后台常驻循环。
- 每次采集保存运行回执，包括时间、请求次数、响应状态、路径和字节数；失败或被限流不会报告为成功。
- 项目入口共用同一缓存的 UTC 日请求账本，每日上限 100 次；请求和重定向在发送前预占，失败不退还，账本损坏时停止。它不跨不同缓存、电脑或旧采集项目自动统一计数，后续调度前仍需明确唯一发送者。
- `scripts.titan007_refresh` 可有界更新已核实的英超赛程/榜单，先冻结和核验，再选择发布；数据库发布失败可按原 `run_id` 重试，不再次访问网站。默认只准备数据，没有自动定时任务。

采集缓存属于**本地来源暂存层**。在此基础上，已实现英超 2026–2027 的共享 PostgreSQL 参考数据导入，以及现有联赛页的后端读取适配；真实缓存已在隔离 PostgreSQL 中完成闭环验证。现有 Docker Desktop FQP 测试栈（前端 18066、API 18080）已启用，不使用缺少现行基础表的原生 5432 旧库。后续有界更新只用 3 次公开请求，已将 380 场、20 队、三类完整榜单发布为批次 `5`：来源截止 2026-10-29 15:01:20，80 场完场，采到时间独立留存。服务器发布、模型输入和自动调度仍待后续。

### 固定候选的赛前记录与后续评分（本地实现，尚未发布）

`scripts.football_history_prospective`提供`freeze / predict / score`三个本地入口。来源全场比分研究不能套用正式SPF工件；线上`observed_maher_shadow`仍使用正式模型，本入口不修改它。复用现有run manifest、Maher概率计算与LogLoss/Brier/RPS，仅保存研究JSON，不建立另一业务数据库，不向正式模型/推荐/彩票写入。

`freeze`同时校验既有诊断摘要、原始输入回执字节摘要、开发清单/参数/代码指纹，保留原69场开发重拟合及额外ridge1，不重新拟合、校准或重评最后10场。CLI使用实际UTC时钟，没有可回填的`--as-of`。固定冻结后14天（且不超出研究赛季窗口）的观察范围；当前真实候选在北京时间2026-10-30 12:59:18封存，规范摘要为`941628c115b12495406d2ff1071ba155ec6c0a7a0b572eab7b4aab7dfa5a841b`。同日13:21:02已用统一数据库真实赛程形成首批20场赛前记录，尚无新赛果评分。

`predict`对输入快照中所有合格比赛计算概率，保留每项排除原因与供给/预测/排除数量。已经开球、完场/带比分、超出观察窗、进入训练集、缺规范球队、重复来源ID或同一事件不能静默混入。计算完成再次核对时钟，计算中开球的比赛剔除；CLI还在输出写入后核对，过时输出删除并报错。模型代码指纹变化后拒绝继续使用旧候选；局部文件hash和时钟不是外部可信存证，不能保证人工修改后不可重写。各次输出拒绝覆盖，跨多次输出汇总时须按来源比赛ID取最早有效记录，不能重复累计；本批未实现跨文件汇总器或自动调度。

赛程快照与后续赛果快照共用以下明确结构，之后可由已发布`league_reference_batches/fixtures`只读生成，不重新抓取或复制业务库。本轮没有连接生产获取真实待赛快照。`captured_at`是读取完成后实际观测时间，不能用来源未知公布时间替代；`batch.imported_at`单独留存。缺可选赔率、阵容、伤停不阻断这个基础比分候选，但不能据此宣称已建模这些因素。

| 字段 | 含义 |
| --- | --- |
| `version` | `fqp.history-source-fixtures/v1` |
| `source_name/source_competition_id/study_season` | 固定`titan007 / 36 / 2026-2027`，与冻结范围相同 |
| `captured_at` | 带时区的实际观测时间，不能晚于运行时钟 |
| `batch` | 已发布批次的`id/state/content_sha256/imported_at`，状态为`published` |
| `fixtures` | 最多5000行；每行来源数字`source_match_id`、规范`home_team_id/away_team_id`、带时区`kickoff_at`、`status`与`home_goals/away_goals` |
| `score_scope` | 后续评分必须为`source_reported_full_match`，不能假冒90分钟SPF |

预测行需`status=scheduled`且比分为空。`score`只读取保存的预测和后续快照，逐场核对来源ID、主客方向及开球时刻；改期/身份变更明确排除，缺赛果/未完场保持待定，布尔/负数/不完整比分不评分。赛果观测必须晚于预测计算完成与该场开球；新赛果不会重拟合参数或修改原概率。三种模型/基线指标严格在同一批已评分比赛上计算，保留覆盖与来源批次。缺赔率不阻断概率评价，也不产生市场或盈利优势结论。`awaiting_results/partially_scored/evaluated`仅为评分进度，`promotion_allowed=false`始终不自动启用模型。

```bash
# 用已保存诊断和原始输入回执封存，不进行训练。
.venv/bin/python -m scripts.football_history_prospective freeze \
  --input /absolute/research/diagnosis.json \
  --receipt /absolute/research/original-inputs.json \
  --sha256 PREVIOUS_DIAGNOSIS_CANONICAL_SHA256 \
  --output /absolute/research/frozen.json

# SHA256始终是上一步JSON内的规范摘要，不是带排版JSON文件的字节摘要。
.venv/bin/python -m scripts.football_history_prospective predict \
  --input /absolute/research/frozen.json \
  --receipt /absolute/research/observed-fixtures.json \
  --sha256 FROZEN_CANONICAL_SHA256 \
  --output /absolute/research/forecast.json

.venv/bin/python -m scripts.football_history_prospective score \
  --input /absolute/research/forecast.json \
  --receipt /absolute/research/later-results.json \
  --sha256 FORECAST_CANONICAL_SHA256 \
  --output /absolute/research/score.json
```

输入最多32MiB，拒绝重复JSON键/非有限值，输出最多5MB且拒绝覆盖；没有合格预测时保留排除诊断、退出2，缺赛果正常输出待定状态。固定样本端到端CLI验证使用临时合成赛程，不冒充真实前瞻证据。34项本地回归、Ruff和Mypy通过，运行源码未变，真实记录阶段沿用这些证据。

首批实际读取在北京时间2026-10-30 13:20:51完成，服务器`100.121.47.26`仍为`6bf375e`且工作区干净，4项服务active。通过stdin内存脚本，以fqp账号在REPEATABLE READ/READ ONLY事务中完整导出英超2026–2027最新已发布批次2的380场；本事务写入0，读取后回滚关闭连接，没有服务器文件、服务或模型变更。20队主客双循环380对齐，0缺开球、0未映射队，未来窗口20场全部记录；其余80场已开球、280场超出观察窗口，均有排除记录。首场按该批次为北京时间10月31日20:30，最后一场11月9日00:30，观察截止仍为11月13日12:59:18。

赛程来源截止为10月29日15:01:20，采到于16:05:06，导入于19:30:56；本次读取时距来源截止约22.33小时。读取统一库不等于实时重抓网站；全批次覆盖已核对，但外部完整赛程及最新改期未另行联网核实。首批预测规范摘要`2bfc767c43f410ccc7061e9f2ced30f1359e05c3f1b783550095e2dc997c3fa1`，计划目录保存带`20261030T052051832607Z`的FIXTURES/CAPTURE/FORECAST及逐场概率表。固定参数、训练清单、14个运行源码和run身份已自核；不是独立发布审查。仅此一份真实预测文件，20场不能通过重复运行累加为更多样本。

下一步等比赛实际结束后，沿用现有有界更新入口取得并发布新的完整参考批次，再只读捕获独立新赛果，按原预测文件执行score。缺赛果保持待定，改期或主客/身份冲突单列；不重新训练或更改本批概率。当前研究未接自动调度，未提交部署、未改变线上模型，不宣称效果更好或P105/P106完整效果验收通过。

## 数据和代码的位置

| 内容 | 路径（相对项目根目录） | 是否提交 Git |
| --- | --- | --- |
| 采集/解析实现 | `scripts/sources/titan007/` | 是 |
| FQP 统一入口、快照与只读读取 | `scripts/titan007_data.py` | 是 |
| 分类与别名初始配置 | `configs/titan007/` | 是 |
| 来源目录声明 | `configs/data_catalog.yaml` 的 `titan007` | 是，仅元数据 |
| 离线赛季预览、映射演练、事务导入 | `scripts/titan007_import.py`、`scripts/league_reference_storage.py` | 是 |
| 有界更新、冻结回执、发布重试 | `scripts/titan007_refresh.py` | 是 |
| 英超身份、赛季窗口和赛制配置 | `configs/titan007/league_import.json` | 是 |
| PostgreSQL 参考批次结构 | `sql/118_league_reference_data.sql` | 是，运行库启用时迁移 |
| 原始数据库 | `data/sources/titan007/titan007.db` | 否 |
| 队徽和头像 | `data/sources/titan007/images/` | 否 |
| 运行配置、映射待核对表 | `data/sources/titan007/config/` | 否 |
| 复制清单 | `data/sources/titan007/SOURCE_SNAPSHOT.json` | 否 |
| 请求回执、冻结数据、冷却/每日计数/间隔 | `data/sources/titan007/runs/`、`cooldown.json`、`daily-usage.json`、`refresh-state.json` | 否 |

可以通过 `FQP_TITAN007_DATA_DIR` 或入口的 `--data-dir` 指定原始缓存位置。原始数据库是可替换、可重新导入的来源材料；模型和页面的正式数据应发布到 FQP 已有的 PostgreSQL，不能各自长期维护另一套业务库。现有 SQLite 不是新的业务事实库。

核心解析使用项目已有的 httpx、BeautifulSoup 和 Python 内置 HTML 解析器。原采集器所需的 requests/lxml 没有作为新的核心依赖引入。访问原 `zq/vip/info` 接口可安装可选传输依赖：

```bash
# 使用项目自己的 Python 环境。此依赖不加入服务器默认 requirements.txt。
uv pip install --python .venv/bin/python -r requirements-titan007.txt
```

## 常用操作

从 FQP 代码根目录执行。下列日期与 ID 是本次资料库的明确来源示例；以后应先查来源目录与赛季，不根据当前年份猜赛季，也不把外部 ID 当 FQP 内部 ID。

```bash
# 首次复制已有数据；目标已存在时不会覆盖。
.venv/bin/python -m scripts.titan007_data snapshot --source /Volumes/Nas/足球数据

# 只读统计；不调用网站、付费 API 或生产数据库。
.venv/bin/python -m scripts.titan007_data inspect --tables matches league_results lineups

# 获取一次当天比分快照。
.venv/bin/python -m scripts.titan007_data collect --max-requests 1 -- live

# 按日增量回填，已有比赛按来源 ID 更新。
.venv/bin/python -m scripts.titan007_data collect --max-requests 4 -- history --start 2026-10-28 --end 2026-10-29

# 当前库核实：英超的球探 ID 是 36；25 是日本职业联赛 J1。
.venv/bin/python -m scripts.titan007_data collect --max-requests 8 -- league --league-id 36 --season 2026-2027

# 按缓存已有比赛补统计/阵容，限制采集对象。
.venv/bin/python -m scripts.titan007_data collect --max-requests 6 -- details --date 2026-10-28 --only-missing --limit 3

# 一次获取当天赔率快照，避免逐场逐公司全部抓取。
.venv/bin/python -m scripts.titan007_data collect --max-requests 1 -- odds --feed

# 查看原采集器全部命令；-- 后的参数由采集器解析。
.venv/bin/python -m scripts.titan007_data collect -- --help
```

不通过 `live --loop` 或无限 `watch` 建第二套常驻调度。若要观察一次赔率异动，使用 `watch --once`。来源仍在冷却时由回执说明原因；不能靠重复重启脚本绕开限流。将来配置自动采集时应挂到既有 Scheduler/Worker，复用来源治理与运行记录，并控制每天的总请求和磁盘留存。届时确认 FQP 为唯一发送者，避免旧采集器的定时任务与 FQP 重复轮询。

## 方法保留在哪里

采集链是“请求公开页面/JS/XML → 按来源格式解析 → 保存原始字段与来源 ID → 离线核对/派生 → 规范身份与事实导入 → FQP 共同读取”。JS 数组使用受限字面量解析，不执行网页 JavaScript。

| 数据 | 主要来源/方式 | 对应实现 |
| --- | --- | --- |
| 当天比分/增量 | `live.titan007.com/vbsxml/bfdata_ut.js`、`change2_ut.xml` | `parsers.py`、`cli.py` |
| 逐日历史赛果 | `bf.titan007.com/football/Over_YYYYMMDD.htm`，显式处理 GBK 和跨午夜日期 | `parsers.py` |
| 统计/事件/实际阵容 | `live.titan007.com/detail/{id}cn.htm`，部分指标为嵌入式 JS | `parsers.py`、`store.py` |
| 联赛/杯赛/积分榜/射手榜 | `zq.titan007.com/jsData/matchResult/…` 及相应资料页 | `leagues.py`、`cli.py` |
| 欧赔、亚盘、大小球与历史 | 当天聚合 feed 优先，单场/公司变化仅补重点 | `odds.py`、`monitor.py` |
| 球队/教练/转会 | `info.titan007.com/jsData/…` | `teams.py`、`roster.py` |
| 伤停、近期战绩与简报 | 比赛分析页；原始报告与推断分开使用 | `analysis.py`、`derive.py` |
| 图片 | 已知来源图片路径，按来源实体 ID 保存 | `assets.py` |

来源代码复制时的提交标记与逐文件摘要见 [复制来源记录](data-sources/titan007/ORIGIN.json)；摘要针对实际读到的文件，不将原 Git 提交标记当作完整工作树证明。

原方法与字段参考：[采集方法原文](data-sources/titan007/titan007_爬虫方法文档.md)、[字段原文](data-sources/titan007/titan007_数据字段清单.md)。原文中的安装方式、示例 ID、默认路径、频率及覆盖陈述可能与当前 FQP 不同，以本页、实际代码和真实数据盘点为准。

## 英超共享数据接入

本轮复用 `competitions`、`seasons`、`competition_seasons`、`teams` 和已核实的来源别名。在同一个 PostgreSQL 中增加四张来源参考表：

现行 P104 观测流的 `match_id` 外键绑定官方比赛，不能容纳没有竞彩身份的全联赛赛程。因此本次在同库保存来源参考批次，沿用共享实体，不为接入观测流伪造官方比赛 ID。

| 表 | 用途 |
| --- | --- |
| `football_team_source_links` | 来源 + 联赛球队 ID 体系 + 外部 ID 到规范球队的明确链接与核实依据 |
| `league_reference_batches` | 不可变赛季修订，保存来源声称的更新时间、独立采集时间（旧副本未知）、实际导入时间、内容摘要、质量报告和原始字段 |
| `league_reference_fixtures` | 同批次赛程/赛果，外部比赛使用独立命名空间，关联共享球队 |
| `league_reference_standings` | 同批次总/主/客全场榜单；半场表不作为全场表 |

导入只读取所选赛季的赛程与榜单来确定参赛队；不会把整个联赛历年球队目录当当季阵容。仅复用明确来源链接、人工配置或已核实的来源别名；已有同名但未核实的球队隔离，不模糊合并、不重复新建。多个赛事/赛季规范候选要求先消除配置歧义。确实没有已有候选时，在共享球队表创建带来源代码的实体；该身份不等同官方竞彩匹配已核实。

每次导入在同一个事务中发布。相同来源内容和身份映射重跑返回 `unchanged`，更正建立新批次，旧批次保持可读；并发导入串行领取同一来源事务锁。失败和映射演练回滚本次全部新增行。独立采到时间不改变内容键：来源事实相同时保留原批次，后续采到时间留在新运行回执，不改写旧批次。已发布批次和子记录由数据库禁止修改、删除和追加；归档清理由后续留存策略处理，不能直接覆盖历史。

参考比赛不写入官方比赛、官方赛果、停售或票单表，也不写旧模型正在消费的积分榜投影。三个共享 GET 为 `/api/league-data/catalog`、`/api/league-data/seasons/{id}`、`/api/league-data/seasons/{id}/fixtures`，沿用会话鉴权、同源客户端、请求去重与超时。浏览页面只读 PostgreSQL，不访问 SQLite 或触发抓取。赛程分页携带赛季读取时的 `batch_id`，导入期间也不会混批次。

总/主/客榜各自校验队数、排名及基本统计一致性；积分采用来源值，保留零分、负积分与未知。新批次某范围不完整时，取同赛季、相同规范球队集合的上一份完整榜，注明其独立时间和批次；从未完整的范围显示缺口，不发布部分排名。旧来源更新时间不会盖过较新版本。近况仅取同赛季、同范围、同一榜单批次内已完场且开球时间已知的比赛，最多五场。

离线缓存没有可靠的逐赛季采集时刻，`source_acquired_at` 保持 `null`；`source_as_of` 只表示原资料的 `last_update`，不是采集或入库时间。缺来源截止时间时仍可显示参考资料，同时标明未知/过期，不能据此作为严格历史时点的模型输入。赛程中同一主客组合出现冲突外部 ID 时，两条一起隔离，不任意合并或重复计入概览。

从现行 FQP 运行环境启用，数据库地址使用该环境已核实的 `DATABASE_URL`。先确认 `teams`、`competitions` 等现行基础结构存在；仅有同名 `fqp` 数据库不能证明目标正确。本次没有向检测到的旧本机库执行迁移。

```bash
# 默认只预览本地缓存，不连接业务库、不请求网站。
.venv/bin/python -m scripts.titan007_import

# 运行库具备现行基础结构后，由既有迁移账户执行增量结构。
psql "$DATABASE_URL" --single-transaction -v ON_ERROR_STOP=1 -f sql/118_league_reference_data.sql

# 使用应用账户预演映射和入库，然后回滚行变更；序列值可能前进。
.venv/bin/python -m scripts.titan007_import --check-mapping

# 查看报告中的未映射球队；必要时在运行配置中补充已核实的 team_links。
# 确认目标后，将当前缓存发布成一个参考批次。
.venv/bin/python -m scripts.titan007_import --apply

# 再次执行应返回 unchanged。用既有应用入口启动后查看：
# #/events?view=league
```

CLI 写入要求显式配置回环地址 `DATABASE_URL`，不会自行使用默认库或远程生产库。在服务器运行时也应使用服务器本机数据库连接。初次发布只新增少量实体和有界批次；迁移不改现有大表，设置两秒锁等待和三十秒语句上限。事务提交前失败可整体回滚。代码回退可以停用读取适配器并保留参考表，避免删除已留存的来源历史。服务器启用与发布仍需另外执行，本文命令不代表已发布。

## 本机 Docker Desktop 已启用（2026-10-29）

现有项目 `fqp-gh-main-202ac4` 已启用 main 未提交工作树的本地快照。API/Scheduler/Worker 为 `local-main-league-df543316916e`；后续队徽修正仅更新 Web 为 `local-main-crests-a2a7306fd7ed`。这是本机分层预览，不是 GitHub 或服务器已发布版本。继续使用原 PostgreSQL/Redis/runtime/appdata 卷，不创建第二个业务数据库。

- 页面：`http://127.0.0.1:18066/#/events?view=league`；API：`http://127.0.0.1:18080`。
- 已检查原 106 条迁移账本无摘要漂移；先在实际测试库副本恢复验证，再补齐 107–118。139 张原表的已有列与数据保持不变，索引有效。
- 初次导入批次 `2`、赛季引用 `2`：380 场、20 队、总/主/客榜各 20 行，70 场完场，截止 10 月 22 日。后续有界更新发布同赛季批次 `5`，80 场完场，截止 10 月 29 日 15:01:20；旧批次保留。映射演练回滚全部行；重复发布返回 `unchanged`。序列前进不表示存在重复批次。
- 初次启用真实登录、25 项 HTTP 检查及两主题/两尺寸四组浏览器检查通过。更新使用已冻结数据发布，只有三张参考表增加记录，其余表的已有数据摘要未变；运行镜像和容器未替换。入库和镜像更新时间不改变来源证据时间。
- 采集仍为手动有界命令，Scheduler 没有球探自动任务，模型输入未改变。API/依赖健康与完整业务健康分开：该空测试库的运维总健康仍可能因缺少备份/审计样本显示 degraded。

本机私密运行文件位于忽略的 `.runtime/desktop-test/`，权限仅限当前用户；不要提交或打印其内容。原生 `.env.local` 无需为这套 Docker 栈创建。管理时明确使用现有项目和私密配置，避免误启动另一套默认项目：

```bash
docker compose -p fqp-gh-main-202ac4 \
  --env-file .runtime/desktop-test/desktop.env \
  -f compose.desktop-test.yml \
  -f .runtime/desktop-test/compose.override.yml ps
```

继续导入原始缓存可使用项目已有 CLI，无需计划目录中的一次性验证脚本。以下容器共享本机 PostgreSQL 容器的网络命名空间，因此 `import.env` 使用 `127.0.0.1` 应用账户；原始缓存只读挂载，不复制进镜像、也不随页面访问采集：

```bash
FQP_LOCAL_IMAGE="$(docker inspect -f '{{.Config.Image}}' fqp-gh-main-202ac4-api-1)"
docker run --rm \
  --network container:fqp-gh-main-202ac4-postgres-1 \
  --env-file .runtime/desktop-test/import.env \
  --mount "type=bind,source=$PWD/data/sources/titan007,target=/source,readonly" \
  "$FQP_LOCAL_IMAGE" python -m scripts.titan007_import \
  --data-dir /source --check-mapping
```

核对后将末尾 `--check-mapping` 换为 `--apply` 发布；本轮已实际验证该 CLI 重跑返回 `unchanged`。本机当前账号沿用已有配置，未重置密码或关闭会话鉴权。临时验证数据库/容器已清理，原镜像与私密恢复材料保留在本机。

当前英超 20 队的旧队徽错图已修正；来源为本地缓存，没有新抓取网站或变更参考数据批次。其他联赛旧素材尚未逐图核查，不能把本批队徽通过等同所有视觉资产已核实。

## 有界更新与发布重试

更新入口固定使用已核实的英超 `36`、`2026-2027` 配置，不自动猜下一赛季。它按赛季取得完整赛程和总/主/客榜单，不逐场请求、不请求射手榜。发布的是完整参考修订；内容没变则不新增业务批次。

每次最多 8 次请求（包含重定向），间隔至少 3 秒，沿用 900 秒采集软时限、同缓存锁和访问拒绝冷却。两次新采集至少相隔 6 小时。完整性要求为配置中的队伍、主客双循环赛程及三类榜单；来源截止和真实采到时间均需已知，且不能过期或明显位于未来。校验失败时页面继续读取现行批次，不用半份资料替换。临时 SQLite 只是一次性解析适配器，随采集结束移除；原 6GB 历史副本不被改写。

```bash
# 真实采集并准备数据；不连接业务库。
.venv/bin/python -m scripts.titan007_refresh

# 用前一条命令返回的 run_id 核验已冻结数据；不再次请求网站。
.venv/bin/python -m scripts.titan007_refresh --resume '<run_id>'

# 已明确配置正确的本机 DATABASE_URL 后，发布同一份数据。
.venv/bin/python -m scripts.titan007_refresh --resume '<run_id>' --apply
```

回执位于 `runs/refresh-{run_id}.json`，完整冻结数据为相邻 `.payload.json`。回执记录源摘要、真实采到时间、HTTP 状态及预算、质量和发布批次；`requests` 是原采集次数，`requests_this_attempt` 是当前尝试的次数，resume 为 0。冻结文件和回执摘要或配置不匹配时拒绝发布。全量冻结数据总量接近 64MiB 时停止新采集，需核实并归档后再继续，不自动删除审计材料。失败不绕过间隔或冷却，发布失败重试也不重新下载。当前工作树尚未发布到运行镜像，CLI 应从这份代码运行；不要在旧 API 容器里直接执行尚不存在的新模块。

现有本机 Docker 参考库可以用一次性容器发布：复用同一数据库网络和已核实私密配置，只读挂载当前代码，缓存父目录可写以容纳同一个锁文件。没有重建服务或迁移数据库。

```bash
FQP_LOCAL_IMAGE="$(docker inspect -f '{{.Config.Image}}' fqp-gh-main-202ac4-api-1)"
FQP_REFRESH_RUN_ID='<run_id>'
docker run --rm --read-only --tmpfs /tmp:rw,size=64m \
  --network container:fqp-gh-main-202ac4-postgres-1 \
  --env-file .runtime/desktop-test/import.env \
  --mount "type=bind,source=$PWD/scripts,target=/app/scripts,readonly" \
  --mount "type=bind,source=$PWD/configs,target=/app/configs,readonly" \
  --mount "type=bind,source=$PWD/data/sources,target=/source" \
  "$FQP_LOCAL_IMAGE" python -m scripts.titan007_refresh \
  --data-dir /source/titan007 --resume "$FQP_REFRESH_RUN_ID" --apply
```

本次真实运行 `98a1cb35693541ed948a18d23ee89359` 使用 3 次请求，冻结约 407KB。发布与重复发布均为零来源 HTTP 请求，返回批次 `5` 与 `unchanged`；只有三张参考表变化，旧批次及其余表的数据摘要保持不变。现在仍是手动更新；自动调度要在运行镜像整合、唯一发送者确认后挂到原 Scheduler，不另建常驻采集器。

## 离线队徽同步

旧脚本曾把体彩原始球队 ID 直接用于 500.com 图片地址。不同来源的数字 ID 不能互换；现在只接受该供应商目录中核实的名称映射，未映射项明确报告，不猜 ID。

`configs/titan007/team_crests.json` 保存当前英超 20 队经目视核对的来源 ID、别名、图片来源和 SHA256。只将约 224 KB 已核对原图复制为前端静态素材，原始缓存仍被 Git 忽略。共享注册表用于联赛、比赛及其他既有 `TeamLogo` 消费者，不限于某一页面。

```bash
# 完全离线，不连接 PostgreSQL，不下载图片，也不触发模型。
.venv/bin/python scripts/jobs/build_team_icon_library.py \
  --sync-cached-crests data/sources/titan007
```

命令先核验全部来源图摘要、格式签名、别名唯一归属和路径范围，再更新本地素材及生成注册表；重复执行不改变输出。未知图片或摘要不符会中止，不自动采用尚未核实的图。保留其他队伍现有条目；原有同图重复别名不会被误判为跨队归属冲突。完整在线生成命令同样保留已核验的球探队徽，不再采用其他来源的数值 ID。

本次 8 项脚本回归、30 项前端相关用例、目标 Ruff/mypy、前端类型和构建检查通过。本机只重建 Web：20 图 HTTP 响应与摘要一致，黑红/极地 × 桌面/手机四组浏览器复核正常。API、Scheduler、Worker、PostgreSQL、Redis 容器 ID 不变，没有数据库迁移、数据导入或服务器发布。后续原图变化需重新核对并更新清单，不能以本次核验代替其他球队的素材审查。

## 2026-10-29 只读盘点结论

本次数据库约 6.11 GB（十进制），48 张业务/辅助表。数据库文件不含两份旧备份和单独图片目录的体积。

| 原表 | 实测记录数 | 使用价值与限制 |
| --- | ---: | --- |
| `league_results` | 90,731 | 260 个赛事、17 种赛季标识；包含未来赛程。已完场且有比分 68,951 条，不能把全表当训练样本 |
| `matches` | 18,348 | 86 个赛事的详情入口，比赛日期 2022-01-01 至 2027-03-07；18,326 条标记完场 |
| `lineups` | 725,194 | 覆盖 17,554 场；先核验实际/预计名单、来源球员 ID 和采到时间 |
| `match_stats` / `events` | 386,800 / 246,050 | 比赛内容与实际事件，适合赛后统计及赛前历史聚合 |
| `odds_history` | 6,671,800 | 赔率历史行，最需要有界增量与按范围读取 |
| `match_injuries` | 254,338 | 覆盖 16,866 场，但伤停发生日/预计回归字段均为空，不代表已知伤停全时间线 |
| `player_transfers` | 38,893 | 归属变化候选事实，需要球员身份和生效区间核对 |
| `player_appearances` | 725,147 | 现有脚本按首发/换人推算的分钟，不能作为官方出场分钟 |
| `player_stats` | 885 | 实际球员单场技术行明显少于推算出场表，不能混称完整球员技术库 |
| `league_standings` / `scorers` | 41,011 / 32,417 | 最新榜单/赛季资料；不是已经保存好的历史时点快照 |

`matches` 和 `league_results` 有 10,034 个来源比赛 ID 重叠，不能直接相加。队伍映射中有 180 条歧义、123 条未匹配，另外 122 条以模糊方法标记成功；即使写着 mapped，也不能直接升级为 FQP 已核实身份。详细比赛的 `source_published_at` 全为空；`first_fetched_at` 最早在 2026-10-24，不能证明这些事实在 2022 年赛前就被系统知道。原 `data_counts` 缓存有过期数字，盘点使用实际 SQL 计数。

球员资料和逐场阵容使用不同 ID 体系，目录还有 `50_000_000` 偏移生成的内部展示 ID。来源标准键至少包含“来源 + 实体类型 + ID 体系 + 外部 ID”；不能把数值相同或姓名相似视为同一人。球队所属也必须带日期与赛事范围。

## 后续消费方案与顺序

沿用既有足球数据改造计划 P109/P104/P107/P108/P106，按下列顺序落实，同一代码入口逐步演进，不另开重复平台。

| 顺序 | 交付 | 复用现有项目 | 完成标准 |
| --- | --- | --- | --- |
| 1 | 采集能力和原始数据迁入（本批） | 当前来源模块、现有依赖、项目 data 目录 | 可独立复制、读取与有限采集，原目录保留，错误回执可见 |
| 2 | 统一身份和 PostgreSQL 暂存/规范事实导入（本机 Docker 已启用） | 现行规范实体、明确来源链接和完整批次契约 | 英超 2026–2027 幂等批次、映射歧义隔离、重跑不重复、0/未知分开、完整事务可见；服务器发布待执行 |
| 3 | 接通赛事中心联赛资料（本机 Docker 已启用） | 既有 `LeagueDataSource.catalog/season/fixtures` 边界及后端鉴权/分页 | 页面默认读共享后端，真实赛程与完整榜单带独立来源/截止/批次；服务器发布待执行 |
| 4 | 逐域接通阵容、转会、伤停与赔率参考 | P108 球员事实、P104 来源观测和既有赔率/单场详情 | 实际首发与预计阵容分开；推算分钟/中立场标注；缺失可降级，官方销售/结算保持来源边界 |
| 5 | 增量调度和数据缺口补取（手动有界更新/回执发布已完成，自动调度未启用） | 现有 Scheduler/Worker、P103 来源治理 | 当前同缓存每日上限与失败冷却；后续唯一发送者、定时更新与临赛补取，不把每次浏览变成采集 |
| 6 | 模型接入与效果验证 | P106 样本 manifest、模型工件/run、时间切分评价，P111/P114 | 扩展带来源的样本契约；赛季/转会/升降级与近期变化单独建模；先影子比较，再决定启用 |

增量结构、隔离验证和本机 Docker 实际迁移/首次导入均已完成；服务器启用仍需单独发布。第三方参考数据作为独立数据产品登记，当前仅供研究、显示和运维，不自动获得预测或结算用途。

训练时必须按预测时点筛选当时可用的历史事实。杯赛还需明确常规时间、加时和点球比分的含义，不能只按“完场+非空比分”就形成标签。今天回填的旧赛果可用于现在的训练；如不能重建旧时点的可用性，只能作为明确标注的历史研究材料，不能冒充严格前瞻回测。赛后技术统计不能进入同场赛前特征；最新积分榜/现阵容不能回写旧赛季。缺伤停、估值、天气等可选信息时记录未知并使用已有基础输入，不用 0、虚构首发或不可靠比赛匹配填满字段。

## 本次实际联网验证

2026-10-29 在项目内的独立忽略缓存进行了少量公开接口检查：一次比分请求返回 296 场比赛、118 条来源联赛记录，目录实际落库 117 行；英超 2026-2027 资料使用 6 次请求（包含 2 次同域跳转），写入 380 条赛程、120 行积分榜、428 条射手榜记录。两批均成功，没有使用付费 API。已修复移植时重复 Referer 导致的 HTTP 400，并为请求头与受控跳转添加回归。其他采集命令已移入并按现有固定样本验证，不代表所有实时接口和所有赛事都已经实测覆盖。

## 验证与回退

针对快照/WAL、原目录保护、失败清理、只读入口、请求限额、冷却、重定向、数据目录、老库兼容及原解析/派生固定样本进行本地回归。公共来源的少量实际请求另存运行回执，不把离线通过当作长期接口可用证明。

```bash
.venv/bin/python -m pytest tests/test_data_sources/titan007 tests/test_scripts/test_data_catalog.py
.venv/bin/python -m pytest tests/test_api/test_league_data.py
# 真实 PostgreSQL 测试要求显式隔离库与数据库标记，未配置时跳过：
# tests/test_computation/test_league_reference_postgres.py
.venv/bin/python -m ruff check scripts/sources scripts/titan007_data.py tests/test_data_sources/titan007 tests/test_scripts/test_data_catalog.py
```

本批源码可以独立回退；原目录一直保留，来源缓存也可保留研究和重新导入。不要通过删除已有票据、官方数据或生产数据来回退采集器。
