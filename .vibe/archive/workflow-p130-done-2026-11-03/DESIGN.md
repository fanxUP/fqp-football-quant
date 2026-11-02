# P121 设计

## 输入和模型

选择现有 `maher_poisson` 的已激活、`converged=true` 参数，并仅评估 SPF。参数必须包含双方球队的攻防项和满足旧模型 `MIN_MAHER_MATCHES` 的样本数。此条件不满足时记录 `model_unavailable`，不回退到市场赔率拟合。

读取 P104 当前有效的 `observed-cutoff-pilot/v1` 批次与 cutoff。P104 当前只稳定提供带时点的 `temperature_2m`、双方首发名单确认状态和带覆盖证据的伤停原始报告；首发强度、伤停影响及 `data_completeness_score` 尚无可信派生值。Maher SPF 影子计算只要求有效气温，用既有天气公式中的温度项产生有界总进球修正；降水、风速、湿度等未观测维度继续未知。首发/伤停状态和对应观测修订号保留在审计回执，不参与强弱修正。

使用当前唯一已激活且收敛的 Maher 参数和精确的 P104 温度值计算有界 SPF 概率。只有模型与气温都合格才产生概率；不从赔率拟合 lambda。结果只写入独立影子消费者的 append-only `prediction_input_consumptions.result_refs`，包括模型版本、公式版本、批次、cutoff、as_of、输入版本、使用字段、来源修订号、原始/调整 lambda、概率和调整原因。原 `model_predictions`、委员会和推荐写入均不调用。

## 更新与失败行为

独立版本化 SPF shadow consumer key 追踪新模型路径，不覆盖 readiness consumer。每轮仍按比赛有界领取，使用 P105 claim/version/lease 围栏去重和并发。输入变化、过期、停售、开球、身份不明、气温缺失或模型参数不合格时，不生成概率；只保留明确的待核实/不可用回执。重复完成返回原始结果回执。

## 证据边界

影子结果证明计算实际读取了观测字段，不证明新输入带来预测提升。真实前瞻覆盖、时间切分回测、manifest/完整 run 与发布门槛仍由 P106 后续切片完成；正式启用由 P115 管理。
# P105-WEATHER 设计

- 定义唯一来源常量 `WEATHER_COLLECTION_HOURS` 与 `WEATHER_COLLECTION_MINUTE`，供 scheduler 和运维状态说明共用，避免时间配置分叉。
- 将小时定为 0、4、8、12、16、20，分钟为 7。APScheduler 已用 Asia/Shanghai 配置 cron 时区；四小时轮询给六小时的 observation freshness 留两小时调度与执行余量。
- 保持 collector 当前每次最多 50 场及 Open-Meteo 客户端节流；按每次请求一次成功计算，基线约 50×6=300 次/日；计入最多 3 次请求尝试，保守上界约 900 次/日。失败或跳过时不制造新事实，模型读取仍按既有 6 小时有效期降级。
- 不尝试从全局销售营业时间、开赛时点或 `saleStatus` 推断逐场停售时间。
