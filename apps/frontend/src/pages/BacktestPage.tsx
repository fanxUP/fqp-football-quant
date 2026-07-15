/** Backtest Center — 回测实验室页面。
 *
 * 功能：
 *   1. 回测运行列表（历史记录）
 *   2. 新建回测表单（模型选择、时间范围、过滤器）
 *   3. 回测详情（指标仪表盘、资金曲线、模型对比）
 */

import React, { useCallback, useEffect, useState } from 'react';
import { api } from '../core/apiClient';
import type { BacktestRun, BacktestResult, DashboardBacktestEquityItem } from '../core/types';
import { PageHeader, Card, DataTable, ErrorState, LoadingSpinner } from '../shared/components';
import { modelNameLabel } from '../shared/constants';
import BacktestPerformanceCharts from '../visualization/backtest/BacktestPerformanceCharts';

// —— 类型 ——

interface BacktestFormState {
  modelNames: string;
  timeStart: string;
  timeEnd: string;
  oddsMin: string;
  oddsMax: string;
  evMin: string;
  minModelProb: string;
  signalStrength: string;
  walkForward: boolean;
  submitting: boolean;
  error: string | null;
  success: string | null;
}

const DEFAULT_FORM: BacktestFormState = {
  modelNames: '',
  timeStart: '',
  timeEnd: '',
  oddsMin: '',
  oddsMax: '',
  evMin: '',
  minModelProb: '0.35',
  signalStrength: 'strong',
  walkForward: true,
  submitting: false,
  error: null,
  success: null,
};

// —— 组件 ——

