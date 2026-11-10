# P108-04 技术设计

- 新解析器接收已确认绑定的官方比赛映射、API fixture 摘要、固定 `fixtures/players` 响应、verified identity resolver、获取时间和可选的来源换人事件。
- 解析器只读取 `statistics[].games.minutes`。整数 0 有“来源报告未出场”的含义；`null` 或缺失只计覆盖缺口，不生成分钟事实；布尔、字符串、负数和超过完赛时长的数值拒绝。
- fixture 必须匹配指定 API fixture ID、支持的完赛状态以及两队主客身份。球员只能由 source ID 查到唯一 verified canonical ID；名字字段不参与连接。
- 换人事件只作为矛盾检查，不推导出场分钟。直接分钟与明确换人时间不兼容时拒收该整场样本。
- 来源响应以规范 JSON 编码后做 SHA-256。每队一个 `appearance` stream，值保留源球员 ID、规范 ID、直接分钟、未解析数和缺失分钟数；证据标明 `source_reported=true`、`derivation=direct_source_field`、fixture/team IDs、摘要和获取时间。
- 主客队先全部校验，再在调用方同一事务中 append 两个队伍流；不设置历史短 TTL。没有 commit、自动请求或调度副作用。
- API 客户端只提供显式 `get_fixture_players(fixture_id)` 方法并校验响应形状；不增加任何调用点。
