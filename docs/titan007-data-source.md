# 足球补充数据：球探采集方法与 FQP 接入

本模块来自用户提供的本地采集项目 `/Volumes/Nas/足球数据`。采集、解析、原始缓存和固定样本已复制进 FQP；源目录继续保留。统一入口为 `python -m scripts.titan007_data`，采集实现位于 `scripts/sources/titan007/`。这份文档是 FQP 的现行操作入口，两份附带的原文仅作接口与字段参考。

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
