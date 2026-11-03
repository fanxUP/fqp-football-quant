# Aggregate reconciliation gate

- 只执行当前路径映射与 V4 scope/budget 检查。
- 保持 P107-06C 的 3 文件/0 新文件/0 migration 锁存档不变。
- 不 stage `uv.lock`；scope 中保留它仅为识别，不表示接受其进入提交。
- 不在此任务中提交、推送、合并、访问生产库、执行迁移或部署。
- 任何额外或缺少的差异都会令验收失败；产品路径后续变化必须新开精确切片。
