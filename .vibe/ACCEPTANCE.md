# A104-SALE-STATUS：官方竞彩销售状态映射纠正

1. 固定官方响应证明 `sellStatus=1` 是已开售、`sellStatus=2` 是暂停销售；解析器将 2 映射为非 selling 状态。
2. 暂停、待开售、缺失或未知的比赛级状态不会把玩法标记为开放，也不会产生开放赔率快照；只有比赛在售且对应玩法池明确 `poolStatus=selling` 时才开放。缺少玩法池/池状态时，即使有赔率也 fail closed。
3. `sellStatus` 优先于旧别名 `saleStatus`，冲突时不把已暂停场次误判为在售。
4. 官方 `sellStatus` 只接受整数或数字字符串，非数字官方值 fail closed；仅当官方字段缺失/空值时才使用旧别名，并只接受已知标准文本状态。
5. 不生成或推断 `sale_stop_time`；P121 的现有硬门槛、数据库结构和公开 API 均不改变。
6. 布尔 `sellStatus` 值作为未知状态 fail closed，不会因 `bool` 是 Python `int` 子类而误判为销售状态。官方解析器固定样本回归、Ruff、格式、compileall、`git diff --check`、V4 scope 和 budget 全部通过：仅 2 个源码/测试路径、0 新文件、0 依赖、0 迁移、0 公开 API。
7. 本地/隔离测试不连接生产数据库、不请求真实供应商 API；合并部署前另需独立只读审查和正式发布门禁。
