# P111-02：P106 预测运行与评价接入

## 目标

让 P111-01 单赛季动态球队候选能使用 P106 已有的训练 manifest、模型工件、不可变预测 run/group 和 prediction replay 评价链路，作为明确标记的 inactive shadow 候选。

## 实施边界

- P106 原始训练 manifest 可能包含多个联赛/赛季；P111 不能把这些样本混合拟合。适配层只依据逐场显式 canonical 赛季证据，从原 manifest 投影出单一赛季清单，继承相同 cutoff、赛果标签和选择版本，并保留父 SHA。样本映射缺失、证据过晚或属于其他赛季时逐条排除并记录原因。
- 派生 manifest 不是第二套赛果筛选规则：它不补充、不改写标签，只执行 P111 模型必要的同季分组。P111 拟合行仍必须与派生 manifest 的 included 行逐行相同。
- 赔率输入必须是同一 prediction-as-of 前的完整 SPF 三项快照：官方 h/d/a 归一到 3/1/0、市场开放、同 market_id/snapshot_time/raw_hash、每项大于 1、45 分钟内，并验证快照的 `snapshot_time` 与数据库 `created_at` 均不晚于 prediction-as-of。任何缺项、闭盘、过期或赛后回填都会拒绝整批 run。
- 通过 P106 已有的 `model_versions`、`model_training_manifests`、`create_prediction_run`、`store_prediction_group` 与 `finalize_prediction_run` 保存。候选版本始终 `is_active=false`，参数中写入 `rollout_mode=shadow`。
- 赛果确认后调用 `evaluate_prediction_replay`，将成对模型/比例去水市场指标存入已有 `backtest_runs.config`。比赛未结算时保留待评价 run，不伪造评价结果。
- 用户已要求提交并部署。本次发布只包含休眠适配器代码；数据库守卫要求 loopback 连接和受信测试库 comment，生产环境会拒绝执行。发布脚本仅运行既有健康检查和保护路由只读 smoke，不调用此适配器、不写入业务数据，也不改变服务配置、预测调度、委员会或活动模型。

## 验收重点

覆盖父 manifest 完整性、季赛投影/排除审计、cutoff、manifest/工件/run/group 的哈希绑定、赔率快照时间、inactive/shadow 不影响正式预测、PostgreSQL 完整写入与 replay evaluation。

## 非目标

不创建迁移、不注册活动模型、不调整 scheduler/委员会/正式预测写入、不让 P111 适配器连接生产数据库或供应商、不在生产环境执行候选，也不以固定样本成绩宣称模型胜过现有模型或市场。既有部署的只读 smoke 属于版本发布检查，不属于 P111 预测运行。
