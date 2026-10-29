> 来源参考文档，复制于 2026-10-29。这里的命令、依赖、ID 示例和覆盖说明描述原采集器，不是 FQP 已启用状态。FQP 入口、请求限制、数据目录和时间边界以 [当前接入说明](../../titan007-data-source.md) 为准。

# titan007 足球数据爬虫方法文档

> 项目目录：`/Volumes/Nas/足球数据`
> 适用代码版本：0.2.0
> 数据字段参考：`titan007_数据字段清单.md`
> 使用说明：`README.md`

---

## 1. 总体架构

```
                 ┌──────────────────────────────┐
                 │            scrape.py          │
                 │        argparse 子命令        │
                 └──────────────┬───────────────┘
                                │
                 ┌──────────────▼───────────────┐
                 │        titan007/cli.py        │
                 │  调度、参数、进度、错误处理    │
                 └──────┬──────────┬────────────┘
                        │          │
          ┌─────────────▼──┐   ┌───▼─────────────────┐
          │ client.py      │   │ parsers/odds/...    │
          │ 请求/限速/重试  │   │ 解析 HTML / JS / XML │
          │ TLS 指纹伪装    │   └───┬─────────────────┘
          └──────┬─────────┘       │
                 │                 │ dict / list
                 └────────┬────────┘
                          ▼
                 ┌──────────────────┐
                 │    store.py      │
                 │ SQLite + upsert  │
                 └────────┬─────────┘
                          ▼
                 data/titan007.db
                          │
                 ┌────────▼─────────┐
                 │ export / alerts   │
                 │ CSV / 终端输出     │
                 └──────────────────┘
```

模块职责：

| 文件 | 职责 |
|---|---|
| `scrape.py` | 入口，调用 `titan007.cli.main` |
| `titan007/cli.py` | 子命令、参数解析、任务编排、日志 |
| `titan007/client.py` | HTTP 请求、限速、重试、编码识别、`curl_cffi` 伪装 |
| `titan007/parsers.py` | 比分、增量、历史页、详情页解析 |
| `titan007/odds.py` | 赔率快照、百家欧赔、变化表解析 |
| `titan007/analysis.py` | 赛前分析页解析 |
| `titan007/teams.py` | 球队 JS 数据包解析 |
| `titan007/leagues.py` | 联赛赛果、积分榜、射手榜解析 |
| `titan007/jsfmt.py` | JS 数组/对象字面量提取 |
| `titan007/monitor.py` | 赔率异动监控 |
| `titan007/store.py` | SQLite 表结构、写入、查询、导出 |

---

## 2. 运行环境与依赖

```bash
cd "/Volumes/Nas/足球数据"
python3 -m pip install -r requirements.txt
```

依赖：

| 包 | 用途 |
|---|---|
| `requests` | 普通 HTTP 请求 |
| `beautifulsoup4` + `lxml` | HTML 解析 |
| `curl_cffi` | 伪装 Chrome TLS 指纹，访问有风控的域名 |

`curl_cffi` 只在访问 `zq` / `vip` / `info` 时需要；`live` / `livestatic` / `bf` / `1x2d` / `m` 用普通 `requests` 即可。

---

## 3. 访问层：请求与反爬

### 3.1 域名分级

| 域名 | 典型用途 | 访问方式 |
|---|---|---|
| `live.titan007.com` | 实时比分、详情页、球员统计、文字直播 | 普通 |
| `livestatic.titan007.com` | 比分/赔率静态文件、单场数据包、flashdata | 普通 |
| `bf.titan007.com` | 按日期历史赛果、未来赛程 | 普通 |
| `1x2d.titan007.com` | 百家欧赔数据包 | 普通 |
| `m.titan007.com` | 手机版赛程/赔率 | 普通 |
| `zq.titan007.com` | 赛前分析、联赛资料库、积分榜、odds JSON | **伪装** |
| `vip.titan007.com` | 单公司赔率变化、全公司亚盘/大小球对比 | **伪装** |
| `info.titan007.com` | 球队/球员资料 | **伪装** |

### 3.2 请求头

统一使用：

```http
User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) ... Chrome/131.0.0.0 Safari/537.36
Referer: https://live.titan007.com/
Accept-Language: zh-CN,zh;q=0.9
```

