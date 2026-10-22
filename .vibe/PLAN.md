# P104-SALE-STATUS-CORRECTION — 修正官方竞彩销售状态映射

状态：READY_TO_MERGE；20 项本地回归、静态/范围/预算检查、独立只读复审和 V4 质量门禁均通过。当前代码仍只在本地 worktree，未提交、推送、合并或部署。基线为 `c62456b57114b14f3e16920bda8da8e2af90eeb4`。本切片只修复竞彩官方 `sellStatus` 语义和依赖该状态的玩法/赔率开放判断。

## 目标

竞彩网官方赛程页脚本明确区分 `sellStatus=1`（已开售）、`sellStatus=2`（暂停销售）和其他值（待开售）。当前解析器把数值 2 也记成 `selling`，且玩法/赔率解析只看 `poolStatus`。当比赛级状态是暂停时，仍可能写入 `sale_status='selling'`、`official_markets.is_open=true` 或当前开放赔率快照。

## 范围

- `scripts/official_crawler.py`
- `tests/test_scripts/test_official_crawler.py`

`.vibe/archive/workflow-p121-done-before-p104-status-correction-20261023/` 保存切换 V4 工作流前的 P121 状态文件，仅用于工作流恢复，不属于 P104 源码交付或本地源码变更预算；不要把此未跟踪归档目录纳入 P104 代码提交。

## 不做

- 不推断或回填 `sale_stop_time`，不放宽 P121 的停售时间/天气准入。
- 不改数据库 schema、API、模型、赔率计算、正式推荐或生产配置。
- 不连接生产数据库，不调用生产消费者，不提交/推送/部署。

## 验证顺序

1. 先加固定响应回归，证明官方 `sellStatus=2` 当前会被错误认作可售。
2. 最小修复：只有官方比赛级状态为已开售，且具体玩法池也可售时，才标记 market 开放；非已开售状态不生成开放赔率快照。
3. 运行 20 个官方解析器固定样本回归、Ruff、格式、编译、diff、V4 scope/budget，并复核源响应的 `sale_stop_time` 仍保持空值。
4. 完成独立只读复审和本地质量门禁后，才可另行讨论发布；生产刷新和部署属于后续发布步骤。
