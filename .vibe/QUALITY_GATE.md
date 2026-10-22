# P105 天气采集时效切片质量门

- 范围仅为天气采集时刻和共享状态文案；运行配置中的固定样本回归、Ruff/格式/compileall、diff、scope、budget 与 regression gate。
- 采集必须固定为 Asia/Shanghai 每 4 小时；状态页使用同一份节奏定义。确认 300 次/日成功基线、900 次/日保守请求上界，并保持 Open-Meteo 请求节流。
- 合并前须有独立代码审查、V4/迁移影响审查、安全审查与 GitHub `test`、`lint-and-typecheck` 在最终 PR 头通过；执行 `python3 -I -S -B .vibe/quality_gate.py --repo .`。
- 此切片不关闭完整 A105，不证明生产模型已消费新观测，也不提供 P121 合格比赛；部署另走正式发布门禁。
