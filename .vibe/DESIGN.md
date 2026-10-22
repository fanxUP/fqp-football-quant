# 设计：竞彩比赛级销售状态优先于玩法池状态

## 证据

竞彩网官方赛程页 `https://www.sporttery.cn/jc/zqszsc/` 加载官方脚本 `https://static.sporttery.cn/res_1_0/jcw/default/jc/szsc/jc_szsc_gz.js`。脚本把 `sellStatus == "1"` 显示为“已开售”，把 `sellStatus == "2"` 显示为“暂停销售”，其他状态显示为“待开售”；在暂停和待开售分支，它清空这场比赛所有玩法的可选状态。

2026-10-23 03:50 对官方公开 match-list 作单次只读 GET：88 场记录中 25 场 `sellStatus=2`，另有 63 场未提供该值；原始对象和玩法池均没有逐场停售时间字段。03:50:45 的核对按 `matchDate+matchTime` 与北京时间比较，25 场 `sellStatus=2` 中 13 场尚未开赛，12 场已开赛或时点无法解析。该字段不能被解释为“在售”；比赛级状态必须优先于 `poolStatus`，而 `poolStatus` 仍是判断单一玩法的第二道条件。

## 处理规则

- 官方数字状态 1 映射为 `selling`；2 映射为 `paused`；已有其他数字映射保持原样，但任何非 `selling` 值都不得开放市场或生成开放赔率快照。
- 兼容字段同时存在时，优先使用官方页面实际读取的 `sellStatus`；只在官方字段缺失/空值时回退到历史 `saleStatus`。官方字段只接受整数或数字字符串，非数字值直接为 `unknown`，不得降级到别名覆盖。
- 历史别名 `saleStatus` 除整数/数字字符串外，只接受已知标准文本状态（如 `selling`），其他文本一律 `unknown`。
- 比赛级状态为 `selling` 后，每个玩法仍须有明确的 `poolStatus=selling` 才开放；仅有赔率、缺少玩法池或缺少/未知池状态均 fail closed。暂停、待开售、缺失或未知的比赛级状态也 fail closed。
- JSON 布尔值不能按 Python 整数子类映射为销售状态，官方 `sellStatus="selling"` 也不能作为有效状态码。
- 不把此状态信号写成绝对停售时间；`sale_stop_time` 继续留空，P121 现有硬门槛不变。
- `parse_matches_from_response` 与 `parse_odds_snapshots_from_match` 共用同一比赛级状态解释，避免赛程表与快照通路得出相反的可售结论。

## 风险和边界

该修正会让当前 `sellStatus=2` 的比赛退出 `sale_status='selling'` 查询，并关闭其玩法/赔率开放标志。已保存的旧行不会自动更正；发布后需由正常官方赛程刷新更新投影，再单独只读核对。历史原始响应保留，不能仅凭当前状态重写历史赔率时间线。
