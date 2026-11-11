# 质量门禁：P108-05A / P111 / P114 点时输入切片

- 单分支 `main`；当前代码提交 `7aeb1fe37bb3eb29a3d990b919833e4bb275cc4c`。
- 本地固定样本与隔离 PostgreSQL 验证通过：相关 6 个模块 204 passed、0 failed、0 skipped；Ruff、格式、3 个实现模块 mypy、compileall、diff、scope/budget 通过。
- P108 球员回执保持 withheld，不改变正式预测；P114 历史标签只认提交可见的来源观测回执。
- 没有迁移、依赖或公共 API 变化；未访问生产数据库或正在回填的 SQLite。
- 独立复核曾发现一个下游来源发布时间可早于开球的 MAJOR；P106/P111 两个消费者已补边界与字段一致性校验，同一审查者只读复核确认关闭。
- GitHub exact-head CI run `42949441719` 已通过；本地、隔离 PostgreSQL、独立复核、scope/budget 均通过。服务器当前仍运行 `3ed1ba8490fc11a67ce31457644c113050ab02af`；服务与 readiness 健康，`deploy.sh --plan` 成功且无迁移/依赖变化。**目标 `7aeb1fe` 尚未部署，发布后 smoke 和正式发布证据待完成。**
- 即使该工程切片发布，A108/A111/A114/A115 仍须分别依赖真实数据与观测完成，不可合并成一个本地测试结论。