不同任务会覆盖 `Referer`：

- 历史页 → `https://bf.titan007.com/`
- 1x2d → `https://1x2.titan007.com/oddslist/{id}.htm`
- vip → `https://vip.titan007.com/`
- zq → `https://zq.titan007.com/`
- info → `https://info.titan007.com/`

### 3.3 TLS 指纹与 `curl_cffi`

`zq` / `vip` / `info` 的 HTTPS 握手能成功，但请求发出后服务端直接空回复/RST。原因不是网络封锁，而是基于 TLS 指纹（JA3/JA4）的反爬。

`client.py` 的处理：

```python
PROTECTED_HOSTS = ("zq.titan007.com", "vip.titan007.com", "info.titan007.com")

if protected:
    resp = curl_cffi.requests.get(url, impersonate="chrome", headers=headers, timeout=...)
else:
    resp = requests.Session().get(url, headers=headers, timeout=...)
```

已验证：普通 curl/Node 访问失败，`curl_cffi(impersonate="chrome")` 和真实 Chrome 均返回 200。

### 3.4 WebSocket（未在爬虫中使用）

实时推送走：

```
GET https://live.titan007.com/commoninterface   → JWT token
wss://live.titan007.com/stream?channels=change_ut_xml&token=<token>
Header 必须带 Origin: https://live.titan007.com
```

消息为二进制帧，内容是 **zlib 压缩的 JSON**，解压后字段与 `change2_ut.xml` 一致。

当前实现选择轮询 `change2_ut.xml`（约 2 秒粒度），因为它更简单、无需处理 token/重连/解压。若要更低延迟，可以把 WebSocket 作为增量源接入 `monitor.py`。

### 3.5 编码识别

`client.decode_body` 的顺序：

1. 响应头 `charset`
2. `utf-8-sig`
3. `utf-8`
4. `gb18030`

原因：

- `live/livestatic/1x2d/zq` 是 UTF-8；
- `bf` 历史页、`vip` 变化页、`PlayerTech.aspx`、`textLive.aspx` 是 GB2312/GBK；
- GB18030 能兜底绝大多数中文页面。

### 3.6 限速、重试、超时

```python
TitanClient(delay=1.5, jitter=0.5, timeout=20)
```

- 每次请求前按 `delay + random(0, jitter)` 节流。
- `requests` 适配器对 429/500/502/503/504 做 3 次指数退避重试。
- 单请求超时 20 秒。

CLI 所有命令都支持 `--delay` / `--jitter`，测试时可调小，正式采集建议保持默认或更大。

### 3.7 合规与频率

站点 `robots.txt` 声明：

```
Disallow: /vbsxml/
Disallow: /*?*
```

本项目采集的几个主接口正好落在这些路径下。实际使用时：

- 控制频率（≥1.5 秒/请求）；
- 不要并发轰炸；
- 只抓需要的日期、比赛、联赛；
- 不要高频轮询 `vip` 变化页（每场每公司每类型一次请求）。

---

## 4. 数据源与抓取方法

### 4.1 实时比分

**入口**

```
GET https://live.titan007.com/vbsxml/bfdata_ut.js?r=007
GET https://live.titan007.com/vbsxml/change2_ut.xml?r=007
```

**方法**

1. `bfdata_ut.js` 是 JS 数组定义：
   ```js
   var A=Array(n+1);          // 比赛
   var B=Array(m+1);          // 联赛
   var matchcount=n;
   A[1]="比赛ID^颜色^联赛^...".split('^');
   ```
2. 用正则提取 `A[i]="..."`、`B[i]="..."`，按 `^` 拆分。
3. 每个比赛 69 个字段，映射见 `parsers.parse_bfdata` 和字段清单。
4. `change2_ut.xml` 是增量，`<h><![CDATA[...]]></h>`，26 字段，约 2 秒一版。

**解析函数**

```python
parsers.parse_bfdata(text)      -> {"matches": [...], "leagues": [...], "meta": {...}}
parsers.parse_change_xml(text)  -> [{match_id, status_code, home_score, ...}]
```

**写入**

