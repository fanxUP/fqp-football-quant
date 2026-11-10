# P111-01 局部验收：算法核心

- [x] training manifest 的 included 样本与拟合行一一一致，哈希可重复。
- [x] 所有训练赛果均在拟合 cutoff 前开球并在 cutoff 前/当时正式公布；超时或未知标签不进入拟合。
- [x] season context 每场都有来源摘要，且所有样本属于唯一 competition 与 competition-season；混季输入失败。
- [x] 季赛映射/场地事实的可用时间不晚于拟合 cutoff；目标赛事事实不晚于 prediction_as_of。内容摘要不是来源授权或真实性证明。
- [x] 配置公开记录算法版本、半衰期、联赛基准、先验强度、主场先验与换季中性重置策略。
- [x] 中立场预测不含主场优势；非中立场由拟合主场参数解释。
- [x] 共用联赛基准不重复计入主场效应；比分矩阵的尾部质量不超过 `1e-10`，高进球率下矩阵自动扩展。
- [x] 新队/小样本队被收缩到中性先验；升班马映射只使用显式 evidence ref，不按名称/联赛推断。
- [x] 预测 cutoff 早于开球，且不得早于模型训练 cutoff；fixture competition-season 必须严格匹配。
- [x] SPF 和比分概率有限、非负且归一；候选 digest 绑定 manifest、season-context、参数、模型相关源码和 Python/NumPy/SciPy 运行时版本。
- [x] 固定样本回归 31 项、Ruff、format、mypy、compile、diff、V4 scope/budget 通过；最终结果以当前工作树重新运行记录为准。
- [x] 本地代码验收不等于 A111；无数据库持久化、正式发布、效果优越性或前瞻验收主张。
