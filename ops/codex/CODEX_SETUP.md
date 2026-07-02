# Codex 开发环境设置建议

## 1. 推荐开发方式

- 本地使用 Codex CLI 或 IDE 插件处理代码修改和测试。
- 大任务使用 Codex Cloud / App 的独立 worktree 并行处理。
- 每个 Agent 任务对应一个独立分支或 worktree。
- 高风险任务只在 staging 执行，不允许直接操作 production。

## 2. 本地目录约定

```text
fqp/
├── docs/
├── sql/
├── scripts/
├── configs/
├── tests/
└── templates/codex/
```

## 3. Codex 任务启动前检查

```text
确认当前分支
确认任务编号
git status 必须干净
读取相关 docs/sql/configs
确认 forbidden files
确认是否 human review required
```

## 4. Codex 完成后必须输出

```text
变更文件清单
测试命令
测试结果
是否影响生产
是否影响资金/推荐/实票
回滚方案
```

## 5. 生产安全

Codex 不应直接拥有生产数据库超级权限。生产任务通过最小权限服务账号执行，并写入审计日志。