- `live` 命令：`store.upsert_matches` + `store.upsert_leagues`
- `live --loop`：`store.update_from_change`，只更新已存在的比赛，避免产生缺少队名的“幽灵行”。

**日期**

比赛日期取自字段 43（年）+ 字段 36（MM-DD），得到实际开球日期。

### 4.2 历史赛果 / 未来赛程

**入口**

```
GET https://bf.titan007.com/football/Over_YYYYMMDD.htm
GET https://bf.titan007.com/football/Next_YYYYMMDD.htm
```

**方法**

1. 页面是 GBK，按 `gb18030` 解码。
2. 每场比赛是一个 `<tr id='tr1_N' sId='比赛ID' name='SclassID,SubSclassID' infoid='国家ID'>`。
3. 列：联赛、时间、状态、主队、比分、客队、半场、亚让、进球数、数据链接。
4. 队名单元格里可能带：
   - 排名 `<span name='order'>[14]</span>` → 提取后从队名中移除；
   - 黄牌/红牌图标 `yellow1.gif` / `redcard1.gif` → 图标数字即张数。
5. 时间有两种格式：
   - 历史页：`16日13:30`
   - 赛程页：`10-18 10:30`
   `parsers._parse_kickoff` 同时支持。

**解析函数**

```python
parsers.parse_history_page(html, page_date) -> [match_row, ...]
```

**日期语义**

`match_date` 使用**实际开球日期**。例如历史页 `Over_20261016.htm` 里 `17日02:30` 的比赛，`match_date` 记为 `2026-10-17`。这样所有数据源按日期查询时口径一致。

### 4.3 比赛详情（技术统计/事件/阵容）

**入口**

```
GET https://live.titan007.com/detail/{matchId}cn.htm
```

备用：

```
GET https://bf.titan007.com/detail/{matchId}.htm
```

**方法**

1. 页面头部有 JS 变量：
   ```js
   var scheduleID = 3087095;
   var state = -1;
   var strTime = '2026-10-17 18:15';
   var homeTeamName = '...';
   var guestTeamName = '...';
   ```
2. 技术统计在 `ul#teamTechDiv li.lists div.data`，每个 `div` 三个 `span`：
   ```html
   <div class='data'><span class='red'>8</span><span>角球</span><span>2</span></div>
   ```
3. 重要事件在 `ul#teamEventDiv li.lists div.data`：
   - 左侧 `span` 有图标 → 主队事件；右侧 → 客队事件；
   - 事件类型取图标 `title`，进球也可能用 `<i class="goalicon">`；
   - 球员名取 `a` 标签的 `title` 或文本；
   - 换人事件的第一个球员是换入、第二个是换出；进球事件的第二个是助攻。
4. 阵容在 `#matchBox2`：
   - `div.plays div.home/guest` → 首发；
   - `div.backupPlay2 div.home/guest` → 替补；
   - 每个 `div.play` 含号码、球员链接、姓名、生日、身高、身价、国籍。
5. 小联赛或未临近开赛时，阵容/事件可能为空，属于正常情况。

**解析函数**

```python
parsers.parse_detail_page(html, match_id) -> {header, stats, events, lineups, ...}
```

**进球球员补充**

`detail_ut.js` 是当日全部进球事件：

```
比赛ID^主客^事件类型^分钟^球员(繁)^球员ID^球员(简)^事件ID^^球员(英)^0
```

`parsers.parse_detail_ut` 解析成 `{(match_id, minute): [事件]}`，再用 `merge_scorers` 补进详情页事件里（只补空值）。

**场地/天气/温度**

`livestatic.titan007.com/phone/txt/analysisheader/cn/3/00/{id}.txt`

`^` 分隔，`parsers.parse_analysis_header` 映射：

| 下标 | 字段 |
|---:|---|
| 0/1 | 主/客队名(简) |
| 2/3 | 主/客队名(繁) |
| 4 | 状态 |
| 5 | 开球时间 YYYYMMDDHHMMSS |
| 6/7 | 主/客队排名 |
| 8/9 | 队徽 |
| 13 | 联赛ID |
| 15 | 联赛名 |
| 17/18 | 主/客队ID |
| 19 | 温度 |
| 20 | 天气 |
| 31 | 球场 |
| 39 | 轮次 |

### 4.4 赔率

