# P106-MANIFEST-PERSISTENCE

## 目标

为每个新 Maher-SPF 模型版本持久化拟合实际使用的完整训练清单，并将清单摘要绑定到模型工件和后续 prediction run。只有数据库中的清单能通过完整性验证时，Maher 来源才标记为 complete。

## 范围

- 新增只追加的 `model_training_manifests` 表和 SQL 112 迁移。
- 在训练事务内保存 canonical manifest、JSONB、计数与摘要；失败时一并回滚新模型及活动版本切换。
- 预测路径读取对应模型版本的清单并核验；缺失或损坏时只将来源标为 incomplete，不阻断普通预测。
- 版本 73 等历史模型不回填；不改变训练样本规则、概率、模型算法、公开 API 或外部数据调用。

## 验收

按 `.vibe/ACCEPTANCE.md` 中的 A106-05 验收。包含固定样本测试、隔离 PostgreSQL、生产迁移器在已应用 111 的隔离副本上演练、静态与 scope/budget 检查、独立审查及精确 head CI。

## 数据库与发布风险

迁移仅创建一张带现有 `model_versions` 外键的 append-only 表，无历史回填和删除操作；在副本上验证锁/语句超时、现存模型数量、权限和迁移账本。生产发布须按 deploy-recovery 完成有效恢复材料、服务状态、迁移就绪核验及发布后健康检查。

## 完成边界

代码发布不等于完整 P106 生产验收。上线后等待 2026-10-26 02:00 的自然 MLE 训练及其后续自然 prediction run，确认清单逐行可读、摘要匹配且 run provenance 完整；不手动触发训练，也不回填旧模型的来源证据。
