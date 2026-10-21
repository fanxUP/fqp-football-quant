# P117：部署版本提示与强制重新登录

## 任务类型与风险

- 类型：跨后端会话校验、前端登录状态与发布版本检测。
- 风险：STRICT；改动会撤销全部旧版本会话并改变客户端访问状态。
- 运行环境：生产服务器由 Git checkout 发布；后端可读取当前 checkout 的提交 SHA。

## 目标

每当服务器运行的 Git 提交发生变化，拒绝旧提交创建的会话；已打开的已登录页面最多每 30 秒发现一次版本变化，出现不可关闭的更新提示，清理旧会话后刷新到登录页。

## 设计

1. 服务器发布脚本为每次目标发布和回滚原子写入 `.runtime/release-id`，值由提交 SHA、UTC 时间和 UUID 组成；后端优先读取该标识。非发布启动读取 `FQP_RELEASE_ID`，再回退到 Git HEAD 完整 SHA，Git 不可用时使用 `VERSION`。
2. 登录时将 release ID 与 Redis session 一同写入；校验时要求 session release ID 与当前后端一致。已有但缺少 release 元数据的会话视为过期。Redis 原 session 值保持 `admin`，避免扩大会话值格式变化。
3. 在公开的 `/api/auth/release` 提供不缓存的 release ID。`/api/auth/me` 对旧版本会话返回可识别的 `deployment_changed` 响应；登出同时删除 Redis 状态并清理 HttpOnly cookie。
4. 前端初始化检查 session；登录后每 30 秒检查 release，页面重新获得焦点时立即检查。版本变化后阻止继续使用旧页面，显示不可跳过的可访问提示，用户确认后登出并刷新到登录页。

## 非目标

- 不改密码验证、角色、会话 TTL、生产登录方式或模型供应商登录。
- 不增加数据库迁移、依赖、服务；不自动提交、合并或实际部署。
- 不在当前授权范围内新增或运行测试。

## 主要风险控制

- release ID 只用于相等性判断，不携带凭据；Redis 失效仍按现有逻辑拒绝访问。
- 旧版本 session 不因访问而延长 TTL；保持旧记录到原 TTL，供 `/me` 向用户说明为何必须重新登录。
- Release endpoint 设置 `no-store`；网络错误时不误登出，下一轮继续检查。
