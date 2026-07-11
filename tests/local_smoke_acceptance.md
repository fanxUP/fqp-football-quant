# 本机开发与 Docker Desktop Smoke Test

## 目标

验证项目能将已推送 GitHub 的本机代码同步到 Docker Desktop，并完成基础启动。

## 前置条件

- Docker Desktop 已启动。
- Codex CLI 如需开发维护，按官方当前文档安装。
- 不要求固定 Python / PostgreSQL / Redis / Node 版本。

## 测试步骤

1. 运行环境检查：

```bash
python scripts/local/check_local_environment.py
```

2. 确认生成：

```text
data/runtime_version_snapshot.json
```

3. 部署 Docker Desktop 服务：

```bash
./ops/local/run_local_stack.sh deploy
```

4. 验证后端：

```bash
curl http://127.0.0.1:8000/health
```

5. 验证前端：

```text
浏览器打开 http://127.0.0.1:3000
```

6. 验证容器：

```bash
docker compose -f ops/local/docker-compose.local.yml ps
```

## 通过标准

- 部署脚本在启动前确认本机提交已推送到 GitHub。
- Docker Compose 能启动 postgres、redis、backend、frontend、worker、scheduler。
- 后端 health 接口可访问。
- 前端页面可打开。
- 版本快照生成成功。
- requirements.txt 无 `==` 固定版本。
- Compose 文件无固定镜像 tag。