#### 4.4.1 统一赔率快照（最便宜）

```
GET https://live.titan007.com/vbsxml/ch_goalbf3.xml?r=007
```

`<m>` 内逗号分隔，覆盖当日全部比赛，默认公司为皇冠（Crow，ID=3）：

| 下标 | 字段 |
|---:|---|
| 0 | 比赛ID |
| 2/3/4 | 亚让盘口、主水、客水 |
| 6/7/8 | 欧赔主胜、平、客胜 |
| 10/11/12 | 大小球盘口、大球、小球 |
| 13 | 走地状态 |
| 末尾2字段 | 推测为半场亚让、半场大小（值为数值时使用） |

`odds.parse_goal_feed` 输出 `[match_id, company_id, odds_type, ...]`。

#### 4.4.2 百家欧赔 + 完整变化史

```
GET https://1x2d.titan007.com/{matchId}.js
```

普通请求即可。文件里有：

```js
var game=Array(
  "公司ID|赔率ID|英文名|初盘主|初盘平|初盘客|初盘概率3项|初盘返还率|即时主|即时平|即时客|即时概率3项|即时返还率|即时凯利3项|变化时间|中文名|...",
  ...
);
var gameDetail=Array(
  "赔率ID^胜|平|负|时间|凯利胜|凯利平|凯利负|年;胜|平|负|...",
  ...
);
```

`odds.parse_1x2d` 输出：

```python
{
  "meta": {...},          # 多语言队名、联赛、天气、排名、season 等
  "companies": [...],     # 每家公司的初盘/即时/返还率/凯利
  "history": [...],       # 每家公司完整变化历史
}
```

这是单场赔率数据里性价比最高的接口：1 次请求 = 通常 200–350+ 家公司 + 数千条历史。

#### 4.4.3 单公司赔率变化历史

```
GET https://vip.titan007.com/changeDetail/1x2.aspx?id={id}&companyid={cid}&l=0
GET https://vip.titan007.com/changeDetail/handicap.aspx?id={id}&companyid={cid}&l=0
GET https://vip.titan007.com/changeDetail/overunder.aspx?id={id}&companyid={cid}&l=0
GET https://vip.titan007.com/changeDetail/1x2Half.aspx?id={id}&companyid={cid}&l=0
GET https://vip.titan007.com/changeDetail/handicapHalf.aspx?id={id}&companyid={cid}&l=0
GET https://vip.titan007.com/changeDetail/overunderHalf.aspx?id={id}&companyid={cid}&l=0
```

表格每行 5 或 7 个 `td`：

- 7 个：`分钟 | 比分 | 主 | 盘/平 | 客 | 变化时间 | 状态`
- 5 个：`分钟 | 比分 | 封 | 变化时间 | 状态`

`odds.parse_vip_change` 统一成：

```python
{"seq": 1, "minute": "92", "score": "1-3", "home": 7.14,
 "line": "平手/半球", "away": 0.02,
 "change_time": "10-17 20:00", "status": "滚"}
```

注意：

- `companyid=0` 只返回 1.2 KB 空壳；
- 第一行往往是“封”（home/line/away 全空），对比时应跳过；
- 需 `curl_cffi`。

#### 4.4.4 联赛整轮赔率

```
GET https://zq.titan007.com/League/LeagueOddsAjax
    ?sclassId=25&subSclassId=943&matchSeason=2026-2027&round=10
```

返回：

```js
oddsData["O_{matchId}"] = [[companyId, 主胜, 平, 客胜], ...];
oddsData["L_{matchId}"] = [[companyId, 主水, 盘口, 客水], ...];
oddsData["T_{matchId}"] = [[companyId, 大球, 盘口, 小球], ...];
```

`odds.parse_league_odds_ajax` 解析，适合一次性补某轮所有公司赔率。

### 4.5 赛前分析

```
GET https://zq.titan007.com/analysis/{matchId}cn.htm
```

页面同时包含三类数据：

1. **内嵌 JS 数组**（无需额外请求）
   - `v_data`：对赛往绩
   - `h_data` / `a_data`：主/客近期战绩
   - `h2_data` / `a2_data`：主/客同主客战绩
   - `Vs_hOdds` / `Vs_eOdds`：亚盘/欧赔全公司对比
