# P132 设计

## 证据边界
2026-11-03 只读生产核验发现 967 组一对一传统 fixture 与官方 canonical fixture，共享同一个体彩 MatchId。839 组队名及日期完全相同；另 128 组只有“狼队/伍尔弗汉普顿”名称别名，直接 MatchId 和对手/方向/日期一致。传统侧只有传统期次 MatchOrder 来源链接且无赛季成员；规范侧已有 `sporttery/jc.matchId` 和赛季归属。此数量仅作为设计输入，写入前必须重新只读核验。

## 存储与读取
新增 `football_fixture_identity_aliases(alias_fixture_id, canonical_fixture_id, source_name, id_system, source_match_id, evidence, created_at)`。两个 fixture 外键、对官方 MatchId 的复合外键及插入触发器共同证明证据直接指向规范 fixture。别名关系限一层、不可修改/删除/截断。别名侧只允许既有传统 MatchOrder 来源且不得有赛季成员。

目录视图经左连接别名表，将传统成员的逻辑 `fixture_id` 投影为规范 ID，并按规范侧 `sporttery/jc.matchId` 读取 official match id。保留已有 view 列列表和 join 基数，确保未建立映射的行完全兼容。

身份链接器对任何已有来源链接执行单层规范化后再比较。别名源链接原样保留，不复制到规范侧；新的来源链接仍写入规范 fixture。

## 发布拆分
本任务迁移部署时别名表保持空；同批服务兼容旧行。发布后创建独立 P133 数据操作：重新导出候选、断言双方唯一、逐项验证 MatchId 和来源事实、排除赛季/其他来源冲突，再单事务写入别名行，执行完整回滚预演与只读读回。按用户要求不创建数据库备份，但必须执行隔离 PostgreSQL 演练及事务回滚证明。
