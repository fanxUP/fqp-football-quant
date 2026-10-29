> 来源参考文档，复制于 2026-10-29。这里的命令、依赖、ID 示例和覆盖说明描述原采集器，不是 FQP 已启用状态。FQP 入口、请求限制、数据目录和时间边界以 [当前接入说明](../../titan007-data-source.md) 为准。

# 球探体育 titan007 可获取数据字段清单

> 验证时间：2026-10-17（北京时间当晚，赛事进行中）
> 验证方式：实际请求 + 页面渲染 + JS 源码字段对照
> 说明：`普通` = 普通 curl/requests 即可；`伪装` = 需 curl_cffi `impersonate="chrome"` 或 Playwright/真实浏览器（TLS 指纹风控）

---

## 0. 访问方式矩阵

| 域名 | 用途 | 访问方式 |
|---|---|---|
| live.titan007.com | 实时比分、详情页、球员统计、文字直播 | 普通 |
| livestatic.titan007.com | 比分/赔率静态文件、单场数据包 | 普通 |
| bf.titan007.com | 按日期历史赛果、未来赛程、小球详情 | 普通 |
| 1x2d.titan007.com | 百家欧赔数据包 | 普通 |
| m.titan007.com | 手机版赛程/赔率 | 普通 |
| zq.titan007.com | 赛前分析、联赛资料库、积分榜 | 伪装 |
| vip.titan007.com | 赔率变化历史、全公司亚盘/大小球对比 | 伪装 |
| info.titan007.com | 球队/球员资料 | 伪装 |
| 1x2.titan007.com | 百家欧指页面 | 伪装（数据包 1x2d 可普通访问） |

编码：`live/livestatic/1x2d/zq` 为 UTF-8；`bf` 历史页、`vip`、`PlayerTech.aspx`、`textLive.aspx` 为 GB2312/GBK。

robots.txt 声明 `Disallow: /vbsxml/`、`Disallow: /*?*`，采集时建议低频（≥2–5 秒/请求）并控制并发。

---

## 1. 实时比分与赛程

### 1.1 全量快照 `GET https://live.titan007.com/vbsxml/bfdata_ut.js?r=007`

文件结构：
```js
var A=Array(n+1);   // 比赛数组
var B=Array(m+1);   // 联赛数组
var C=Array(k+1);   // 国家/地区数组
var matchcount=n; var sclasscount=m;
var matchdate="10月17日"; var topLeagueIds="67,75";
```
每条 `A[i]` 用 `^` 分隔，共 **69 个字段（下标 0–68）**：

