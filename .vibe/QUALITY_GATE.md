# 质量门禁：P108-05A / P111 / P114 点时输入切片

- 单分支 `main`；当前基线 `b175cd2e09db12d7d6feed506d9479550adae7ec`。
- 本地固定样本与隔离 PostgreSQL 验证通过：相关 6 个模块 204 passed、0 failed、0 skipped；Ruff、格式、3 个实现模块 mypy、compileall、diff、scope/budget 通过。
- P108 球员回执保持 withheld，不改变正式预测；P114 历史标签只认提交可见的来源观测回执。
- 没有迁移、依赖或公共 API 变化；未访问生产数据库或正在回填的 SQLite。
- 独立复核曾发现一个下游来源发布时间可早于开球的 MAJOR；P106/P111 两个消费者已补边界与字段一致性校验，同一审查者只读复核确认关闭。
- 当前本地代码在已部署 `3ed1ba8` 之上有未提交变更；**尚未达到 READY_TO_MERGE/READY_TO_DEPLOY**：exact-head GitHub CI、服务器状态、受保护路由 smoke 和正式发布证据仍待完成。
- 即使该工程切片发布，A108/A111/A114/A115 仍须分别依赖真实数据与观测完成，不可合并成一个本地测试结论。
