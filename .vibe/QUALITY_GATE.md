# P138 质量门禁

- 仅在唯一 `main` 分支直接推进；不新建分支或 worktree。
- 变更严格限制为 `.vibe` 控制记录以外的预测 job、既有单元测试、隔离 PostgreSQL 回归，以及 CI 暴露的 Dashboard 计数动画时序断言四个代码路径。
- RED 单测先证明当前查询未设置 cutoff；GREEN 后单测和隔离 PostgreSQL 真实行选择回归全绿。
- 无 DB schema/migration、依赖、API、模型参数和生产数据更改；不手动触发生产预测。
- 主线 exact-head CI、独立只读审查、V4 scope/budget 与 diff 通过后再评估是否发布。
