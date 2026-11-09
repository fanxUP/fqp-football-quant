# P108-03 验收

- API-Football `Questionable` 映射为 `doubtful`；`Missing Fixture` 只表示缺席，不能据此认定受伤。缺席原因只有明确显示停赛或可识别伤情时才映射为 `suspended`/`injured`；其他原因保持 `unknown`。未知文本不得默认变成 injured。
- 只有完整且有效的 11 人首发进入 `confirmed` 阵容事实；预测阵容不得进入确认阵容投影，现有接口不能表示预测时须明确拒绝。
- 采集时刻保留为 observation acquisition/availability；每条球员记录的 `effective_at`、`published_at`、`expected_return_date` 仅从对应的明确来源字段读取。`updated_at`、比赛开球和采集时刻不得代填。缺失保持 null。
- 空伤停结果仍为 unknown；只有显式、可信且完整的覆盖证据可以确认 absence，不为任何未报告球员构造 returned/available 事实。
- 重复响应保持 revision 幂等，并为每次采集追加两队历史回执；更正只形成新修订，旧 cutoff 仍读到旧值；失败不留下部分投影。
- 使用现有 P104 append-only observation ledger 和 legacy projection，不增加数据库表/迁移，不调用供应商、不连接生产、不修改模型概率。
- 固定响应单测、隔离 PostgreSQL 16 的 P104 球员观察回归（显式 loopback 端口，仍要求专用用户、数据库名与数据库 marker）、lint/typecheck、CI 必跑模块检查、独立只读审查、scope/budget/quality gate 全通过。
