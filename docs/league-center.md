# 赛事中心：联赛资料

本模块按“先实现页面，数据以后接入”的要求建设。现有竞彩目录保留，联赛资料与其并列在赛事中心，不增加一级菜单或独立数据库。

## 当前交付

- `#/events`：默认仍为竞彩比赛，沿用官方编号、分页与单场详情。
- `#/events?view=league`：联赛资料入口，预留英超范围。**当前没有真实赛季、球队或榜单数据**，页面显示“数据待接入”，概览为 `—`，赛季选择不可用。
- 页面已实现赛季概览、总/主/客/近况积分榜、轮次和状态筛选、20 场分页、球队列表和本赛季球队子页。
- 来源、批次、数据截止（北京时间）、覆盖和过期分别展示。缺失值不当作 0；真实 0、扣分后的负积分保留。
- 主客/近况没有覆盖时不借用总榜。非完整榜单不发布为排名；后续适配器应提供上一完整批次，不能拼接逐队最新行。
- 同赛季手动刷新失败保留上次成功数据；切换赛季或筛选后清除旧结果，迟到响应不能覆盖新结果。目录、赛季、赛程各自显示读取失败并允许重试。
- 仅 `officialMatch.verification=verified` 且官方 ID 为正安全整数的参考赛程，才提供已有 `#/matches/:id` 入口。参考 ID 本身不用于单场分析。

球员榜、xG/xPts、赔率复制、模型接线和赛季情景模拟不在本批实现。页面浏览不会触发采集、外部网站请求、供应商调用、轮询、模型训练或业务写入。

## 实现与后续接数边界

代码入口：`apps/frontend/src/pages/EventsPage.tsx`；联赛功能位于 `apps/frontend/src/features/league-center/`。

- `types.ts` 定义 `LeagueDataSource` 的三个只读方法：`catalog()`、`season(competitionSeasonId)`、`fixtures(query)`。它们是 TypeScript 内部边界，**当前未新增后端 HTTP 接口**。
- `dataSource.ts` 的默认来源为 `disconnectedLeagueSource`，仅声明英超作为产品范围，返回空赛季目录。没有假赛季 ID、运行时示例球队、虚构榜单、演示开关，也不把现有竞彩子集冒充完整联赛。
- `LeagueCenter.tsx` 接受可替换的 `source`；后续接入时在同目录实现读取 FQP 共享接口的适配器并替换默认来源。不得直接从浏览器抓外站，或绕过共享事实和身份映射读取其他数据库。
- `state.ts` 负责校验/恢复 hash 参数；已配置的唯一当前赛季可以作为默认，不按浏览器年份猜赛季。显式指定但不存在的赛季/球队不静默替换。选择赛季、标签、范围、轮次、状态、页码和球队可刷新恢复，浏览器返回/前进会恢复同路由状态。

未来适配器必须先保证：

1. 赛事/赛季/球队 ID 使用 FQP 规范身份，跨年赛季、升降级与同名队显式区分。未核实的参考赛程保持独立命名空间，不能产生官方编号、停售或结算事实。
2. 每个积分榜范围来自完整同批次，注明来源、截止、阶段规则。扣分、判罚采用真实来源值；近况限定所选联赛和赛季，按由早到晚记录实际场数，最多 5 场，不填造缺场。
3. `overview` 由去重、状态和最终比分合格的比赛聚合。部分覆盖显示“样本统计”，覆盖分母未知时返回 `null`，不能仅凭批次完整声称赛季赛程全量。
4. `asOf`、`kickoff` 使用带时区时间。数据截止与浏览器读取时间分开；首次采到/可用时间、事实更正历史在共享后端保存，不由 UI 推断。
5. `fixtures(query)` 在共享后端按赛季、轮次、状态、可选球队筛选并稳定排序、分页，`total` 是精确筛选总数，不是当页行数。`upcoming` 只包含未开赛，延期独立分类；轮次 ID 使用 1–64 位字母/数字/下划线/连字符的稳定标识。
6. 后端继续使用现有鉴权、请求去重、来源预算和缓存。数据库扩展、真实导入、HTTP 契约与生产发布另按真实来源实施验证。本批没有数据库迁移、额外依赖或数据接入承诺。

示例链接（ID 仅解释格式，实际必须来自已接入目录）：

```text
#/events?view=league&competition_season_id=<canonical_id>&tab=fixtures&round=<round_id>&page=2
#/events?view=league&competition_season_id=<canonical_id>&tab=teams&team_id=<canonical_team_id>
```

## 本地验证

固定数据仅在 `LeagueCenter.test.tsx` 内用于组件验证，不进入运行目录或数据库。关联测试覆盖空态无网络、未知与0、扣分、缺失范围、批次不完整/过期、分页与筛选、未核实映射、错误与重试、错误赛季/球队、迟到响应、同路由恢复。

```bash
cd apps/frontend
npm test -- --run src/pages/EventsPage.test.tsx src/features/league-center/state.test.ts src/features/league-center/LeagueCenter.test.tsx
npm run typecheck
npm run build
```

这些验证说明页面和读取契约的本地行为，不代表真实来源覆盖、模型效果、数据库接通或生产部署完成。实际本轮结果记录在工作区 `plans/league-center-integration-20261027/IMPLEMENTATION.md`。