2. **HTML 表格**
   - 联赛/杯赛积分排名
   - 盘路走势、相同盘路、入球分布、半全场、进球时间等
   - 阵容情况（伤停）
   - 球员上一场评分
   - 未来五场
3. **文本**
   - 赛前简报
   - 赛季数据统计比较

`analysis.parse_zq_analysis` 输出：

```python
{
  "meta": {...},
  "h2h": [...],
  "form_home": [...], "form_away": [...],
  "form_home_same": [...], "form_away_same": [...],
  "standings": [...],          # 全场/半场 × 总/主/客/近6
  "injuries": [...],
  "ratings": [...],
  "next_matches": [...],
  "briefing": "...",
  "odds_compare_asian": [...],
  "odds_compare_europe": [...],
  "sections": {"联赛盘路走势": "...", ...}
}
```

写入 `analysis_sections` 时：

- 每个顶层 key 单独一行 JSON；
- `sections` 拆成 `text:<标题>`；
- `--with-json` 额外抓 `default/getAnalyData` 存为 `analy_data`。

#### 附：`getAnalyData` JSON

```
GET https://zq.titan007.com/default/getAnalyData?sid={id}&t=1
```

返回结构化赛前赔率：

- `sbOdds` / `sbOddsHalf`：亚盘、大小、欧赔初盘/即时
- `jcOdds`：竞彩胜平负、让球、总进球、半全场、比分
- `bet365Odds` / `vcbetOdds` / `sbobetOdds`
- `ouOddsCompare`、`probabilityDatas`
- 赛中的 `matchEvents` / `matchTechDetails` / `lineup` / `tvLive`

### 4.6 球队资料

```
GET https://info.titan007.com/jsData/teamInfo/teamDetail/tdl{teamId}.js
```

JS 变量：

| 变量 | 内容 |
|---|---|
| `teamDetail` | 球队资料：名称、城市、球场、容量、成立日期、官网、简介 |
| `goalkeeper/rearguard/midfielder/vanguard/coach` | 按位置分组的基础阵容 |
| `lineupDetail` | 球员详情：生日、身高、体重、位置、国籍、合同、出场、进球 |
| `leagueData` | 主/客/总 + 半场战绩 |
| `cupData` | 参赛杯赛 |
| `teamCount` | 逐场记录 |
| `teamHonor` | 荣誉 |
| `countSum` / `teamCharacter` | 统计汇总/球队特征 |

`teams.parse_team_js` 提取变量，`normalize_team` 统一成 profile / squad / league_stats / honors / cups / matches。

注意：基础阵容数组的球员 ID 与 `lineupDetail` 的 ID 不一致，因此按**球员姓名**匹配详情。

### 4.7 联赛数据

1. 找到子联赛 ID：
   ```
   GET https://zq.titan007.com/cn/subleague.aspx?sclassid={leagueId}
   → 正则 SubSclassID = (\d+)
   ```
2. 取最新赛季（可选）：
   ```
   GET https://zq.titan007.com/jsData/LeagueSeason/sea{leagueId}.js
   → var arrSeason = [...]
   ```
3. 整季文件：
   ```
   SubSclassID != 0:
     https://zq.titan007.com/jsData/matchResult/{season}/s{leagueId}_{subId}.js
   SubSclassID == 0:
     https://zq.titan007.com/jsData/matchResult/{season}/s{leagueId}.js
   ```
   例：J1 → `s25_943.js`；英超 → `s36.js`。

   文件包含：
   - `arrLeague`：联赛多语言名、颜色、赛制说明
   - `arrSubLeague`：子联赛
   - `arrTeam`：球队列表
   - `jh["R_{轮次}"]`：每轮比赛结果
   - `totalScore/homeScore/guestScore/halfScore/...`：积分榜
4. 射手榜：
   ```
   GET https://zq.titan007.com/cn/Archer/{season}/{leagueId}.html
   ```
   有两种数据源：
   - J1 等：页面内嵌 `arrTotalData` / `arrHomeData` / `arrGuestData`
   - 英超等：页面引用 `jsData/Count/{season}/playerTech_{leagueId}.js`
     → `techCout_Player["Total"]["value"]`，`Goals` 在索引 52

   `leagues.parse_scorers` 处理第一种，`parse_player_tech_scorers` 处理第二种；`cmd_league` 会自动回退。

