# 本机开发与 Docker Desktop 部署说明

## 决定

自 2026-07-11 起，本项目恢复 Docker Desktop 作为运行环境；开发仍在 macOS 本机工作目录中进行。每次 Docker 部署均以已推送 GitHub 的提交为版本边界。

本文是当前运行规则；其他文档中“未使用 Docker Desktop”的表述，除非明确标为当前规则，均为对应阶段的历史验收事实。

## 本机开发

```bash
cp .env.local.example .env.local
./ops/local/run_local_dev.sh
```

## Docker Desktop 部署

```bash
./ops/local/run_local_stack.sh deploy
```

脚本依次确认工作区没有未提交或未跟踪文件、推送当前分支到 GitHub、比对远端提交 SHA、重建 Compose 服务、检查 `8000/health` 和前端首页。任何 Git 同步失败都会阻止 Docker 启动。

数据库、Redis 和备份位于宿主机 `data/` 下；不提交 Git，也不会因容器重建而自动删除。

## 后续规则

- 代码在本机开发、测试与提交；禁止在容器内直接修改源码。
- Docker Desktop 仅通过 `ops/local/run_local_stack.sh deploy` 同步，避免容器版本和 GitHub 版本漂移。
- API 密钥仅保存在忽略的本地 `.env.local` 中；示例文件只保留占位符。
