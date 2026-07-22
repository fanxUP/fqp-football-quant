# 06_API接口设计

完整接口草案见 api/openapi.yaml。

## 核心接口

### 官方赛程
- GET /api/v1/official/matches?date=YYYY-MM-DD
- GET /api/v1/official/matches/{match_id}
- GET /api/v1/official/matches/{match_id}/odds-snapshots

### 模型预测
- POST /api/v1/models/predict/date/{date}
- GET /api/v1/models/predictions?match_id=xxx
- GET /api/v1/models/versions

### 推荐引擎
- POST /api/v1/recommendations/generate?date=YYYY-MM-DD
- GET /api/v1/recommendations/daily?date=YYYY-MM-DD
- POST /api/v1/recommendations/{ticket_id}/invalidate

### 实票
- POST /api/v1/real-tickets/upload
- POST /api/v1/real-tickets/{id}/confirm
- GET /api/v1/real-tickets?date=YYYY-MM-DD
- POST /api/v1/real-tickets/{id}/settle

### 复盘
- GET /api/v1/reviews/daily?date=YYYY-MM-DD
- GET /api/v1/reviews/weekly?week_start=YYYY-MM-DD
- GET /api/v1/reviews/monthly?month=YYYY-MM

### 回测
- POST /api/v1/backtests
- GET /api/v1/backtests/{id}

### 传统足彩
- GET /api/v1/pool/issues
- POST /api/v1/pool/issues/{id}/generate-combinations

### 运行时模块与面板
- GET /api/v1/modules
- PATCH /api/v1/modules/{module_code}/status
- GET /api/v1/ui/panels
