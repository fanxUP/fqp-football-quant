# 52_Codex 开发与 Docker Desktop 设计归档

> 历史设计摘要，不是操作手册。

早期方案确立了两项仍有效的原则：依赖不以静态版本号锁死，实际运行版本应可记录；Codex 负责开发、测试、维护和诊断，不替代常驻任务进程。

当时关于“直接执行 Docker Compose”“容器内任务是唯一运行模式”等描述已经被当前流程替代。现在的唯一操作口径是：

1. 在本机工作目录开发、测试并提交；
2. 使用 `./ops/local/run_local_stack.sh deploy` 推送 GitHub 并核验提交 SHA；
3. 仅在校验通过后由 Docker Desktop Compose 重建发布服务；
4. 本机 Scheduler 与 Docker Scheduler 不得并行。

详细命令见 [54_本机运行与DockerDesktop弃用说明.md](54_本机运行与DockerDesktop弃用说明.md) 和 [../ops/local/README_Codex_Docker_Desktop.md](../ops/local/README_Codex_Docker_Desktop.md)。
