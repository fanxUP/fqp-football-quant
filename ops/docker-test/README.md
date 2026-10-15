# GitHub 基线的 Docker Desktop 本地测试

初始探针基于 GitHub main 提交 `202ac4a9b5b3a0fde93d416832359e5e2de4171e`。Compose 用于本地隔离部署，源码与发布状态以 Git 记录为准。现行运行边界见 [运行规范](../../docs/54_本机运行与DockerDesktop弃用说明.md)。

栈包含前端、API、Scheduler、Worker、PostgreSQL 16 和 Redis；使用独立卷及回环端口。官方与新闻采集关闭，启动健康快照只写测试库。工作树变更不会自动更新已有镜像。

## 操作规则

1. 从该工作树根目录使用下列项目名、环境文件和 Compose 文件管理测试栈。原因：明确项目边界可避免误操作其他容器。
2. 保持该探针的数据和凭证与生产隔离，保留关闭采集的配置。原因：测试启动也会迁移和写入数据库。
3. 私密 `.env` 不提交或打印，首次登录后修改公开默认密码 `admin123`。原因：环境文件包含凭证，默认密码不适合保护实例。
4. 按授权重建镜像并记录结果；发布时设置 `FQP_IMAGE_TAG` 为提交短哈希、`FQP_REVISION` 为完整哈希，后者写入镜像版本标签。原因：旧镜像不包含新增修改，独立标签保留回滚版本。
5. 普通停止使用 `down` 保留卷；仅在明确要删除此测试数据时使用 `down --volumes`。原因：卷删除不可由重新拉取代码恢复。

## 启动

```bash
docker compose -p fqp-gh-main-202ac4 --env-file .env -f compose.desktop-test.yml up -d --build
```

首次启动会构建镜像并向新测试库应用迁移。前端地址为 `http://127.0.0.1:18066`，API 为 `http://127.0.0.1:18080`。

## 查看与停止

```bash
docker compose -p fqp-gh-main-202ac4 --env-file .env -f compose.desktop-test.yml ps
docker compose -p fqp-gh-main-202ac4 --env-file .env -f compose.desktop-test.yml logs --tail=100
docker compose -p fqp-gh-main-202ac4 --env-file .env -f compose.desktop-test.yml down
```
