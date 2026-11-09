# P108-01 设计：可审计的来源球员 ID 映射

以 `(source_name, external_player_id)` 唯一定位来源身份，映射目标是现有 `players.id`。当前映射保留 `unresolved/candidate/verified/rejected` 状态、来源证据引用、匹配方法、置信评分、审查人和时间、递增修订；每次状态变化追加不可变事件。

业务读取只接受 `verified`。已存在但未验证/被拒绝的映射必须阻止回退猜测。API-Football 兼容仅允许精确查询现有 `players.player_code=apifootball:<id>`；姓名/生日只用于候选提示，绝不自动建立 verified 映射。

候选工具只处理两个本地 CSV，输出稳定排序的建议清单，不访问数据库或网络。应用角色仅 SELECT 映射，不获得写权限。down 迁移遇到任何映射或审计事件时拒绝删除。
