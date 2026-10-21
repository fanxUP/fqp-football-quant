# P118：前端构建开发依赖的可回退发布

## 目标

安全发布已经修复的前端开发依赖漏洞，同时让失败回退重建旧版前恢复旧版依赖树。

## 边界

- 仅针对前端 `devDependencies.vite` 和 `devDependencies.vitest` 的版本更新及其锁定传递依赖。
- 不放行前端生产依赖、应用代码、Python 依赖、Node 运行时、Pi bridge 依赖或数据库迁移。
- 不降低 release evidence、主机身份、服务、readiness、保护 HTTP smoke 或有迁移时的一小时备份要求。

## 流程

1. Python 分类器读取指定 base/target 提交中的 manifest 与 lockfile。
2. manifest 的其他根字段和开发依赖键必须完全相同，只有 Vite/Vitest 版本可改。
3. 从两侧锁文件分别遍历 Vite/Vitest 的 `dependencies`、`optionalDependencies` 和 `peerDependencies` 闭包；只接受闭包内且两侧均标记为 `dev: true` 的变更项，拒绝无关开发依赖变更。
4. 部署前运行 `npm ci --ignore-scripts`，随后构建新前端。
5. 如果发布失败，checkout 回滚 SHA，再按旧锁文件执行 `npm ci --ignore-scripts`，再构建旧前端并恢复服务；旧依赖无法安装时停止 Nginx，拒绝以混合依赖继续运行。

## 主要风险控制

分类器默认拒绝未知/缺失字段，任何生产包变化都回到专门依赖发布流程。生产服务不加载 Vite/Vitest；锁文件仍固定可复现构建。代码与服务回退不执行破坏性数据库回滚。
