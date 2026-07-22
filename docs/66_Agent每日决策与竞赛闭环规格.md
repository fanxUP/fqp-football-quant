# 66. Agent 每日决策与竞赛闭环规格

## 目标

- Scheduler 按 `Asia/Shanghai` 执行每日任务，16:00 生成 Agent 决策。
- Agent 只创建系统内虚拟票，不触发真实联网购票或支付。
- 每个自然日必须留下“已购买 / 已放弃 / 执行失败”决策与原因，便于复盘。
- Agent 票统一进入 `simulation_tickets`；用户手动模拟票与实票共同计入用户竞赛池。
- 投注中心“比赛结果”展示最近 Agent 决策。

## 数据与接口

- 复用 `daily_budget_plans` 作为每日决策账本：
  - `status`: `purchased`、`abstained`、`failed`；
  - `suggested_stake`: 当日 Agent 虚拟投入；
  - `unused_budget`: 未使用额度；
  - `reason`: 购买摘要、放弃门槛原因或失败原因。
- 新增只读接口 `GET /api/competition/decisions?limit=14`。
- 接口不得提供真实下单、支付或自动购票能力。

## 特征与调度修复

- `BackgroundScheduler` 显式使用 `FQP_TIMEZONE`，默认 `Asia/Shanghai`。
- `team_season_profiles` 写入遵循当前画像表结构，不再写旧积分字段。
- 画像构建按赛事中文名和比赛时间解析 `competition_season_id`；无法解析时跳过画像，不能回滚整场特征任务。

## 验收标准

1. Scheduler 日志显示时区为 `Asia/Shanghai`，推荐任务下一次执行时间为北京时间 16:00。
2. 特征构建不再出现 `team_season_profiles.season_code` 或旧积分字段不存在错误。
3. 推荐任务无合格候选时写入 `abstained` 和原因；有票时写入 `purchased`、票数与投入。
4. Agent 正常模式产生的票在统一账本中归属 Agent，不再归属“我的模拟票”。
5. 用户模拟票和实票都进入用户竞赛统计，结算来源分别使用 `simulator` 与 `real`。
6. 后端测试、前端测试、前端构建与代码检查通过，服务重启后健康。
