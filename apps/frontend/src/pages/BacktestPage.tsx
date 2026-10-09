/** Backtest Center — 回测实验室页面。
 *
 * 功能：
 *   1. 回测运行列表（历史记录）
 *   2. 新建回测表单（模型选择、时间范围、过滤器）
 *   3. 回测详情（指标仪表盘、资金曲线、模型对比）
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../core/apiClient';
import type { BacktestRun, BacktestResult, DashboardBacktestEquityItem } from '../core/types';
import { PageHeader, Card, DataTable, LoadingSpinner } from '../shared/components';
import { modelNameLabel } from '../shared/constants';
import { formatTimestamp } from '../shared/utils';
import useReadOnlyResource from '../features/command-center/useReadOnlyResource';
import ReadEvidenceStatus from './ReadEvidenceStatus';
import './BusinessEvidence.css';
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

const CURRENT_METHODOLOGY_VERSION = 3;

function methodologyVersion(config: Record<string, unknown> | null | undefined): number {
  const version = config?.methodology_version;
  return typeof version === 'number' ? version : 1;
}

// —— 组件 ——

export default function BacktestPage() {
  const fetchRuns = useCallback(async () => {
    const data = await api.backtests.list({ limit: 30 });
    if (!Array.isArray(data.runs) || data.runs.length > 30 || !Number.isSafeInteger(data.total) || data.total < data.runs.length
      || data.runs.some(r => !Number.isSafeInteger(r.id) || r.id <= 0 || typeof r.name !== 'string' || typeof r.status !== 'string')
      || new Set(data.runs.map(r => r.id)).size !== data.runs.length) throw new Error('回测列表格式不正确');
    return data;
  }, []);
  const runResource = useReadOnlyResource(fetchRuns);
  const runs = runResource.data?.runs ?? [];
  const loading = runResource.loading;
  const loadRuns = runResource.refresh;
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('');
  const [method, setMethod] = useState('');
  const [page, setPage] = useState(1);
  const filteredRuns = runs.filter(r => (!status || r.status === status)
    && (!method || (method === 'current' ? methodologyVersion(r.config) >= CURRENT_METHODOLOGY_VERSION : methodologyVersion(r.config) < CURRENT_METHODOLOGY_VERSION))
    && `${r.id} ${r.name}`.toLowerCase().includes(search.trim().toLowerCase()));
  const pageCount = Math.max(1, Math.ceil(filteredRuns.length / 10));
  const currentPage = Math.min(page, pageCount);
  const visibleRuns = filteredRuns.slice((currentPage - 1) * 10, currentPage * 10);
  const [selectedRun, setSelectedRun] = useState<number | null>(null);
  const [selectedRunRecord, setSelectedRunRecord] = useState<BacktestRun | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [detailAt, setDetailAt] = useState<number | null>(null);
  const [results, setResults] = useState<BacktestResult[]>([]);
  const [form, setForm] = useState<BacktestFormState>(DEFAULT_FORM);
  const [equityData, setEquityData] = useState<DashboardBacktestEquityItem[]>([]);
  const [equityLoading, setEquityLoading] = useState(false);
  const [equityError, setEquityError] = useState<string | null>(null);
  const [equityAt, setEquityAt] = useState<number | null>(null);
  const requestVersion = useRef(0);
  const curveVersion = useRef(0);
  const activeId = useRef<number | null>(null);
  useEffect(() => () => { requestVersion.current += 1; curveVersion.current += 1; }, []);

  const loadCurve = useCallback(async (runId: number, version: number) => {
    const curve = ++curveVersion.current;
    setEquityLoading(true);
    setEquityError(null);
    try {
      const response = await api.dashboard.backtestEquity({ run_id: runId });
      const emptyResponse = response as unknown as { empty?: boolean; empty_reason?: string };
      if (emptyResponse.empty_reason === '无法读取回测视图') throw new Error(emptyResponse.empty_reason);
      if (!response.data && emptyResponse.empty !== true) throw new Error('窗口趋势格式不正确');
      const rows = response.data?.series ?? [];
      if (!Array.isArray(rows) || rows.some(row => row.run_id !== runId || Object.values(row).some(value => typeof value === 'number' && !Number.isFinite(value)))) throw new Error('窗口趋势与所选运行不一致');
      if (version !== requestVersion.current || curve !== curveVersion.current) return;
      setEquityData(rows);
      setEquityAt(Date.now());
    } catch (failure) {
      if (version === requestVersion.current && curve === curveVersion.current) setEquityError(failure instanceof Error ? failure.message : '窗口趋势数据加载失败');
    } finally {
      if (version === requestVersion.current && curve === curveVersion.current) setEquityLoading(false);
    }
  }, []);

  const loadDetail = useCallback(async (runId: number) => {
    const version = ++requestVersion.current;
    curveVersion.current += 1;
    const changed = activeId.current !== runId;
    activeId.current = runId;
    setSelectedRun(runId);
    if (changed) {
      setSelectedRunRecord(null); setResults([]); setDetailAt(null);
      setEquityData([]); setEquityAt(null);
    }
    setDetailLoading(true); setDetailError(null); setEquityError(null); setEquityLoading(false);
    try {
      const data = await api.backtests.get(runId);
      if (data.run?.id !== runId) throw new Error('回测详情与所选运行不一致');
      if (!Array.isArray(data.results) || data.results.some(row => typeof row.model_name !== 'string'
        || Object.values(row).some(value => typeof value === 'number' && !Number.isFinite(value)))) throw new Error('回测指标格式不正确');
      if (version !== requestVersion.current) return;
      setSelectedRunRecord(data.run);
      setResults(data.results.filter(r => r.window_index === null));
      setDetailAt(Date.now());
      void loadCurve(runId, version);
    } catch (failure) {
      if (version === requestVersion.current) setDetailError(failure instanceof Error ? failure.message : '加载回测详情失败');
    } finally {
      if (version === requestVersion.current) setDetailLoading(false);
    }
  }, [loadCurve]);

  // —— 提交新建回测 ——
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setForm((f) => ({ ...f, submitting: true, error: null, success: null }));

    const body: Record<string, unknown> = {
      signal_strength: form.signalStrength,
      walk_forward: form.walkForward,
      min_model_prob: form.minModelProb.trim() === '' ? 0.35 : Number(form.minModelProb),
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
    v != null && Number.isFinite(v) ? `${(v * 100).toFixed(2)}%` : '—';
  const fmtNum = (v: number | null | undefined, decimals = 2) =>
    v != null && Number.isFinite(v) ? v.toFixed(decimals) : '—';

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

  const selectedRunIsLegacy = selectedRunRecord != null
    && methodologyVersion(selectedRunRecord.config) < CURRENT_METHODOLOGY_VERSION;

  // —— 渲染 ——
  return (
    <div className="be-page">
      <PageHeader
        title="策略验证"
        subtitle="赛前时点赔率 · 每场单一决策 · 独立比赛口径"
      />

      <ReadEvidenceStatus resource={runResource} label="刷新回测列表" note={`已获取 ${runs.length} / 最多 30 条 · 数据库共 ${runResource.data?.total ?? '—'} 条 · 筛选 ${filteredRuns.length} 条；可见时每30秒刷新`} />

      {/* 统计卡片 — staggered entrance */}
      <div className="fqp-grid-4">
        <Card entranceDelay={0}>
          <div className="fqp-stat-card">
            <div className="fqp-stat-value">{runResource.data ? runs.length : '—'}</div>
            <div className="fqp-stat-sub">已获取回测数</div>
          </div>
        </Card>
        <Card entranceDelay={80}>
          <div className="fqp-stat-card">
            <div className="fqp-stat-value">
              {runResource.data ? runs.filter((r) => r.status === 'completed').length : '—'}
            </div>
            <div className="fqp-stat-sub">已完成</div>
          </div>
        </Card>
        <Card entranceDelay={160}>
          <div className="fqp-stat-card">
            <div className="fqp-stat-value">
              {runResource.data ? runs.filter((r) => r.status === 'running').length : '—'}
            </div>
            <div className="fqp-stat-sub">运行中</div>
          </div>
        </Card>
        <Card entranceDelay={240}>
          <div className="fqp-stat-card">
            <div className="fqp-stat-value">
              {detailAt === null ? '—' : results.length}
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
              <label htmlFor="bt-model-names">模型名称（逗号分隔，留空=全部活跃）</label>
              <input id="bt-model-names"
                type="text"
                value={form.modelNames}
                onChange={(e) => setForm((f) => ({ ...f, modelNames: e.target.value }))}
                placeholder="market_baseline, maher_poisson, dixon_coles, elo_rating"
              />
            </div>
            <div className="fqp-form-group">
              <label htmlFor="bt-signal-strength">信号强度</label>
              <select id="bt-signal-strength"
                value={form.signalStrength}
                onChange={(e) => setForm((f) => ({ ...f, signalStrength: e.target.value }))}
              >
                <option value="strong">强信号（概率 &gt; 40%）</option>
                <option value="weak">弱信号（概率 30-40%）</option>
                <option value="all">全部</option>
              </select>
            </div>
          </div>

          <div className="fqp-form-row">
            <div className="fqp-form-group">
              <label htmlFor="bt-time-start">开始日期</label>
              <input id="bt-time-start"
                type="date"
                value={form.timeStart}
                onChange={(e) => setForm((f) => ({ ...f, timeStart: e.target.value }))}
              />
            </div>
            <div className="fqp-form-group">
              <label htmlFor="bt-time-end">结束日期</label>
              <input id="bt-time-end"
                type="date"
                value={form.timeEnd}
                onChange={(e) => setForm((f) => ({ ...f, timeEnd: e.target.value }))}
              />
            </div>
          </div>

          <div className="fqp-form-row">
            <div className="fqp-form-group">
              <label htmlFor="bt-odds-min">最低赔率</label>
              <input id="bt-odds-min"
                type="number" step="0.1" min="1.0"
                value={form.oddsMin}
                onChange={(e) => setForm((f) => ({ ...f, oddsMin: e.target.value }))}
                placeholder="1.5"
              />
            </div>
            <div className="fqp-form-group">
              <label htmlFor="bt-odds-max">最高赔率</label>
              <input id="bt-odds-max"
                type="number" step="0.1" min="1.0"
                value={form.oddsMax}
                onChange={(e) => setForm((f) => ({ ...f, oddsMax: e.target.value }))}
                placeholder="5.0"
              />
            </div>
            <div className="fqp-form-group">
              <label htmlFor="bt-ev-min">最低 EV</label>
              <input id="bt-ev-min"
                type="number" step="0.01"
                value={form.evMin}
                onChange={(e) => setForm((f) => ({ ...f, evMin: e.target.value }))}
                placeholder="0.02"
              />
            </div>
            <div className="fqp-form-group">
              <label htmlFor="bt-model-prob">最低模型概率</label>
              <input id="bt-model-prob"
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

      {/* Selected run owns independent detail and window evidence. */}
      {selectedRun && (
        <Card title={`回测详情 #${selectedRun}`} >
          <ReadEvidenceStatus label="刷新回测详情" resource={{ data: selectedRunRecord, loading: detailLoading, error: detailError, receivedAt: detailAt, refresh: () => loadDetail(selectedRun) }} note={`运行 #${selectedRun} · 手动读取；归档口径见下方`} />
          {detailLoading && !selectedRunRecord ? (
            <LoadingSpinner />
          ) : !selectedRunRecord ? null : results.length === 0 ? (
            <p className="fqp-muted">暂无该回测的聚合结果</p>
          ) : (
            <div>
              {selectedRunIsLegacy && (
                <div
                  role="alert"
                  style={{
                    marginBottom: 16,
                    padding: '12px 14px',
                    borderRadius: 8,
                    color: 'var(--fqp-warning)',
                    background: 'rgba(255,193,7,0.08)',
                    border: '1px solid rgba(255,193,7,0.28)',
                  }}
                >
                  旧口径结果仅供归档：可能包含赛后预测、旧资金曲线或未校准时区，不参与模型上线判断。请使用“当前 V{CURRENT_METHODOLOGY_VERSION}”口径重新回测。
                </div>
              )}

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
                  { key: 'log_loss', title: '对数损失', width: '80px', render: (_: unknown, row: BacktestResult) => fmtNum(row.log_loss, 4) },
                  { key: 'clv', title: '预测概率优势', width: '120px', render: (_: unknown, row: BacktestResult) => fmtNum(row.clv, 4) },
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

              <p>预测概率优势为模型概率减去推荐时市场概率；当前回测未采集真实收盘赔率 CLV。</p>

              {/* 模型上线门槛检查 — staggered reveal */}
              {!selectedRunIsLegacy && results.map((r, ri) => {
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

              <ReadEvidenceStatus label="刷新窗口趋势" resource={{ data: equityAt === null ? null : equityData, loading: equityLoading, error: equityError, receivedAt: equityAt, refresh: () => loadCurve(selectedRun, requestVersion.current) }} note={`仅运行 #${selectedRun} 的历史时间窗；不是逐日资金曲线`} />
              <BacktestPerformanceCharts
                results={results}
                windowRows={equityData}
                loading={equityAt === null && equityLoading}
                error={equityAt === null ? equityError : null}
              />
            </div>
          )}
        </Card>
      )}

      {/* 回测历史列表 */}
      <Card title="回测历史">
        <div className="be-toolbar">
          <label>搜索回测记录<input type="search" value={search} onChange={e => { setSearch(e.target.value); setPage(1); }} /></label>
          <label>运行状态<select value={status} onChange={e => { setStatus(e.target.value); setPage(1); }}><option value="">全部状态</option>{Array.from(new Set(['pending', 'running', 'completed', 'failed', 'cancelled', ...runs.map(r => r.status), ...(status ? [status] : [])])).map(value => <option key={value} value={value}>{statusLabel(value)}</option>)}</select></label>
          <label>回测口径<select value={method} onChange={e => { setMethod(e.target.value); setPage(1); }}><option value="">全部口径</option><option value="current">当前口径</option><option value="legacy">旧口径</option></select></label>
          <button type="button" onClick={() => { setSearch(''); setStatus(''); setMethod(''); setPage(1); }}>清空回测筛选</button>
        </div>
        <p className="be-note">筛选仅覆盖本次获取的最近30条；全局总数来自数据库计数。</p>
        {loading ? (
          <LoadingSpinner />
        ) : (
          <DataTable
            columns={[
              { key: 'id', title: 'ID', width: '60px' },
              { key: 'name', title: '名称', width: '200px' },
              {
                key: 'methodology', title: '口径', width: '90px',
                render: (_: unknown, row: BacktestRun) => (
                  methodologyVersion(row.config) >= CURRENT_METHODOLOGY_VERSION
                    ? <span className="fqp-status-ok">当前 V{CURRENT_METHODOLOGY_VERSION}</span>
                    : <span className="fqp-status-warn">旧口径</span>
                ),
              },
              {
                key: 'status', title: '状态', width: '80px',
                render: (_: unknown, row: BacktestRun) => (
                  <span className={statusClass(row.status)}>{statusLabel(row.status)}</span>
                ),
              },
              { key: 'created_at', title: '创建时间', width: '160px',
                render: (_: unknown, row: BacktestRun) =>
                  formatTimestamp(row.created_at),
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
            rows={visibleRuns}
            rowKey={row => row.id}
            selectedRowKey={selectedRun}
            loading={false}
            emptyText={runResource.error && !runResource.data ? "回测列表读取失败，请刷新" : runs.length ? "未找到符合筛选的回测，请清空筛选" : "暂无回测记录，请创建新的回测"}
          />
        )}
        <div className="be-pagination">
          <button type="button" aria-label="上一页回测" disabled={currentPage === 1} onClick={() => setPage(currentPage - 1)}>上一页</button>
          <span>{currentPage} / {pageCount} 页</span>
          <button type="button" aria-label="下一页回测" disabled={currentPage === pageCount} onClick={() => setPage(currentPage + 1)}>下一页</button>
        </div>
      </Card>
    </div>
  );
}