### 4.8 赔率监控

`monitor.py` 的两种模式：

| 模式 | 入口 | 对比对象 | 频率建议 |
|---|---|---|---|
| `feed` | `ch_goalbf3.xml` | `odds` 表上一条 `source='feed'` | 30–120 秒 |
| `vip` | `vip/changeDetail/*` | `odds_history` 上一条 `source='vip'` | 30–60 秒/盘口 |

流程：

```
抓取 → 解析 → 读取旧值 → 逐字段比较 → 生成 alert → 写 odds/odds_history → 写 odds_alerts
```

比较规则：

- `line`（盘口/大小球线）变化：始终记录；
- `home/away`（水位/赔率）变化：绝对值 ≥ `--min-delta` 才记录；
- VIP 模式跳过“封”行，取最新有效行；
- `odds_alerts` 唯一索引去重。

---

## 5. 解析层方法

### 5.1 JS 字面量提取（`jsfmt.py`）

站点大量数据以 JS 变量形式内嵌：

```js
var v_data = [...];
var game = Array("...", "...");
var techCout_Player = {"Pid": {...}, "Total": {...}};
```

`jsfmt.extract_js_literal` 的步骤：

1. 定位 `var <name> = [` 或 `var <name> = (new )?Array(` 或 `var <name> = {`；
2. 从起始括号开始做**括号配对扫描**，正确处理字符串里的 `[` `]` `{` `}`；
3. 把 `new Array(...)` 转成 `[...]`；
4. 替换 JS 的 `true/false/null/undefined`；
5. 处理数组空位：`[a,,b]` → `[a,None,b]`；
6. `ast.literal_eval` 转成 Python 对象。

这比正则 `\[.*?\]` 可靠，能处理字符串里带括号、HTML 属性、嵌套数组等情况。

### 5.2 HTML 表格解析（BeautifulSoup + lxml）

适用：

- 历史赛果页
- 比赛详情页
- vip 赔率变化表
- zq 积分榜/伤停/评分/未来五场

常用技巧：

- 用 `tr.get('sid')` 读行主键（bs4 会把 `sId` 转成小写 `sid`）；
- `td.get_text(" ", strip=True)` 统一空白；
- 单元格里嵌套 `<span>`/`<a>`/`<font>` 时，先提取结构再用文本；
- 排名标记 `<span name='order'>` 先 `decompose()` 再取队名；
- 表格列数不一致时按列数分支（如 vip 的 5/7 列）；
- 注释掉的 HTML（`<!-- ... -->`）默认不解析。

### 5.3 正则与文本

用于：

- `bfdata` 的 `A[i]="..."` 提取；
- `change2_ut.xml` 的 CDATA；
- `ch_goalbf3.xml` 的 `<m>`；
- 历史页日期 `16日13:30` / `10-18 10:30`；
- 比分 `2-0`、盘口 `2/2.5`；
- 球员文本 `17 (后腰) 手塚康平`。

### 5.4 字段映射与容错

- 字段带 `None`/空值时，`_int` / `_float` 返回 `None`，不抛异常；
- 排行榜/积分榜列数不足时跳过该行；
- 阵容/统计为空时不覆盖已有数据；
- 增量更新只 `UPDATE` 已有比赛；
- 同一场比赛多次抓取按主键合并。

---

## 6. 存储层设计

### 6.1 核心表

| 表 | 主键 | 说明 |
|---|---|---|
| `matches` | `match_id` | 比赛主数据 |
| `match_stats` | `(match_id, stat_key)` | 技术统计 |
| `events` | `(match_id, seq)` | 事件 |
| `lineups` | `(match_id, side, player_name)` | 阵容 |
| `leagues` | `league_id` | 联赛目录 |
| `odds` | `(match_id, company_id, odds_type, source)` | 初盘/即时赔率 |
| `odds_history` | `(match_id, company_id, odds_type, source, seq)` | 赔率变化 |
| `odds_alerts` | 自增 id + 唯一索引 | 异动记录 |
| `analysis_sections` | `(match_id, section)` | 赛前分析 JSON |
| `team_profiles` | `team_id` | 球队资料 |
| `team_squad` | `(team_id, player_id)` | 阵容 |
| `league_results` | `match_id` | 联赛赛果 |
| `league_standings` | `(league_id, season, scope, team_id)` | 积分榜 |
| `scorers` | `(league_id, season, scope, player_id)` | 射手榜 |

