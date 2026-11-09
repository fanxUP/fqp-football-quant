# P108-03 质量门禁

- 仅在 `main` 顺序开发；八路径、零迁移、零依赖；禁止改动其他消费者、API 或模型分数。
- RED/GREEN/REFACTOR；本地固定响应；PostgreSQL 必须指向带专用 marker 的 disposable PG16 数据库；地址限 `127.0.0.1`，用户名与库名须精确匹配，端口只从显式 DSN 读取。拒绝 `hostaddr`、service 路由参数及环境变量 `PGHOSTADDR`、`PGSERVICE`、`PGSERVICEFILE`，防止 libpq 将连接改道。
- API-Football 的 `Questionable` 表示 doubtful；`Missing Fixture` 只表示该球员缺席。仅当缺席原因明确标为停赛或包含可识别伤情时分类为 suspended/injured，否则为 unknown。
- 所有来源时间从明示字段读取且有时区；没有时保持 null；不得推断 `updated_at`、比赛时间或采集时间。
- PostgreSQL 验证 append-only cutoff/revision、原子事务、空响应 coverage 和 confirmed-vs-predicted 区分。
- CI 将 P104 player observations PostgreSQL module 列为必跑项且不得 skip。
- 独立只读审查、scope、budget、regression、V4 quality gate 通过后才关闭；本批不连接生产、不部署。