| 下标 | 字段 | 示例 | 说明 |
|---:|---|---|---|
| 0 | 比赛ID | 3087095 | 详情页/赔率页主键 |
| 1 | 联赛颜色 | #CA01CA | 前端配色 |
| 2 | 联赛名(简) | 荷青甲 | |
| 3 | 联赛名(繁) | 荷青甲 | |
| 4 | 预留 | 空 | |
| 5 | 主队名(简) | 费耶诺德U21 | |
| 6 | 主队名(繁) | 飛燕諾U21 | |
| 7 | 预留 | 空 | |
| 8 | 客队名(简) | 迪加史卓普青年队 | |
| 9 | 客队名(繁) | 迪加史卓普青年隊 | |
| 10 | 预留 | 空 | |
| 11 | 开赛时间 | 18:15 | HH:MM |
| 12 | 最后更新时间 | 2026,9,17,19,23,18 | 年,月(0基),日,时,分,秒 |
| 13 | 比赛状态码 | 3 | 见下方状态码表 |
| 14 | 主队全场比分 | 4 | |
| 15 | 客队全场比分 | 0 | |
| 16 | 主队半场比分 | 3 | |
| 17 | 客队半场比分 | 0 | |
| 18 | 主队红牌 | 0 | |
| 19 | 客队红牌 | 0 | |
| 20 | 主队黄牌 | 2 | |
| 21 | 客队黄牌 | 4 | |
| 22 | 主队联赛排名 | 1 | 页面显示为队名上标 |
| 23 | 客队联赛排名 | 3 | |
| 24 | 内部标志 | 0/1 | 未在 JS 中使用，含义未确认 |
| 25 | 赛事分级位掩码 | 0/2/3 | 1 与 2 的组合，供赛事级别过滤 |
| 26 | 高清直播频道 | 香港NOW639 | 空=无 |
| 27 | 阵容标志 | 1 | 未开赛时 1=已有阵容 |
| 28 | 走地盘标志 | True/False | 是否有走地赔率 |
| 29 | 亚让盘口 | 0.25 / -0.5 | 亚洲让球盘 |
| 30 | 比分/直播说明 | 小赛事只提供完场比分 | |
| 31 | 联赛页链接 | /cn/SubLeague.aspx?SclassID=604 | 相对路径 |
| 32–35 | 预留 | 空 | |
| 36 | 比赛日期 | 10-17 | MM-DD |
| 37 | 主队ID | 8628 | |
| 38 | 客队ID | 8629 | |
| 39 | 预留 | 空 | |
| 40 | 国家/地区ID | 8 | 对应 C 数组 |
| 41 | 固定值 | 0 | |
| 42 | 附加赛果说明(编码串) | `;|;|;|;1,3-2;;1` | 含加时/点球等信息 |
| 43 | 年份 | 2026 | |
| 44 | 内部标志 | 0/1 | 含义未确认 |
| 45 | 联赛ID (SclassID) | 604 | 与 31 对应 |
| 46 | 大小球盘口 | 2.25 / 3.5 | |
| 47 | 动画直播标志 | 0/1 | |
| 48 | 主队角球 | 8 | |
| 49 | 客队角球 | 2 | |
| 50 | 角球数据标志 | 0/1 | 1=有角球数据 |
| 51 | 内部标志 | 0/1 | 含义未确认 |
| 52 | 内部ID | 690 / 2187 | 疑似直播/动画相关，未确认 |
| 53 | 动画直播行标志 | 0 | |
| 54 | 附加说明(简) | 裁判回看VAR，进球可能被判无效 | |
| 55 | 附加说明(繁) | 同上 | |
| 56 | 补时分钟 | 3 | |
| 57 | 竞彩编号 | 周六007 | 竞足场次 |
| 58 | 足彩场次编号 | 8 | |
| 59 | 单场编号 | 90 | |
| 60 | 竞彩单关标志 | 0/1 | |
| 61 | 竞彩单关标志2 | 0/1 | |
| 62 | 热门赛程标志 | 0/1 | |
| 63 | 联赛有高清直播 | 0/1 | |
| 64 | 本场有高清直播 | 0/1 | |
| 65 | 加时/点球结果(简) | 点球[4-3],主胜 | |
| 66 | 加时/点球结果(繁) | | |
| 67 | 加时/点球结果(第三语言) | | |
| 68 | 附加说明所属球队ID | 0 / 65961 | 用于判断说明是主队还是客队 |

**状态码（字段13）**

| 码 | 含义 | 码 | 含义 |
|---:|---|---:|---|
| -14 | 推迟 | 0 | 未开赛 |
| -13 | 中断 | 1 | 上半场 |
| -12 | 腰斩 | 2 | 中场 |
| -11 | 待定 | 3 | 下半场 |
| -10 | 取消 | 4 | 加时 |
| -1 | 完场 | 5 | 点球 |

**联赛数组 B（14字段）**

| 下标 | 字段 |
|---:|---|
| 0 | 联赛名(简) |
| 1 | 联赛名(繁) |
| 2 | 预留 |
| 3 | 类型：1=联赛，2=杯赛 |
| 4 | SclassID |
| 5 | 固定值 |
| 6 | 当日总场次（运行时统计） |
| 7 | 显示场次（运行时统计） |
| 8 | 联赛资料相对URL `League.aspx?SclassID=` |
| 9 | 预留 |
| 10 | 筛选状态：1=全部，2=精简 |
| 11 | 热门场次计数（运行时） |
| 12 | 选择组合状态 |
| 13 | 联赛是否有高清直播 |

### 1.2 增量比分 `GET https://live.titan007.com/vbsxml/change2_ut.xml?r=007`