### 6.2 幂等策略

- `matches` / `leagues` / `odds` / `team_profiles`：`INSERT ... ON CONFLICT DO UPDATE`；
- 可空字段用 `COALESCE(excluded.x, table.x)`，空值不覆盖已有值；
- `match_stats` / `lineups`：非空时先删后插；
- `events`：先删后插；
- `odds_history`：按 `(match, company, type, source)` 整体替换；
- `analysis_sections`：按 `(match, section)` 覆盖；
- `league_standings` / `scorers`：按联赛+赛季整体替换；
- `odds_alerts`：唯一索引去重，重复轮询不会重复入库。

### 6.3 日期口径

- `matches.match_date` = 实际开球日期（北京时间）；
- 历史页的“赛事日”只用于解析 `16日13:30`；
- 凌晨比赛会归到次日。

---

## 7. 调度与运行

### 7.1 一次性建库

```bash
python3 scrape.py init
python3 scrape.py live
python3 scrape.py history --start 2026-10-01 --end 2026-10-17
python3 scrape.py details --date 2026-10-17 --only-missing --with-scorers --with-header
python3 scrape.py odds --feed
python3 scrape.py analysis --date 2026-10-17 --limit 50
python3 scrape.py league --league-id 25
python3 scrape.py team --team-id 181 209
```

### 7.2 持续运行

```bash
# 每 5 秒抓增量，每 5 分钟刷新全量
python3 scrape.py live --loop --interval 5 --refresh-snapshot 300

# 每 30 秒监控皇冠盘口
python3 scrape.py watch --mode feed --interval 30
```

### 7.3 cron

```cron
*/2 * * * * cd "/Volumes/Nas/足球数据" && python3 scrape.py watch --mode feed --once --quiet
30 8 * * *  cd "/Volumes/Nas/足球数据" && python3 scrape.py history --start $(date -v-1d +\%Y-\%m-\%d) --end $(date +\%Y-\%m-\%d)
```

### 7.4 断点续抓

`details --only-missing` 会跳过已有 `match_stats` 的比赛；`history` / `odds` / `analysis` 重复运行会覆盖更新，不会产生重复行。

---

## 8. 典型故障与排查

| 现象 | 原因 | 处理 |
|---|---|---|
| `HTTP 000` / `Empty reply from server` | 访问了 `zq/vip/info`，未伪装 TLS | 安装 `curl_cffi`，确认 `client.py` 走了 protected 分支 |
| 中文乱码 | 页面是 GBK | `client.decode_body` 会自动处理；自定义脚本时用 `gb18030` |
| 历史页 0 场 | 日期是未来/当天，`Over_` 尚未生成 | 用 `Next_`；`--include-next` |
| 联赛 0 场 | 子联赛 ID 处理错误 | 检查 `SubSclassID`；0 用 `s{id}.js`，非 0 用 `s{id}_{sub}.js` |
| 射手榜 0 人 | 页面使用外部 `playerTech` 文件 | 已自动回退；检查 HTML 里的 `jsData/Count/...` 路径 |
| 阵容为空 | 小联赛/未临近开赛 | 正常；稍后重试或忽略 |
| 文字直播为空 | 仅比赛中生成 | 赛后无法补 |
| vip 页面只有 1.2 KB | `companyid=0` | 传具体公司 ID，如 3/8/12 |
| 监控误报“封” | 第一行是封盘行 | 已跳过；自定义脚本时同样处理 |
| `429/5xx` | 频率过高 | 增大 `--delay`，减少并发 |

调试建议：

```python
from titan007.client import TitanClient
c = TitanClient(delay=0)
html = c.get("https://zq.titan007.com/analysis/3000486cn.htm")
open("/tmp/debug.html", "w").write(html)
```

然后用 `BeautifulSoup` 或正则检查结构。

---

## 9. 扩展方法

