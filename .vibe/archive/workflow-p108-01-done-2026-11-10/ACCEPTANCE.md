# P108-01 验收

- `(source_name, external_player_id)` 唯一，canonical 外键有效，状态和置信区间受数据库约束。
- 身份状态每次实质变更增加单调修订和 append-only 审计事件；同一输入重复提交无新事件。
- `verified` 要求目标、证据、方法、置信、审查人和时间齐全；其他状态不进入解析结果。
- 已登记的非 verified 来源 ID fail closed；禁止 verified 直接指向另一 canonical player。
- API-Football 精确 `player_code` 兼容，不以姓名/birth/team 自动匹配。
- 候选 CSV 报告稳定、只读、可复现，候选状态从不等同 verified。
- 隔离 PostgreSQL 16 验证应用角色仅读、up/down/up、回滚保留规则及现有测试夹具不受影响。
- GitHub CI 的 required-module 校验确认该 PostgreSQL 测试模块实际运行且无跳过。
- P108-01 不导入生产数据、不接入模型、不宣称球员归属/资格/出场分钟已完整。