export default function BacktestPage() {
  const [runs, setRuns] = useState<BacktestRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedRun, setSelectedRun] = useState<number | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [results, setResults] = useState<BacktestResult[]>([]);
  const [form, setForm] = useState<BacktestFormState>(DEFAULT_FORM);
  const [equityData, setEquityData] = useState<DashboardBacktestEquityItem[]>([]);
  const [equityLoading, setEquityLoading] = useState(false);
  const [equityError, setEquityError] = useState<string | null>(null);

  // —— 加载回测列表 ——
  const loadRuns = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.backtests.list({ limit: 30 });
      setRuns(data.runs);
    } catch (e) {
      setError((e as Error).message || '加载回测列表失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadRuns();
  }, [loadRuns]);

  // —— 加载回测详情 ——
  const loadDetail = useCallback(async (runId: number) => {
    setSelectedRun(runId);
    setDetailLoading(true);
    setEquityData([]);
    setEquityError(null);
    try {
      const data = await api.backtests.get(runId);
      // 只显示聚合结果（window_index IS NULL）
      setResults(data.results.filter((r) => r.window_index === null));

      // Also load equity curve data for charts
      setEquityLoading(true);
      api.dashboard.backtestEquity({ run_id: runId })
        .then((res) => {
          const series = res.data?.series || [];
          setEquityData(series as DashboardBacktestEquityItem[]);
        })
        .catch((equityFailure) => {
          setEquityError((equityFailure as Error).message || '窗口趋势数据加载失败');
        })
        .finally(() => setEquityLoading(false));
    } catch (e) {
      setError((e as Error).message || '加载回测详情失败');
    } finally {
      setDetailLoading(false);
    }
  }, []);

  // —— 提交新建回测 ——
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setForm((f) => ({ ...f, submitting: true, error: null, success: null }));

    const body: Record<string, unknown> = {
      signal_strength: form.signalStrength,
      walk_forward: form.walkForward,
      min_model_prob: parseFloat(form.minModelProb) || 0.35,
    };

    if (form.modelNames.trim()) {
      body.model_names = form.modelNames.split(',').map((s) => s.trim()).filter(Boolean);
    }
    if (form.timeStart) body.time_start = form.timeStart;
    if (form.timeEnd) body.time_end = form.timeEnd;
    if (form.oddsMin) body.odds_min = parseFloat(form.oddsMin);
    if (form.oddsMax) body.odds_max = parseFloat(form.oddsMax);
    if (form.evMin) body.ev_min = parseFloat(form.evMin);

    try {
      const result = await api.backtests.create(body);
      if (result.run_id) {
        setForm((f) => ({ ...f, submitting: false, success: `回测已提交 (ID: ${result.run_id})` }));
        await loadRuns();
        if (result.run_id) {
          await loadDetail(result.run_id);
        }
      } else {
        setForm((f) => ({ ...f, submitting: false, success: '回测完成' }));
      }
    } catch (err) {
      setForm((f) => ({
        ...f,
        submitting: false,
        error: (err as Error).message || '提交失败',
      }));
    }
  };

  // —— 指标渲染 ——
  const fmtPct = (v: number | null | undefined) =>
    v != null ? `${(v * 100).toFixed(2)}%` : '—';
  const fmtNum = (v: number | null | undefined, decimals = 2) =>
    v != null ? v.toFixed(decimals) : '—';

  const statusLabel = (s: string) => {
    const map: Record<string, string> = {
      pending: '等待中', running: '运行中', completed: '已完成',
      failed: '失败', cancelled: '已取消',
    };
    return map[s] || s;
  };

  const statusClass = (s: string) => {
    if (s === 'completed') return 'fqp-status-ok';
    if (s === 'running') return 'fqp-status-warn';
    if (s === 'failed') return 'fqp-status-err';
    return '';
  };

  // —— 渲染 ——
  return (
    <div>
      <PageHeader
        title="策略验证"
        subtitle="赛前时点赔率 · 每场单一决策 · 独立比赛口径"
      />

      {error && <ErrorState message={error} onRetry={loadRuns} />}

      {/* 统计卡片 — staggered entrance */}
      <div className="fqp-grid-4">
        <Card entranceDelay={0}>
          <div className="fqp-stat-card">
            <div className="fqp-stat-value">{runs.length}</div>
            <div className="fqp-stat-sub">回测总数</div>
          </div>
        </Card>
        <Card entranceDelay={80}>
          <div className="fqp-stat-card">
            <div className="fqp-stat-value">
              {runs.filter((r) => r.status === 'completed').length}
            </div>
            <div className="fqp-stat-sub">已完成</div>
          </div>
        </Card>
        <Card entranceDelay={160}>
          <div className="fqp-stat-card">
            <div className="fqp-stat-value">
              {runs.filter((r) => r.status === 'running').length}
            </div>
            <div className="fqp-stat-sub">运行中</div>
          </div>
        </Card>
        <Card entranceDelay={240}>
          <div className="fqp-stat-card">
            <div className="fqp-stat-value">
              {results.length}
            </div>
            <div className="fqp-stat-sub">当前查看模型数</div>
          </div>
        </Card>
      </div>

      {/* 新建回测表单 — staggered sections */}
      <Card title="新建回测" entranceDelay={300}>
        <form onSubmit={handleSubmit} className="fqp-form">
          <div className="fqp-form-row">
            <div className="fqp-form-group">
              <label>模型名称（逗号分隔，留空=全部活跃）</label>
              <input
                type="text"
                value={form.modelNames}
                onChange={(e) => setForm((f) => ({ ...f, modelNames: e.target.value }))}
                placeholder="market_baseline, maher_poisson, dixon_coles, elo_rating"
              />
            </div>
            <div className="fqp-form-group">
              <label>信号强度</label>
              <select
                value={form.signalStrength}
                onChange={(e) => setForm((f) => ({ ...f, signalStrength: e.target.value }))}
              >
                <option value="strong">Strong（概率 &gt; 40%）</option>
                <option value="weak">Weak（概率 30-40%）</option>
                <option value="all">全部</option>
              </select>
            </div>
          </div>

          <div className="fqp-form-row">
            <div className="fqp-form-group">
              <label>开始日期</label>
              <input
                type="date"
                value={form.timeStart}
                onChange={(e) => setForm((f) => ({ ...f, timeStart: e.target.value }))}
              />
            </div>
            <div className="fqp-form-group">
              <label>结束日期</label>
              <input
                type="date"
                value={form.timeEnd}
                onChange={(e) => setForm((f) => ({ ...f, timeEnd: e.target.value }))}
              />
            </div>
          </div>

          <div className="fqp-form-row">
            <div className="fqp-form-group">
              <label>最低赔率</label>
              <input
                type="number" step="0.1" min="1.0"
                value={form.oddsMin}
                onChange={(e) => setForm((f) => ({ ...f, oddsMin: e.target.value }))}
                placeholder="1.5"
              />
            </div>
            <div className="fqp-form-group">
              <label>最高赔率</label>
              <input
                type="number" step="0.1" min="1.0"
                value={form.oddsMax}
                onChange={(e) => setForm((f) => ({ ...f, oddsMax: e.target.value }))}
                placeholder="5.0"
              />
            </div>
            <div className="fqp-form-group">
              <label>最低 EV</label>
              <input
                type="number" step="0.01"
                value={form.evMin}
                onChange={(e) => setForm((f) => ({ ...f, evMin: e.target.value }))}
                placeholder="0.02"
              />
            </div>
            <div className="fqp-form-group">
              <label>最低模型概率</label>
              <input
                type="number" step="0.01" min="0" max="1"
                value={form.minModelProb}
                onChange={(e) => setForm((f) => ({ ...f, minModelProb: e.target.value }))}
              />
            </div>
          </div>

          <div className="fqp-form-row">
            <div className="fqp-form-group">
              <label>
                <input
                  type="checkbox"
                  checked={form.walkForward}
                  onChange={(e) => setForm((f) => ({ ...f, walkForward: e.target.checked }))}
                />{' '}
                滚动时间窗（不重训模型）
              </label>
              <div className="fqp-muted" style={{ marginTop: '6px', fontSize: '12px' }}>
                仅验证已经落库的历史预测，不会在每个时间窗内重新训练模型。
              </div>
            </div>
          </div>

          <button type="submit" className="fqp-btn fqp-btn-primary" disabled={form.submitting}>
            {form.submitting ? '运行中...' : '开始回测'}
          </button>

          {form.error && <p className="fqp-error-msg">{form.error}</p>}
          {form.success && <p className="fqp-success-msg">{form.success}</p>}
        </form>
      </Card>

      {/* 回测详情 — slide up reveal */}
      {selectedRun && (
        <Card title={`回测详情 #${selectedRun}`} style={{ animation: 'fqpSlideUpBounce 0.5s ease both' }}>
          {detailLoading ? (
            <LoadingSpinner />
          ) : results.length === 0 ? (
            <p className="fqp-muted">暂无该回测的聚合结果</p>
          ) : (
            <div>
              {/* 指标表格 */}
              <DataTable
                columns={[
                  {
                    key: 'model_name', title: '模型', width: '190px',
                    render: (_: unknown, row: BacktestResult) => modelNameLabel(row.model_name),
                  },
                  { key: 'n_bets', title: '投注数', width: '80px' },
                  { key: 'n_wins', title: '命中', width: '80px' },
                  {
                    key: 'hit_rate', title: '命中率', width: '80px',
                    render: (_: unknown, row: BacktestResult) => fmtPct(row.hit_rate),
                  },
                  {
                    key: 'roi', title: 'ROI', width: '80px',
                    render: (_: unknown, row: BacktestResult) => (
                      <span style={{ color: (row.roi ?? 0) >= 0 ? '#10b981' : '#ef4444' }}>
                        {fmtPct(row.roi)}
                      </span>
                    ),
                  },
                  {
                    key: 'total_profit', title: '总盈利', width: '90px',
                    render: (_: unknown, row: BacktestResult) => (
                      <span style={{ color: row.total_profit >= 0 ? '#10b981' : '#ef4444' }}>
                        {fmtNum(row.total_profit)}
                      </span>
                    ),
                  },
                  { key: 'avg_odds', title: '均赔', width: '70px', render: (_: unknown, row: BacktestResult) => fmtNum(row.avg_odds) },
                  { key: 'brier_score', title: 'Brier', width: '80px', render: (_: unknown, row: BacktestResult) => fmtNum(row.brier_score, 4) },
                  { key: 'log_loss', title: 'LogLoss', width: '80px', render: (_: unknown, row: BacktestResult) => fmtNum(row.log_loss, 4) },
                  { key: 'clv', title: 'CLV', width: '80px', render: (_: unknown, row: BacktestResult) => fmtNum(row.clv, 4) },
                  {
                    key: 'max_drawdown_pct', title: '最大回撤', width: '90px',
                    render: (_: unknown, row: BacktestResult) => (
                      <span style={{ color: '#ef4444' }}>{fmtNum(row.max_drawdown_pct, 1)}%</span>
                    ),
                  },
                  {
                    key: 'longest_losing_streak', title: '最长连亏', width: '80px',
                  },
                  { key: 'sharpe_ratio', title: 'Sharpe', width: '80px', render: (_: unknown, row: BacktestResult) => fmtNum(row.sharpe_ratio) },
                  {
                    key: 'profit_factor', title: '盈利因子', width: '90px',
                    render: (_: unknown, row: BacktestResult) => fmtNum(row.profit_factor),
                  },
                ]}
                rows={results}
                loading={false}
                emptyText="暂无回测结果"
              />

              {/* 模型上线门槛检查 — staggered reveal */}
              {results.map((r, ri) => {
                const checks = {
                  '样本量 ≥ 1000': r.n_bets >= 1000,
                  'ROI > 0': (r.roi ?? -1) > 0,
                  '最大回撤 < 30%': (r.max_drawdown_pct ?? 100) < 30,
                  '命中率 > 30%': (r.hit_rate ?? 0) > 0.30,
                };
                const allPass = Object.values(checks).every(Boolean);
                return (
                  <div
                    key={r.model_name}
                    style={{
                      marginTop: 16,
                      padding: 12,
                      background: allPass ? 'rgba(0,255,136,0.06)' : 'rgba(255,193,7,0.06)',
                      borderRadius: 8,
                      border: `1px solid ${allPass ? 'rgba(0,255,136,0.2)' : 'rgba(255,193,7,0.2)'}`,
                      animation: `fqpSlideUpBounce 0.4s ease both`,
                      animationDelay: `${ri * 100}ms`,
                    }}
                  >
                    <strong>{modelNameLabel(r.model_name)}</strong>
                    {' — '}
                    <span style={{ color: allPass ? 'var(--fqp-success)' : 'var(--fqp-warning)' }}>
                      {allPass ? '✅ 满足上线门槛' : '⚠️ 未完全满足上线门槛'}
                    </span>
                    <div style={{ marginTop: 8, display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                      {Object.entries(checks).map(([label, pass], ci) => (
                        <span
                          key={label}
                          style={{
                            fontSize: 13,
                            color: pass ? 'var(--fqp-success)' : 'var(--fqp-red-neon)',
                            animation: `fqpBadgePop 0.3s ease both`,
                            animationDelay: `${ri * 100 + ci * 60}ms`,
                          }}
                        >
                          {pass ? '✅' : '❌'} {label}
                        </span>
                      ))}
                    </div>
                  </div>
                );
              })}

              <BacktestPerformanceCharts
                results={results}
                windowRows={equityData}
                loading={equityLoading}
                error={equityError}
              />
            </div>
          )}
        </Card>
      )}

      {/* 回测历史列表 */}
      <Card title="回测历史">
        {loading ? (
          <LoadingSpinner />
        ) : (
          <DataTable
            columns={[
              { key: 'id', title: 'ID', width: '60px' },
              { key: 'name', title: '名称', width: '200px' },
              {
                key: 'status', title: '状态', width: '80px',
                render: (_: unknown, row: BacktestRun) => (
                  <span className={statusClass(row.status)}>{statusLabel(row.status)}</span>
                ),
              },
              { key: 'created_at', title: '创建时间', width: '160px',
                render: (_: unknown, row: BacktestRun) =>
                  row.created_at ? new Date(row.created_at).toLocaleString('zh-CN') : '—',
              },
              {
                key: 'actions', title: '操作', width: '80px',
                render: (_: unknown, row: BacktestRun) => (
                  <button
                    className="fqp-btn fqp-btn-sm"
                    onClick={() => loadDetail(row.id)}
                  >
                    查看
                  </button>
                ),
              },
            ]}
            rows={runs}
            loading={false}
            emptyText="暂无回测记录，请创建新的回测"
          />
        )}
      </Card>
    </div>
  );
}