约每 2 秒更新，`<h><![CDATA[...]]></h>`，每条用 `^` 分隔，**26 字段**：

| 下标 | 字段 | 对应快照字段 |
|---:|---|---|
| 0 | 比赛ID | 0 |
| 1 | 状态码 | 13 |
| 2 | 主队全场比分 | 14 |
| 3 | 客队全场比分 | 15 |
| 4 | 主队半场比分 | 16 |
| 5 | 客队半场比分 | 17 |
| 6 | 主队红牌 | 18 |
| 7 | 客队红牌 | 19 |
| 8 | 开赛时间 | 11 |
| 9 | 更新时间 | 12 |
| 10 | 比分/直播说明 | 30 |
| 11 | 阵容标志 | 27 |
| 12 | 主队黄牌 | 20 |
| 13 | 客队黄牌 | 21 |
| 14 | 比赛日期 MM-DD | 36 |
| 15 | 附加赛果说明 | 42 |
| 16 | 主队角球 | 48 |
| 17 | 客队角球 | 49 |
| 18 | 角球数据标志 | 50 |
| 19 | 附加说明(简) | 54 |
| 20 | 附加说明(繁) | 55 |
| 21 | 补时分钟 | 56 |
| 22–24 | 预留 | |
| 25 | 附加说明所属球队ID | 68 |

### 1.3 WebSocket 实时推送

```
GET https://live.titan007.com/commoninterface          -> JWT token
wss://live.titan007.com/stream?channels=change_ut_xml&token=<token>
Header 必须带 Origin: https://live.titan007.com
```
消息为二进制帧，内容为 **zlib 压缩的 JSON**：
```json
{"change_ut_xml": "比赛ID^状态^主分^客分^主半^客半^..."}
```
字段与 1.2 的 26 字段一致。

### 1.4 手机版

| 入口 | 内容 |
|---|---|
| `https://m.titan007.com/txt/goal3.xml` | 实时赔率（与 ch_goalbf3 同格式），82 KB |
| `https://m.titan007.com/phone/Schedule_0_0.txt` | 联赛目录：联赛^ID^?...^国家^国家ID^颜色 |
| `https://m.titan007.com/txt/time.shtml` | 服务器时间戳 |
| `https://m.titan007.com/Common/CommonInterface.ashx?type=12/17` | 广告/配置 JSON |

---

## 2. 赔率数据

### 2.1 全场统一赔率 `ch_goalbf3.xml` / `goalBf3.xml`

- `https://live.titan007.com/vbsxml/ch_goalbf3.xml?r=007`
- `https://livestatic.titan007.com/vbsxml/goalBf3.xml?r=007`

`<m>` 内为逗号分隔，覆盖当日全部比赛，默认公司（Crow/皇冠）：

| 下标 | 字段 | 备注 |
|---:|---|---|
| 0 | 比赛ID | |
| 1 | 赔率记录ID | |
| 2 | 亚让盘口 | 0.75、-0.25 |
| 3 | 亚盘主队水位 | |
| 4 | 亚盘客队水位 | |
| 5 | 赔率记录ID/时间戳 | |
| 6 | 欧赔主胜 | |
| 7 | 欧赔平 | |
| 8 | 欧赔客胜 | |
| 9 | 大小球记录ID | |
| 10 | 大小球盘口 | |
| 11 | 大球水位 | |
| 12 | 小球水位 | |
| 13 | 走地状态 | 0=无 1=有 2=正在走地 |
| 14 | 亚盘开放标志 | 0=开 |
| 15 | 欧赔开放标志 | 0=开 |
| 16 | 大小球开放标志 | 0=开 |
| 17–18 | 固定 3,3 | |
| 末尾2字段 | 半场亚让、半场大小 | 如 `0.25,2` |

### 2.2 单场赔率时间线 `livestatic.titan007.com/jsData/{sclass%100}/{sclass/100}/{id}.js`

例如 `https://livestatic.titan007.com/jsData/30/00/3000486.js`

