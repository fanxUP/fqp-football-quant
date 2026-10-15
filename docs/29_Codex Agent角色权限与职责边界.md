# 29. Agent 角色与审核边界

## 现行规则

1. 登记项目 Agent 时采用 `configs/agent_registry.yaml` 的名称和权限声明。原因：`agent_registry.py` 从该文件读取并初始化登记记录。
2. 角色权限以任务授权和实际入口共同判断，不把 YAML 当作所有写入的自动拦截器。原因：当前代码没有全局执行该权限矩阵的中间件。
3. 创建项目 Agent 任务时明确目标、范围、输入、验收和风险等级。原因：`AgentTask` 与 `agent_tasks` 使用这些信息跟踪工作。
4. `L4/L5` 或显式要求审核的任务保留人工审核闸门；待审核任务不能直接转为 `approved/merged`。原因：`orchestrator.py` 会创建并检查 pending review gate。
5. 推荐发布、资金规则、生产迁移、实票编辑和模型激活按 `human_review_gate.py` 的高风险类型检查审核状态。原因：这些操作有明确的 `approved` 校验；任务创建器仍需正确声明风险或审核要求。
6. 通过 `activate_simulation_ticket` 激活 generated 票单时提供已批准状态。原因：该函数调用推荐发布审核；每日虚拟竞赛购票是另一流程。
7. 实票修改或删除遵循用户授权，并保留现有存储层审计。原因：实票已有合法的编辑/删除接口，一律禁止删除与现有功能冲突。
8. 在任务记录或交付中保留实际命令、差异、结果和影响。原因：数据库审计不会自动捕获任意聊天工具操作。

## 实现入口

`scripts/agents/orchestrator.py`、`scripts/agents/human_review_gate.py`、`scripts/agents/cli.py`、`scripts/model_storage.py`、`scripts/real_ticket_storage.py`。