新增一个数据源的步骤：

1. **确认访问方式**：普通 requests 还是 curl_cffi；
2. **在 `cli.py` 顶部加 URL 常量**；
3. **在对应 parser 模块加解析函数**，返回 `dict` / `list`；
4. **在 `store.py` 加表结构和 `save_*` 函数**；
5. **在 `cli.py` 加子命令和参数**；
6. **在 `build_parser` 注册**；
7. **测试**：先用固定 URL 解析，再跑 CLI；
8. **更新 README 和本文档**。

示例：新增“文字直播”：

```python
# cli.py
TEXT_LIVE_URL = "https://live.titan007.com/textLive.aspx?id={match_id}&l=0"

# parsers.py
def parse_text_live(html):
    soup = BeautifulSoup(html, "lxml")
    return soup.get_text("\n", strip=True)

# store.py
# CREATE TABLE IF NOT EXISTS text_live (match_id INTEGER PRIMARY KEY, content TEXT);

# cli.py
def cmd_text_live(args):
    ...
```

---

## 10. 请求预算

| 命令 | 每场请求数 | 说明 |
|---|---:|---|
| `live` | 1 次/轮（全量） | 1 个文件 |
| `live --loop` | 1 次/轮 | 增量文件 |
| `history` | 1 次/天 | 每天 1 页 |
| `details` | 1，`--with-header` 2 | 详情 + 可选头部 |
| `odds --feed` | 1 次/轮（全量） | 1 个文件 |
| `odds --match-id` | 1 次/场 | 1x2d |
| `odds --vip` | 公司数 × 类型数/场 | 默认 3 次/场 |
| `analysis` | 1，`--with-json` 2 | |
| `team` | 1 次/队 | |
| `league` | 3–5 次/联赛 | 子联赛 + 赛季 + 数据 + 射手榜 |
| `watch --feed` | 1 次/轮 | 全量监控 |
| `watch --vip` | 公司数 × 类型数/场/轮 | 只建议重点比赛 |

---

## 11. 数据质量校验

```sql
-- 每日比赛数
SELECT match_date, COUNT(*) FROM matches GROUP BY match_date ORDER BY match_date DESC;

-- 比分缺失
SELECT match_date, COUNT(*) FROM matches
WHERE status_code = -1 AND (home_score IS NULL OR away_score IS NULL)
GROUP BY match_date;

-- 赔率覆盖
SELECT odds_type, source, COUNT(DISTINCT match_id) FROM odds GROUP BY odds_type, source;

-- 某场比赛的赔率变化条数
SELECT company_id, odds_type, COUNT(*) FROM odds_history
WHERE match_id = 3000486 GROUP BY company_id, odds_type ORDER BY 3 DESC;

-- 最近异动
SELECT detected_at, league_name, home_name, away_name, company_name,
       odds_type, field, old_value, new_value
FROM odds_alerts ORDER BY id DESC LIMIT 20;

-- 分析数据完整度
SELECT match_id, COUNT(*) AS sections FROM analysis_sections GROUP BY match_id ORDER BY 2 DESC;
```

导出：

```bash
python3 scrape.py export --table matches --out exports/matches.csv
python3 scrape.py export --table odds_alerts --out exports/odds_alerts.csv
```

---

## 12. 已知限制

- 高清视频流、会员专享 AI 预测/分析师内容需要登录或付费，未纳入采集。
- 文字直播仅比赛中生成，赛后为空。
- 部分小联赛没有技术统计、阵容或详情事件。
- `detail_ut.js` 只覆盖当日进球事件，历史比赛的事件球员需从详情页 HTML 或 `analysis` 页获取。
- 阵容详情在小联赛/未临近开赛时可能缺失。
- 未使用 WebSocket；增量粒度为约 2 秒。
- `odds --feed` 只覆盖皇冠一家公司；其他公司用 `--vip` 或 1x2d。

---

## 13. 合规提醒

- 站点 `robots.txt` 禁止 `/vbsxml/` 和带查询参数的路径；
- 控制请求频率，避免对站点造成压力；
- 数据仅供个人研究/分析使用，注意站点服务条款和版权；
- 不要将采集用于绕过付费墙、批量转售或任何违法用途。
