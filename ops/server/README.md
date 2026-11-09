# Ubuntu 发布与 Nginx

在现有干净 `main` 上运行 `deploy.sh <完整提交SHA> --plan` 查看差异，按现有发布证据协议 `--apply <证据JSON>` 发布。目标须为 `origin/main`；普通待执行迁移须有迁移副本演练和一小时内校验过的备份。

无备份发布策略使用固定白名单：迁移123；迁移124、125同时且按序；仅迁移126、127、128、129、130或131；以及按序同时待执行的132+133（赛前排程、官方通知和胜平负市场参考）。124/125、126、127、128、129、130及132/133均要求SQL SHA-256与发布白名单完全一致、24小时内的隔离PostgreSQL演练、明确的无备份授权、既有数据保全、约束/触发器检查、事务回滚、2秒锁等待、30秒语句超时及零跳过测试。128还验证受限fqp的目录和导入路径；129验证别名写入与读取；130验证结果事实写入、模型候选读取、来源身份错配拒绝、追加式保护和回滚；132/133验证受限fqp写入排程与公告、赔率与开球一致、市场记录追加式保护及含运行数据时拒绝回退。混合迁移、顺序不符、SQL摘要变化或证据缺失均拒绝；其他待执行迁移仍要求一小时内有效备份。隔离演练不等同于线上数据回填或完整备份恢复能力。

126仅授予`fqp`对`official_event_season_retention`的SELECT/INSERT/UPDATE，不改既有迁移、数据、所有权或触发器，不授予DELETE/TRUNCATE/DDL/转授权。除上述通用报告项，126还要求`application_role={"name":"fqp","superuser":false,"owns_retention_table":false}`，以及`application_role_acl`、`application_business_paths`、`acl_rollback_verified`均为`passed`；须以实际受限角色验证赛季刷新、比赛存储、范围拦截与回滚，不能用管理员成功或健康接口200替代。正式发布仍须绑定真实目标提交，复核生产权限与关键路径。本地开发记录不是生产已修复证明。

127是追加两表、只读目录及约束/不可变触发器，不重写旧赛季、共同比赛或历史事实。仅授予fqp新表SELECT/INSERT、目录SELECT和新序列USAGE/SELECT；无旧表新授权。除通用报告，还要求`application_role={"name":"fqp","superuser":false,"owns_season_identity_tables":false}`及`application_role_acl`、`application_business_paths`、`acl_rollback_verified`全部passed，实际验证受限角色导入/读取、旧权限不变及DDL/ACL/账本同事务回滚。127不能与其他迁移混合。迁移后先保持新表空，再单独对固定官方材料进行新鲜身份核验与受控事务写入；旧未证实关系和模型不自动转换。已提交的追加结构保留，失败不执行破坏性DROP/数据撤销，先核实兼容版本并恢复服务。

128只为传统足彩期次/场次增加体彩来源期号、比赛日期精度、官方比分和玩法赛果字段，并扩展现有目录视图；不回填或重写旧成员、不碰`official_matches`/`official_results`。无备份例外仅接受固定SHA的128单独迁移，演练须证明旧行保持、约束/触发器可用、事务回滚，以及非超级用户`fqp`能读新目录字段并写来源事实。生产迁移后先刷新只读清单，再把玩法类型修正和历史导入作为独立、逐批事务执行；不得把演练当作生产数据写入证明。

129只追加空的 `football_fixture_identity_aliases` 表及受约束的 `football_pool_fixture_catalog` 规范身份投影；不搬动、不删除、不更新旧 fixture、来源链接、期次成员、赛季或赛果。无备份例外只接受固定SHA的129单独迁移，演练需证明受限非超级用户 `fqp` 的表权限、别名插入/目录读取路径、旧行保留和事务回滚。迁移本身不插入任何生产别名；生产映射须另行生成新鲜清单，校验直接 Sporttery MatchId、双方唯一关系、赛季与其他来源边界后再进行单独事务处理。

无备份策略由 `release_migration_policy.py` 单独校验并有固定样本测试。对应迁移集的无备份测试记录应保存在本次发布计划目录；部署前仍需核实服务器当前迁移账本和服务状态。入口负责恢复旧代码、前端及服务，不能将配置成功等同整个业务验收成功。

## 静态资源配置

服务器与 Docker 前端共用 `nginx/http.conf` 和 `nginx/static.conf`，不额外安装压缩模块或打包插件。

| 文件 | 安装位置 / 作用 |
| --- | --- |
| `nginx/http.conf` | `/etc/nginx/conf.d/00-fqp-performance.conf`，HTTP 级缓存映射和日志格式 |
| `nginx/static.conf` | `/etc/nginx/snippets/fqp-static.conf`，仅 FQP 站点 include |
| `configure_nginx.py` | 默认只读预览；`--apply` 安装、检查及重载，失败恢复原文件 |

