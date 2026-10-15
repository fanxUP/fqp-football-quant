# 配置与注册表规则

1. 模块与面板变更维护 `final_module_registry.yaml`、`final_panel_registry.yaml`，不向旧注册表扩展功能。原因：`routers/ui.py` 读取最终注册表，旧文件只保留兼容参考。
2. 使用最终注册表的实际字段，并核对运行时接口与页面路由。原因：字段校验脚本不是完整运行时，菜单配置也不会自动生成路由。
3. 修改依赖时核对 `module_dependencies.yaml` 和实际代码消费者。原因：配置声明不能说明所有 Python 导入与后台调用。
4. 调度以 `scripts/jobs/run_scheduler.py` 和 `scripts/official_crawler_stub.py` 为准。原因：`ai_scheduled_jobs.yaml` 已明确标记为历史设计。
5. Agent 与权限声明按实际入口核实，不能把配置等同于全局执行拦截。原因：部分规则依赖调用方显式调用审核函数。
6. 依赖版本以当前包清单、lockfile 和 CI 为准，不按旧的“一律最新版”声明自动升级。原因：现有工程已限定 Python/Node 范围并包含精确版本。
7. 修改配置时同步其仍有效的文档说明。原因：未消费配置和历史设计不能作为新增实现的依据。

辅助检查入口：`scripts/modules/module_loader.py`、`scripts/modules/panel_registry.py`；运行时行为仍以 `apps/backend/src/routers/ui.py` 为准。
