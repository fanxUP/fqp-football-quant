# Codex 开发 + Docker Desktop 本地部署说明

## 最终执行原则

1. 项目使用 Codex 作为开发、维护、测试、修复、重构和代码审查工具。
2. 项目部署运行在本地 Docker Desktop，不依赖复杂云服务。
3. 组件依赖不锁死版本：本地已有组件优先使用本机当前版本；缺失组件按官方渠道安装当前最新版。
4. 本地长期运行由 Docker Compose + Scheduler + Worker 完成；Codex 不作为生产守护进程，只负责开发与受控维护。
5. 每次启动执行 `scripts/local/check_local_environment.py`，生成 `data/runtime_version_snapshot.json`，用于排错和复盘。

## 启动流程

```bash
cd ops/local
./run_local_stack.sh
```

Windows 可在 PowerShell 中执行：

```powershell
cd ops/local
.\setup_local_latest_windows.ps1
docker compose -f docker-compose.local.yml up --build
```

## 不指定版本策略

- `requirements.txt` 只写包名，不使用 `==`。
- Dockerfile 使用 `FROM python`，不指定 Python 镜像版本。
- Docker Compose 使用 `postgres`、`redis`，不指定固定 tag。
- 前端 `package.json` 使用 latest 依赖或不固定版本。
- 如果需要追查问题，查看 `data/runtime_version_snapshot.json`，它记录的是本机实际运行版本，不是项目版本锁。

## 风险控制

不锁版本会提高升级便利性，但也会降低复现稳定性。因此项目增加三道保护：

1. 启动前记录实际版本快照。
2. 更新依赖后运行本地 smoke test。
3. 如果最新版导致异常，由 Codex 创建修复分支，必要时回滚 Docker 镜像或恢复上一份数据备份。
