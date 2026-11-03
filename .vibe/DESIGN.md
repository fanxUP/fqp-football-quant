# P138 设计：固定 cutoff 的赔率快照

## 根因

`run_model_prediction._run_impl()` 固定记录批次 `predict_time`，但单场计算读取赔率时只按 match/play type/open 过滤并取最新行；RQSPF 让球查询也没有时间条件。因此在耗时约 1–2 分钟的任务中，计算后半段会选到任务开始时点之后新采集的赔率。生产 run `224063` 已复现：620 个输出组中 451 个组、1,353 个赔率选项时点晚于 `predict_time`，最晚 4 秒。特征快照查询本身已有 `as_of=predict_time`。

`prediction-input-fence/v1` 是并发更新版本栅栏，不是 P104 观测版本证明；其 `input_version=null` 可表示当前尚无更新头，不能单独据此判泄漏。此次缺陷是可证实的赔率时间越界。

## 修正

- 沿用本次 run 已冻结的 `predict_time`，为主赔率读取增加 `snapshot_time <= predict_time`。
- 用同一 cutoff 限制 RQSPF handicap 行。
- 排序固定为 `snapshot_time DESC, id DESC`，保留最新合格行并消除同秒不确定性。
- cutoff 后才到达的快照只供下一次 run 使用。截止前无赔率则继续使用当前已有的缺数处理。

不改变 `predict_time` 定义、任务调度、预测模型、DB schema、官方结算和历史结果。