```js
var sOdds=[
 ['早餐',0,0, 0.74,0.25,1.16, 1.12,0.5,0.77, ...],
 ['未开场',0,0, ...],
 ['05',0,0, ...],
 ['21',0,1, ...]
];
```
每行 = `[时间标签, 主队比分, 客队比分, 13组×3个数值]`。
13 组分别为约 6 家亚盘（主水/盘口/客水）、2 家大小球（大/盘/小）、4 家欧赔（主/平/客）+ 1 组预留。数值随比赛进程刷新，是公开接口里最细的赔率时间线之一。

### 2.3 单场结构化赔率 JSON

`GET https://zq.titan007.com/default/getAnalyData?sid={matchId}&t=1`（伪装）

返回 JSON，字段：

| 顶层字段 | 内容 |
|---|---|
| `scheduleId` | 比赛ID |
| `sbOdds.sbOdds` | 亚盘/大小/欧赔三组：kind=ASIAN/OU/EURO，每项含公司ID、初盘、即时盘、时间 |
| `sbOddsHalf` | 半场同上 |
| `bet365Odds` / `vcbetOdds` / `sbobetOdds` | 指定公司的亚盘/大小/欧赔（含半场） |
| `ouOddsCompare` | 大小球初盘/即时对比 |
| `jcOdds.sfOdds` | 竞彩胜平负：初盘/即时 win/draw/lose |
| `jcOdds.wlOdds` | 胜负（让球）初盘/即时 |
| `jcOdds.goalOdds` | 总进球数赔率 g0–g7 |
| `jcOdds.hfOdds` | 半全场 9 种组合赔率 |
| `jcOdds.scoreOdds` | 比分赔率：score10…score52、胜/平/负汇总 |
| `probabilityDatas` | 各公司近10/20场胜平负概率（含 ALL/LEVEL1 分组） |
| `matchEvents` / `matchTechDetails` / `matchProcess` / `lineup` / `tvLive` | 赛中才填充，赛前为 null |
| `cornerRealOdds` / `letRealOdds` / `ouRealOdds` | 角球/让球/大小球实时赔率 |

### 2.4 百家欧赔 `https://1x2d.titan007.com/{matchId}.js`（普通）

大体积 JS（约 220 KB），包含：

| 变量 | 内容 |
|---|---|
| 多语言名称 | `matchname*`、`hometeam*`、`guestteam*`（中简/中繁/英/泰/越/韩/日/俄/西/印尼/葡） |
| 基本属性 | `MatchTime`、`ScheduleID`、球队ID、队徽、`hOrder/gOrder`（排名）、`neutrality`、`season`、`sclassId`、`sclassKind`、`ifShow`、`weatherIcon`、`temperature`、`venues_en` |
| `game` | 每家公司一条：公司ID｜赔率记录ID｜英文名｜初盘胜平负｜初盘概率3项｜初盘返还率｜即时胜平负｜即时概率3项｜即时返还率｜即时凯利3项｜变化时间｜中文名｜标志｜初盘凯利3项 |
| `gameDetail` | 每家公司完整变化历史：`胜|平|负|变化时间|凯利胜|凯利平|凯利负|年`，`;` 分隔 |
| `jcEuropeOddsData` | 竞彩欧赔初盘/即时 |
| `jcEuropeOddsDetail` | 竞彩欧赔完整变化历史 |

### 2.5 单公司赔率变化记录（伪装）

| 页面 | 参数 | 字段 |
|---|---|---|
| `vip.titan007.com/changeDetail/1x2.aspx` | id, companyid, l | 比赛分钟, 比分, 主胜, 平, 客胜, 变化时间, 状态(初/滚) |
| `.../handicap.aspx` | 同上 | 比赛分钟, 比分, 主水, 盘口, 客水, 变化时间, 状态 |
| `.../overunder.aspx` | 同上 | 比赛分钟, 比分, 大球, 进球数, 小球, 变化时间, 状态 |
| `.../1x2Half.aspx` | 同上 | 半场胜平负变化 |
| `.../handicapHalf.aspx` | 同上 | 半场亚让变化 |
| `.../overunderHalf.aspx` | 同上 | 半场大小变化 |

注意：`companyid=0` 只返回 1.2 KB 空壳；需 `companyid=3/8/12/35/42…` 才有数据。页面还提供“亚让/胜平负/进球数/三合一/半场让球/半场胜平负/半场进球数/角球指数”标签。

