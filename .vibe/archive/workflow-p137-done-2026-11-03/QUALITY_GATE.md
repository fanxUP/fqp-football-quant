# P137 质量门禁

- 始终在唯一 `main` 分支；当前 P136 控制面已哈希归档。
- 目标回归：Titan 原始 HTML/字段契约和 `football_fixture_result_facts` 隔离 PostgreSQL 测试，零跳过。
- 固定样本涵盖完整和错误原始行；真实本地 SQLite 仅只读扫描，不触发网络。
- 无 SQL migration、依赖或公开 API 变更；任何意外写入先停下。
- 生产导入必须通过新鲜只读预览、官方结果与身份逐行校验、短事务 dry-run 回滚、当前 ACL 确认和独立审查；失败整批回滚，不建备份、不做池结果字段回退。
- 只有 GitHub main exact-head CI 和服务/只读数据核验全部通过，方可标 DONE。
