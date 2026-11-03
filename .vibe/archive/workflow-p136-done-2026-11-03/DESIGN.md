# P136 设计：共享比赛结果事实

## 边界

- `official_results` 继续代表官方竞彩比赛的官方结果；传统玩法的 `source_*` 继续代表体彩期次结果/结算语义。
- 新表记录第三方或补充来源对同一实际比赛的观察。每条必须关联已有 `football_fixture_source_links` 的同一来源 ID 和同一规范 fixture。
- 来源修订追加新观察；重复的同源同载荷回放返回原行，不修改旧事实。
- 赛果状态与比分依据分开：completed/shortened/abandoned/postponed/cancelled/awarded/unknown；on_field/awarded/unknown；regulation/extra_time/penalties/unknown。
- 仅 completed + on_field + regulation + 完整全场比分可以进入模型候选视图。历史源只写“完场”但未证明时间范围时必须标记 unknown，不可据此自动训练。
- 日期、开球时间精度和来源发布时间可空；缺失就保持空，不把采集时间或排期时间伪造成实际开球。

## 数据保护

SQL 130 只建表、索引、只读视图和约束/触发器；fqp 仅 SELECT/INSERT。表记录完整解析 payload 与证据 JSONB，并由数据库生成确定性 SHA-256。没有更新、删除或清空旧观察的路径。
