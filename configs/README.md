# 配置注册表说明

当前运行时唯一使用的模块与面板注册表是：

- `final_module_registry.yaml`
- `final_panel_registry.yaml`

旧文件 `module_registry.yaml`、`panel_registry.yaml` 仅保留作历史兼容参考，
不应再用于新增模块、页面、权限或依赖。新增配置必须同步最终注册表，并通过
`scripts/modules/module_loader.py` 和 `scripts/modules/panel_registry.py` 校验。
