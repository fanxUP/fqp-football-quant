# Codex 模块升级任务提示词模板

你是 FQP 项目的 Codex 开发 Agent。本任务只允许修改指定模块，不允许跨模块大范围重构。

## 任务信息

- 任务ID：{{task_id}}
- 模块：{{module_code}}
- 目标：{{goal}}
- 允许修改文件：{{allowed_files}}
- 禁止修改文件：{{forbidden_files}}

## 必须读取

1. configs/final_module_registry.yaml
2. configs/module_dependencies.yaml
3. configs/final_panel_registry.yaml
4. 对应模块 README.md
5. 对应 OpenAPI 契约
6. 对应 SQL migration
7. 对应测试文件

## 输出要求

1. 修改代码或文档。
2. 补充测试。
3. 说明影响范围。
4. 说明回滚方式。
5. 不得修改合规边界。
6. 不得删除历史快照、审计日志、模型版本。

## 验收命令

```bash
pytest {{test_path}}
python scripts/modules/migration_guard.py {{migration_files}}
```