### 2.6 全公司盘口对比（伪装）

| 页面 | 字段 |
|---|---|
| `vip.titan007.com/AsianOdds_n.aspx?id=` | 公司, 多盘, 初盘(主队/盘口/客队), 终盘(主队/盘口/客队), 历史资料 |
| `vip.titan007.com/OverDown_n.aspx?id=` | 公司, 多盘, 初盘(大球/进球数/小球), 终盘(大球/进球数/小球), 历史资料 |
| `1x2.titan007.com/oddslist/{id}.htm` | 公司, 初始欧指, 即时欧指, 返还率, 即时凯利胜平负, 变化时间（数据来自 1x2d） |

两页均支持 `t=0` 全场 / `t=1` 半场。

### 2.7 联赛整轮赔率

`GET https://zq.titan007.com/League/LeagueOddsAjax?sclassId={leagueId}&subSclassId={subId}&matchSeason={season}&round={round}`（伪装）

返回 JS：
```js
oddsData["O_{matchId}"]=[[companyId, 主胜, 平, 客胜], ...];  // 欧赔
oddsData["L_{matchId}"]=[[companyId, 主水, 盘口, 客水], ...]; // 亚盘
oddsData["T_{matchId}"]=[[companyId, 大球, 盘口, 小球], ...]; // 大小球
```
一次拿到整轮所有公司赔率。

### 2.8 角球赔率

- `https://livestatic.titan007.com/jsData/corner/{sclass}/{id}.js` → `var cOdds=[...]; makecornertable();`
- `https://livestatic.titan007.com/xml/corner/{sclass}/{id}.xml`
- 详情页 `cornerOddsDiv` 区块
- `getAnalyData.cornerRealOdds`

---

## 3. 比赛详情 / 技术统计

入口：`https://live.titan007.com/detail/{matchId}cn.htm`（普通，UTF-8）
备用：`https://bf.titan007.com/detail/{matchId}.htm`

### 3.1 本场技术统计（主队 vs 客队）

角球、半场角球、黄牌、红牌、射门、射正、进攻、危险进攻、射门不中、射门被挡、任意球、控球率、半场控球率、越位、界外球、传球、传球成功率、犯规、头球、救球、铲球、换人数、过人、成功抢断。

### 3.2 重要事件 / 详细事件

- 分钟
- 事件类型：入球、点球、乌龙、助攻、黄牌、红牌、两黄变红、换人、换入、换出、射失点球、视频裁判(VAR)、扑出点球、射中门柱、最佳球员、犯规造成点球、失误导致失球、门线救险、最后防守球员、最后运球
- 球队、球员

另一个入口 `https://live.titan007.com/vbsxml/detail_ut.js`：
`比赛ID^主/客^事件类型^分钟^球员(繁)^球员ID^球员(简)^事件ID^^球员(英)^0`

### 3.3 阵容与伤停

- 预计阵容（首发 11 人 + 阵型）
- 替补
- 伤停：球员、位置、缺阵原因
- 上一场阵容（zq 分析页）

### 3.4 球队近期统计（详情页内嵌）

| 区块 | 字段 |
|---|---|
| 技统数据 | 进球、失球、被射门、角球、黄牌、犯规、控球率；口径：全部/同主客 × 近3场/近10场，主客队各一份 |
| 进失球概率 | 时间段 1–15、16–30、31–45、46–60、61–75、76–90、90+；主队进球/失球、客队进球/失球；近30/近50场 |
| 半场/全场胜负统计 | 胜胜、平胜、负胜、胜平、平平、负平、胜负、平负、负负（近两赛季，主/客场） |
| 数据统计 | 近20场入球分布（0/1/2/3+球）、平均黄牌、平均角球（主/客） |

### 3.5 球员统计 `https://live.titan007.com/PlayerTech.aspx?ID={matchId}&l=0`（普通，GBK）

每位球员字段：
号码、球员、位置、评分、关键事件、射门、射正、关键传球、带球过人、传球次数、传球成功、传球成功率、横传次数、精确横传、长传次数、精确长传、直塞次数、精确直塞、争顶成功、身体接触、抢断、拦截、解围次数、有效解围、封堵、造越位、犯规、被侵犯、被抢断、失误、越位。

