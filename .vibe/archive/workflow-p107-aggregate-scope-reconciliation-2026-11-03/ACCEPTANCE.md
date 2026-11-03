# Acceptance

- 以固定 HEAD `4a7a37aa57b885cc3ae332731b6a6e273dd49bff` 比较，52 个业务路径与 scope 完全相等。
- 51 个产品路径都映射到既有 P107/P138 切片；唯一例外 `uv.lock` 明确标成 unowned、只计数、不修改、不 stage。
- 既有 P107-06C 原始锁仍是 3 文件；P107-06G 6 文件/3 新文件/1 迁移与审查记录独立保留。
- aggregate scope、budget 与 regression budget 检查通过；没有新增依赖、生产访问或业务数据写入。
- 该工作流不作代码正确性、GitHub CI、生产迁移或部署验收声明。
