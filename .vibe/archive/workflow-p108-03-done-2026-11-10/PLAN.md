# P108-03：首发阵容与可用性观察

1. 固定八条允许路径和零迁移/零依赖预算；复用 P104 observation ledger。
2. 先写 RED：API-Football 的 `Missing Fixture` 只说明缺席，须依据明确的伤停原因分类；来源未给出可识别原因时保持 unknown。Returned/doubtful/suspended 明确区分；只接受带时区的显式 source timestamps 和 ISO expected-return date；`updated_at` 不可代填。
3. 补充严格解析与 per-player facts；加入 `lineup_status=confirmed`；预测阵容不得写入确认投影；保持完整性、幂等、失败回滚和 coverage 规则。
4. 扩展固定响应单测与已有隔离 PostgreSQL P104 fixture，验证 cutoff、幂等修订和空覆盖语义。
5. 将 PostgreSQL 回归模块登记为 CI 必跑、无 skip；运行本地隔离测试、静态检查、scope/budget/quality gate。
6. 进行一次独立只读复核，记录具体结论；不得接入模型或部署生产。