### 3.6 直播类

| 类型 | 入口 | 说明 |
|---|---|---|
| 文字直播 | `https://live.titan007.com/textLive.aspx?id={matchId}&l=0` | 仅比赛中生成内容，赛后/未开赛显示“暂无直播内容” |
| 动画直播 | `/flashDetail/flash.html?id={matchId}...` + `livestatic.titan007.com/flashdata/get?id={matchId}` | flashdata 返回天气、球场、比分、技术统计、进失球概率等压缩串 |
| 高清视频 | `tvLive` / tcplayer HLS | 需登录/会员，非公开 |

---

## 4. 赛前分析页 `https://zq.titan007.com/analysis/{matchId}cn.htm`（伪装）

页面内嵌 `v_data / h_data / a_data / h2_data / a2_data / Vs_hOdds / Vs_eOdds` 等变量，无需额外请求即可解析。

| 区块 | 字段 |
|---|---|
| 头部 | 主队(排名)、客队、联赛+轮次、时间、场地、天气、温度 |
| 即时走势 | 让球、大小球、欧赔走势 |
| 联赛积分排名 | 全场/半场；总/主/客/近6：赛、胜、平、负、得、失、净、积分、排名、胜率 |
| 杯赛积分排名 | 同上 |
| 对赛往绩 `v_data` | 日期、联赛ID/名/颜色、主客队ID/名(含排名)、全场比分、半场比分、盘口、比赛ID、主客排名、联赛链接 |
| 近期战绩 `h_data/a_data` | 同上 + 让球结果、大小球结果等标记；分“竖版/横版”“同主/同客” |
| 数据对比 | 近N场双方数据对比 |
| 裁判统计 | 近N场裁判数据 |
| 联赛盘路走势 | 亚让：赛、赢盘、走水、输盘、赢盘率；进球数：大球、大球率、小球、小球率；总/主/客/近6；含半场 |
| 相同盘路 | 初盘、赢、走、输、赢盘率；总/主/客；近6场盘路走势 |
| 入球数/上下半场分布 | 0/1/2/3/4+ × 上半场/下半场 × 总/主/客 |
| 半全场 | 9 种组合 × 总/主/客 |
| 进球数/单双 | 大/小/走/单/双，场次与百分比 |
| 进球时间 | 1–10…81–90+ × 总/主/客 |
| 第一个进球时间 | 同上时间段 |
| 未来五场 | 时间、赛事、对阵、分析链接、直播、相隔天数 |
| 阵容情况 | 伤停（球员、位置、原因）、上一场阵容（首发/替补） |
| 球员评分 | 号码、球员、位置、首发、评分、平均评分、近10场平均评分 |
| 赛前简报 | AI 生成的中文分析文本 |
| 本赛季数据统计比较 | 主/客队战绩（胜平负%）、得失球（总/主/近6：进球总数、失球总数、平均进球、平均失球）、净胜球分布（净胜2+、净胜1、平、净输1、净输2+） |
| 盘口对比 `Vs_hOdds` | 公司ID、初盘主水/盘口/客水、即时主水/盘口/客水 |
| 欧赔对比 `Vs_eOdds` | 公司ID、初盘胜平负、即时胜平负、赔率记录ID |

另有 `https://zq.titan007.com/analysis/odds/{matchId}.htm`：全公司初盘/即时欧赔、亚盘、大小球、返还率、凯利指数。

---

## 5. 历史赛果

### 5.1 按日期 `https://bf.titan007.com/football/Over_YYYYMMDD.htm`（普通，GBK）

每天一页，约 500 行比赛，字段：

| 列 | 字段 | 备注 |
|---|---|---|
| 1 | 联赛 | 带背景色 |
| 2 | 赛事时间 | `16日13:30` |
| 3 | 状态 | 完/延/取等 |
| 4 | 主队 | 队名前可带黄/红牌图标 |
| 5 | 全场比分 | 字体红/蓝表示胜负 |
| 6 | 客队 | 可带黄/红牌图标 |
| 7 | 半场比分 | |
| 8 | 亚让 | `val` 数值 + 中文盘口 |
| 9 | 进球数 | 大小球盘口 |
| 10 | 数据链接 | 析/欧/亚/大 |

