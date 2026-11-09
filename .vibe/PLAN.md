# P108-01 实施计划：外部球员身份桥

1. 固定范围为迁移 134、身份映射读写 helper、文件输入候选报告、三组定向测试和 CI 必跑模块登记。
2. 先写 RED：验证外部 ID 唯一、状态转换、审计修订、幂等、歧义不解析、API-Football 旧 player_code 兼容和报告确定性。
3. 添加 PostgreSQL 16 隔离测试；迁移只新建空表/触发器并提供保护数据的 down，运行 up/down/up 和回滚拒绝测试。
4. 运行目标 pytest、Ruff、格式、Mypy、scope/budget/diff 检查。所有 PG 测试必须使用 127.0.0.1 上显式命名的 disposable 数据库。
5. 不读取生产数据库，不导入本地 Titan 数据，不调用供应商 API，不更改预测或模型消费行为。
6. 本地验收后再检查 GitHub exact-head CI 与审查；任何生产迁移/导入须另行评估存储、恢复策略和运行时权限。