安装器仅在标准 `sites-enabled/*` 或 `conf.d/*.conf` 中寻找直接位于 `server {}`、root 为 `/var/www/fqp` 的唯一站点；跟随 `/etc/nginx` 内部启用链接并去重，拒绝歧义或指向外部的链接。插入一个 include，保留原有 listen、TLS、代理、上传、认证和安全设置。非标准多层 include 布局需要先核实，不自动覆盖整个站点。

`deploy.sh` 在停止应用前预览并检查现有 Nginx，前端发布成功后才安装配置。安装前/后分别 `nginx -t`；验证失败恢复文件，重载失败还会重新载入原配置，随后发布器恢复旧应用。恢复本身失败会明确输出 `ROLLBACK_REQUIRED` 并返回独立退出码 3；发布器停止应用与 Nginx，不能在未核实配置时自动重启。

如需单独查看变更，运行 `.venv/bin/python ops/server/configure_nginx.py --plan`；应用配置需要服务器管理权限。不会创建额外站点、改变监听地址或自动启用 HTTPS。

## 缓存、压缩与日志口径

- 只有 `/assets/` 下符合 Vite 内容哈希命名的 JS/CSS/字体/图像成功响应缓存一年；非哈希文件、HTML、现有未版本化登录图重新验证。缺失 chunk 返回真实 404，不回退为 SPA HTML，不附加一年缓存。
- 使用 `expires` 生成缓存头，保留旧版 Nginx 的安全响应头继承；没有添加 `immutable`，也不依赖 1.29.3 才提供的头合并指令。
- gzip 仅显式开启于静态 HTML、JS、CSS、SVG，级别 5，最小 1 KB，按客户端能力发送并带 `Vary: Accept-Encoding`。不对已压缩 WebP/字体重复压缩。不修改已有 API 压缩策略。
- 站点明确关闭 Nginx proxy cache；API/auth/release 的动态响应仍透传后端状态及缓存控制，部署后的强制登录语义不变。此配置不新增 SPA 页面或业务缓存。
- FQP access log 沿用 `/var/log/nginx/access.log` 及服务器既有轮转，格式改为 JSON。记录 request/upstream 总耗时、首包/连接耗时、传输字节及 gzip 比例；字段 `backend_request_id` 对应后端已观测读取的 `X-Request-ID`。非观测路由没有该 ID，显示 `-`。
- 日志只记录规范化 URI，不含 query、Cookie、Authorization、来源页面或请求体。`request_time` 包含客户端传输等待，不等同 SQL 耗时；与后端 pool/sql 的日志联合定位。

每次发布后检查实际入口 HTML、哈希 JS/CSS 的 gzip/identity、404、`/api/auth/release` 的 `no-store`、登录与版本变化提示，再观察日志。源码配置和本地测试不能代替服务器实际响应验证；背景图体积、冷 SQL 与首字节抖动仍需分别优化。

## 特征解释模型

特征重要性、模型信息、单场 SHAP 的 GET 不再训练模型。现有 Scheduler 的 `train_feature_explanation` 在启动后3分钟及每日23:44运行，使用 `model_agent` 任务审计；同一工件路径的训练由进程锁互斥。样本/类别/特征不足记为 skipped，并保存真实原因；执行或发布错误记为 failed，不替换旧有效模型。训练参数、100场独立已结算赛前样本门槛和主预测链路不变，训练准确率仍只是拟合指标。

默认工件为项目 `.runtime/feature-explanation.json`，与现有 API/Scheduler 共享目录一致；Docker Desktop 沿用已有 runtime 卷，不新增卷或服务。可用 `FQP_FEATURE_MODEL_ARTIFACT_PATH` 指定双方相同的绝对路径；训练进程须能写父目录，API 须能读取工件（默认临时文件权限0600，适用于同一服务用户）。不要把 Scheduler 私有容器路径当成共享路径。工件存模型、特征版本/顺序、重要性和原训练时间，原子替换前验证内容摘要及原生模型宽度/类别；失败提示不会刷新旧训练时间。

首次工件尚未生成或无合格数据时，页面明确显示未就绪；正常模型预测仍独立执行。工件已就绪时 importance 一次返回排名和同版本 model_info；model-info 仅读元信息，SHAP 才按需加载相同工件。保留 `force_retrain` 查询参数的校验，但传 true 明确返回400，防止 GET 触发写入。必要时由运维运行 `.venv/bin/python -c 'from scripts.jobs.train_feature_explanation import run; print(run())'`，仍经过审计和同一进程锁。发布后需核实双方路径/权限、首次后台任务和实际接口响应，不能以本地验证代替线上验收。

SHAP 的 `base_values` 和贡献均为原始模型分数，不是概率；前端直接显示原始分数，SHAP 缺失时显示未知。`predicted_probs` 仍为原有主胜/平局/客胜概率映射。