行属性：`sId`=比赛ID，`name`=`SclassID,SubSclassID`，`infoid`=国家/地区ID。

未来赛程：`https://bf.titan007.com/football/Next_YYYYMMDD.htm`，字段相同，时间为未来开赛时间。

### 5.2 联赛整季 `https://zq.titan007.com/jsData/matchResult/{season}/s{sclassId}_{subId}.js`（伪装）

变量 `jh["R_{轮次}"]` 为每轮比赛数组，每行字段：

| 下标 | 字段 |
|---:|---|
| 0 | 比赛ID |
| 1 | 联赛ID |
| 2 | 状态（-1 完场，0 未开赛） |
| 3 | 比赛时间 |
| 4 | 主队ID |
| 5 | 客队ID |
| 6 | 全场比分 |
| 7 | 半场比分 |
| 8 | 主队排名 |
| 9 | 客队排名 |
| 10 | 全场亚让盘口 |
| 11 | 半场亚让盘口 |
| 12 | 全场大小球盘口 |
| 13 | 半场大小球盘口 |
| 14–17 | 析/欧/亚/大 数据可用标志 |
| 18 | 主队红牌 |
| 19 | 客队红牌 |
| 20 | 进球时间/说明串 |
| 21–22 | 与 8/9 相同的排名冗余 |
| 23 | 预留 |

同文件还包含 `arrLeague`（联赛信息+赛制说明）、`arrSubLeague`、`arrTeam`、`totalScore`（总积分榜）、`homeScore`（主场榜）、`guestScore`（客场榜）、`halfScore`（半场榜）、`homeHalfScore`、`guestHalfScore`、`scoreColor`（升级/降级/亚冠颜色）、`lastUpdateTime`。

积分榜数组字段（`totalScore` 等）：
`[排名, 队伍ID, 赛, 胜, 平, 负, 得, 失, 净, 胜率, 平率, 负率, 场均进球, 场均失球, 积分, ...]`

### 5.3 联赛赛程/资料库页面

`https://zq.titan007.com/cn/SubLeague/{season}/{sclassId}.html`（伪装）
标签：赛程资料统计、射手榜、最佳阵容、球队资料、先入球/失球、没入球/失球、标准亚洲盘对照；统计标签：积分榜、亚让、大小球、常见赛果、单双数、入球数、半/全场、入球时间、波胆、净胜/负、入/失球。

---

## 6. 球队 / 球员 / 联赛资料

### 6.1 球队详情 `https://info.titan007.com/jsData/teamInfo/teamDetail/tdl{teamId}.js`（伪装）

| 变量 | 字段 |
|---|---|
| `teamDetail` | ID、中文名(简/繁)、英文名、队徽、城市(简/繁/英)、球场(简/繁/英)、容纳人数、成立日期、官网、简介 |
| `goalkeeper` / `rearguard` / `midfielder` / `vanguard` | 按位置分组的球员：球员ID、号码、名(简/繁/英)、标志 |
| `coach` | 教练 |
| `lineupDetail` | 球员详情：ID、号码、名(简/繁/英)、生日、身高、体重、位置、国籍(简/繁)、合同、出场/进球/助攻/黄牌等 |
| `leagueData` | 联赛主/客/总：赛、胜、平、负、得、失、净、胜率、平率、负率、场均进球、场均失球、积分 |
| `cupData` | 杯赛列表 |
| `countSum` | 球队统计汇总（射门、角球、黄牌、控球等） |
| `teamCount` | 逐场记录：比赛ID、联赛、时间、对手、比分、角球、射门、控球等 |
| `teamHonor` | 荣誉：赛事、年份、赛事ID |
| `teamCharacter` | 球队特征 |

### 6.2 联赛球队表 `https://info.titan007.com/jsData/teamInfo/team{leagueId}.js`（伪装）

`arrLeague`（联赛多语言名/颜色/赛季）、`arrTeam`（球队ID、名(简/繁/英)、队徽）。

