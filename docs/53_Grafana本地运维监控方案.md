# Grafana 本地运维监控方案

> FQP 系统监控层 — 独立于主业务前端，仅用于运维状态监控。

## 架构定位

Grafana **不替代**业务 Dashboard。业务 Dashboard 由 React + ECharts 在前端实现。
Grafana 只负责以下运维场景：

- Docker 容器是否正常运行
- API / 数据库 / Redis 是否可连接
- 数据采集任务成功率
- 赔率快照过期告警
- 模型任务异常
- 错误日志趋势

## 访问地址

```text
http://localhost:3001
```

默认登录：`admin` / `admin`（首次强制改密）

## 数据源配置

### PostgreSQL（业务数据源）

进入 Configuration → Data Sources → Add data source → PostgreSQL：

| 参数 | 值 |
|------|-----|
| Host | `postgres:5432` |
| Database | `fqp` |
| User | `fqp` |
| Password | `fqp_local_password` |
| TLS/SSL | disable |
| Version | 自动检测 |

### Prometheus（可选，需额外配置）

如需更细粒度的指标监控，后期可加入 Prometheus：

1. 在 `docker-compose.local.yml` 新增 `prometheus` 服务
2. 在 API 中暴露 `/metrics` 端点（使用 `prometheus_client`）
3. Grafana 添加 Prometheus 数据源

## 推荐 Dashboard

### 1. FQP System Overview

关键面板：

| 面板 | 数据源 | 说明 |
|------|--------|------|
| API Health | PostgreSQL | `SELECT status FROM v_dashboard_today_summary` |
| 今日比赛数 | PostgreSQL | `SELECT match_count FROM v_dashboard_today_summary` |
| 待开奖票数 | PostgreSQL | `SELECT pending_settlement_count FROM v_dashboard_today_summary` |
| 最近任务状态 | PostgreSQL | pipeline/jobs 表查询 |

### 2. FQP API Monitor

- API 响应时间（如有 Prometheus）
- 请求错误率
- 活跃连接数

### 3. FQP Scheduler Monitor

- 定时任务执行状态
- 最近失败任务
- 采集延迟

## 告警配置

可在 Grafana 中设置以下告警：

- API 健康检查失败 → `Alert`
- 待开奖票单数超过 100 → `Warning`
- 磁盘使用率超过 85% → `Warning`
- 数据采集失败超过 3 次 → `Alert`

## 注意事项

1. Grafana 不使用固定版本 tag（`grafana/grafana` = latest）
2. 端口 3001，不与前端 3000 冲突
3. 不在 Grafana 中实现投注推荐页面
4. 不在 Grafana 中展示核心模型逻辑
5. 数据卷 `grafana_data` 持久化配置和 Dashboard
