# P108-02 设计：球员归属与参赛资格分离

## 归属候选

`player_affiliation_candidates` 从已发布的 `football_history_available` 筛选 Titan `player_transfers`，读取既有 `source_player_id`、归一化有效/结束日期、转出/转入来源队伍、来源记录键、批次 SHA-256、规范化版本与导入时间。不会复制转会事实。仅当 `(titan007, external_player_id)` 的 P108-01 链接为 `verified` 时才输出 canonical `player_id`；其他状态均为空。每行明确 `candidate_only`，不表达当前所属球队或注册资格。

## 注册资格事实

`player_registration_authority_sources` 保存来源的权威核验与审批/停用修订，迁移不预置任何获批来源。`player_registration_facts` 保存来源球员 ID、来源赛事/赛季 ID、可选 canonical `competition_season_id`、来源记录键/版本/内容 SHA-256、`unknown|confirmed`、资格布尔值、来源权威类别、有效起止日期、source publication/acquisition 时间、证据引用、审查者与时间。起始日期含当天，结束日期不含当天。每次新的来源修订新增行；两个账本的更新、删除、截断均由触发器拒绝。`confirmed` 必须有映射到 canonical 赛季、完整有效区间、明确布尔值、已批准匹配权威类别及人工复核。

`get_registration_eligibility` 要求调用方明确提供比赛有效日和知识截止时刻；`known_at` 表示系统当时实际可用知识，不是来源声称的历史时间。事实必须在截止前采集并写入本库，且所需人工复核也必须已完成；来源审批修订同样要求截止前写入和复核。这样，截止后才导入的旧赛季回填、截止后才审核的事实，以及截止后才审核的来源批准都不会倒灌进旧时间截面。查询再校验事实有效区间及当时的来源审批和球员身份映射创建/更新时间与审核时间。缺事实、来源当时未批准/已停用、显式未知、事实未生效/已过期均返回 `unknown`，不会用 Titan 转会、旧历史批次导入时间或“无伤停记录”推断资格。结果只对截止时已 verified 且已审核的身份暴露 canonical player ID；之后才验证、审核或后来被撤回的映射不会用于更早的预测。当前资格视图也按北京时间有效日、系统可见时间、事实审核时间及权威来源审核时间 fail closed。

## 当前来源边界

`configs/data_catalog.yaml` 仅登记共享数据契约，不授予权限。现有目录没有注册/资格来源，也没有官方注册样本。因此 Titan 保留为历史参考，资格数据产品默认 unknown；本批不会新增获批来源或写入 confirmed 记录。
