# 本地质量门禁

- P104-SALE-STATUS-CORRECTION 仅限官方解析器和固定样本回归两个路径。
- A104-SALE-STATUS 证据须由 `vibe evidence run` 实际执行，不手写 PASS。
- 运行回归、Ruff/格式/编译、diff、scope 和预算检查；代码树指纹改变后重跑相关证据。
- 独立只读审查通过后方可将工作流推进到 READY_TO_MERGE；发布另行执行。
