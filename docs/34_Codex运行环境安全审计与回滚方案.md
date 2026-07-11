# 34. Codex 运行环境、安全审计与回滚方案

## 1. 环境分层

```text
local-dev：本地开发，Codex CLI/IDE 可直接修改。
dev：开发服务器，允许自动测试和非生产数据。
staging：预发环境，连接脱敏或影子数据。
prod：生产环境，只允许受控任务和人工审核。
```

## 2. Secret 管理

Codex 不应把密钥写入代码、日志或文档。所有密钥进入：

```text
.env
Secret Manager
Docker secrets
CI/CD encrypted variables
```

## 3. 数据安全规则

```text
历史赔率快照禁止覆盖。
真实票据禁止删除。
真实用户数据禁止导出到开发环境。
生产数据库禁止 Codex 自主执行 DROP/TRUNCATE。
日志中不得输出密钥、Cookie、完整票据图片 URL。
```

## 4. 审计日志

记录：

```text
谁发起任务
哪个 Agent 执行
改了哪些文件
执行了哪些命令
写入了哪些表
生成了哪些推荐
是否通过审核
是否触发熔断
```

## 5. 回滚策略

### 代码回滚

```text
git revert <commit>
重新部署上一个镜像 tag
重启 worker
运行 smoke test
```

### 数据库回滚

```text
每个 migration 必须有 down SQL
迁移前自动备份 schema
高风险迁移先在 staging 验证
生产迁移必须人工确认
```

### 模型回滚

```text
model_versions 保留 is_active 标记
新模型异常时切回上一 active 版本
已生成推荐不自动重写，需标记失效或重算
```

### 配置回滚

```text
configs 使用版本号
资金规则、熔断规则、Agent 权限配置必须有 changelog
```

## 6. Codex 安全提示

每次涉及生产时必须在任务里写明：

```text
环境：prod/staging/dev
是否写生产库：是/否
是否影响推荐：是/否
是否影响资金：是/否
是否需要人工审核：是/否
回滚方案：具体命令
```