### 6.3 联赛/国家目录 `https://zq.titan007.com/jsData/leftData/leftData.js`（伪装）

`arrArea`：国家/地区 → 联赛列表（ID、名(简/繁/英)、颜色、赛季类型）。

### 6.4 赛季列表 `https://zq.titan007.com/jsData/LeagueSeason/sea{sclassId}.js`（伪装）

`arrSeason`：该联赛可用赛季数组（2004–2026-2027）。

### 6.5 射手榜 `https://zq.titan007.com/cn/Archer/{season}/{leagueId}.html`（伪装）

内嵌 `arrTotalData` / `arrHomeData` / `arrGuestData`，字段：
`[排名, 球员ID, 名(简/繁), 英文名, 国籍(简/繁/英), 球队ID, 总进球, 主场进球, 客场进球, 点球数, ...]`

### 6.6 最佳阵容 `https://zq.titan007.com/cn/bestTeam/{season}/{leagueId}.html`（伪装）

`arrBestPlayers`。

### 6.7 球员页

`https://info.titan007.com/cn/team/player/{teamId}/{playerId}.html`（伪装）——球员资料、赛季数据、比赛记录。

---

## 7. 其他零散数据

| 数据 | 入口 | 字段 |
|---|---|---|
| 当日进球事件 | `live.titan007.com/vbsxml/detail_ut.js` | 比赛ID、主客、事件类型、分钟、球员(简/繁/英)、球员ID、事件ID |
| 交锋/盘路历史 | `live.titan007.com/vbsxml/panlu_ut.js` | 联赛、颜色、日期、主队ID、客队ID、比分、半场、盘口 |
| 多公司走地赔率 | `live.titan007.com/vbsxml/runOddsData_8.js`、`sbOddsData.js` | 每场6家公司 × 9个数值（亚盘/欧赔/大小球初/即时） |
| 比赛ID映射 | `live.titan007.com/vbsxml/soccer_scheduleid.js` | 当前页面比赛ID列表 |
| 分析页头部 | `livestatic.titan007.com/phone/txt/analysisheader/cn/3/00/{id}.txt` | 队名(简/繁)、队徽、排名、时间、天气、温度、球场、轮次、赛事ID等 |
| 动画数据 | `livestatic.titan007.com/flashdata/get?id={id}` | 天气、球场、比分、技术统计、进失球概率、阵型等压缩串 |
| 联赛筛选/国家 | `live.titan007.com/vbsxml/bfdata_ut.js` 的 `C` 数组 | 国家ID、名称 |

---

## 8. 明确拿不到 / 受限的数据

| 数据 | 原因 |
|---|---|
| 高清视频直播流 | 需登录/会员，`tvLive` 由用户态接口下发 |
| 文字直播（赛后） | 仅比赛中生成，赛后为空 |
| 部分会员专享：V计划、AI 预测、分析师推荐、赛前情报全文 | 需登录/付费 |
| 部分深度数据（如全场跑动、传球网络） | 页面未提供 |
| 实时赔率推送的低延迟版本 | 需走 WebSocket + token，普通轮询约 2 秒粒度 |

---

## 9. 建议的采集优先级

1. **比分/赛程**：`bfdata_ut.js` 全量 + `change2_ut.xml` 增量（普通请求，稳定）
2. **历史赛果**：`bf.titan007.com/football/Over_YYYYMMDD.htm`（按日批量）
3. **单场统计**：`live.titan007.com/detail/{id}cn.htm` + `PlayerTech.aspx`
4. **赔率**：`1x2d/{id}.js`（欧赔全历史）+ `vip/changeDetail/*`（单公司亚盘/大小球历史）+ `LeagueOddsAjax`（整轮）
5. **赛前分析**：`zq/analysis/{id}cn.htm`（内嵌 H2H、近期战绩、积分榜、伤停、简报）
6. **球队/球员/联赛资料**：`tdl{teamId}.js`、`Archer/*`、`sea*.js`、`leftData.js`

> 采集时统一加 `Referer: https://live.titan007.com/`，`zq/vip/info` 使用 `curl_cffi(impersonate="chrome")`，控制频率，避免对站点造成压力。
