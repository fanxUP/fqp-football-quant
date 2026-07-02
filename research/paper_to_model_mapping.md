# 论文到模型映射

| paper_key | 模型 | 输入 | 输出 | 生产用途 | 限制 |
|---|---|---|---|---|---|
| maher1982 | Maher Poisson | 历史比分、主客场 | lambda、比分矩阵 | 胜平负/总进球/比分 | 独立进球假设较强 |
| dixoncoles1997 | Dixon-Coles | 历史比分、时间衰减 | 修正比分矩阵 | 平局/低比分修正 | 参数需要稳定估计 |
| shin1993 | Shin概率 | 同玩法SP | 去水概率 | 市场概率 | 对竞彩SP需本地验证 |
| cainlawpeel2003 | FLB修正 | 赔率区间、赛果 | 偏差分层 | 热门/冷门偏差 | 不同市场偏差不同 |
| karlisntzoufras2003 | Bivariate Poisson | 进球数据 | 相关进球模型 | 平局相关性 | 实现复杂度高 |
