# 本地工程验收：P108-05A / P111 / P114

本验收仅覆盖当前代码切片，不等同于 A108、A111、A114 或 A115 通过。

- [x] 球员候选回执保持 `withheld`，不写正式预测概率。
- [x] 点时训练标签要求来源观测、官方发布时间、取得时间及事务提交可见回执均严格早于 cutoff。
- [x] 固定样本回归：214 passed、0 failed；没有夹具的首次运行中有 159 个 PostgreSQL 用例跳过，随后单独补跑。
- [x] 隔离 PostgreSQL 16 回归：观测、P105 输入运行时和 P106 预测运行存储共 169 passed、0 failed、0 skipped。
- [x] Ruff、格式、10个源码模块 mypy、compileall、git diff --check、scope/budget 通过。
- [ ] 独立复核当前完整发布 diff、GitHub exact-head CI、服务器发布与只读 smoke。
- [ ] 真实球员事实/分钟链验收、真实 P111 训练、P114 样本外效果和 P115 前瞻窗口仍需各自的数据证据。

不将缺失时间补造为历史事实，不把本地或合成回归描述为模型效果验收。
