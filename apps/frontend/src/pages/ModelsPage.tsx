import { useEffect, useState } from 'react';
import { api } from '../core/apiClient';
import type { Prediction, EvalModelSummary, ModelPerformanceHistory } from '../core/types';
import { ApiError } from '../core/types';
import PageHeader from '../shared/components/PageHeader';
import Card from '../shared/components/Card';
import DataTable, { type Column } from '../shared/components/DataTable';
import ErrorState from '../shared/components/ErrorState';
import { modelNameLabel, optionLabel, playTypeLabel } from '../shared/constants';
import TeamName from '../shared/components/TeamName';
import ModelPerformanceCharts from '../visualization/ModelPerformanceCharts';

export default function ModelsPage() {
  const [predictions, setPredictions] = useState<Prediction[]>([]);
  const [evalModels, setEvalModels] = useState<EvalModelSummary[]>([]);
  const [performanceHistory, setPerformanceHistory] = useState<ModelPerformanceHistory>({
    status: 'ok',
    metric: 'rolling_hit_rate',
    window: 20,
    points: [],
  });
  const [loading, setLoading] = useState(true);
  const [evalLoading, setEvalLoading] = useState(true);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.predictions({ limit: 200 })
      .then((res) => {
        setPredictions(res.predictions);
        setLoading(false);
      })
      .catch((e) => {
        setError(e instanceof ApiError ? e.message : '加载失败');
        setLoading(false);
      });
  }, []);

  useEffect(() => {
    api.analysis.performanceHistory({ window: 20, days: 365 })
      .then((res) => {
        setPerformanceHistory(res);
        setHistoryLoading(false);
      })
      .catch((e) => {
        setHistoryError(e instanceof ApiError ? e.message : '加载模型曲线失败');
        setHistoryLoading(false);
      });
  }, []);

  // Fetch real evaluation data
  useEffect(() => {
    api.analysis.evaluationSummary()
      .then((res) => {
        if (res.status === 'ok') {
          setEvalModels(res.models);
        }
        setEvalLoading(false);
      })
      .catch(() => {
        setEvalLoading(false);
      });
  }, []);

  // Stats
  const modelNames = [...new Set(predictions.map((p) => p.model_name))];
  const totalCount = predictions.length;
  const latestTime = predictions.length > 0 ? predictions[0].predict_time : null;
  const positiveEvCount = predictions.filter((p) => (p.ev ?? 0) > 0).length;
  const avgConfidence =
    predictions.length > 0
      ? predictions.reduce((s, p) => s + (p.confidence ?? 0), 0) / predictions.length
      : 0;

  // Find best model by Brier
  const bestBrier = evalModels.length > 0 ? evalModels[0] : null;
  const overallBrier =
    evalModels.length > 0
      ? evalModels.reduce((s, m) => s + m.avg_brier, 0) / evalModels.length
      : null;

  const columns: Column<Prediction>[] = [
    { key: 'model_name', title: '模型', render: (v) => modelNameLabel(String(v)) },
    {
      key: 'home_team',
      title: '主队',
      width: '120px',
      render: (value) => <TeamName name={String(value)} />,
    },
    {
      key: 'away_team',
      title: '客队',
      width: '120px',
      render: (value) => <TeamName name={String(value)} />,
    },
    { key: 'play_type', title: '玩法', width: '80px', render: (v) => playTypeLabel(String(v)) },
    {
      key: 'option_code',
      title: '选项',
      width: '60px',
      render: (v, row) => optionLabel(row.play_type, String(v)),
    },
    {
      key: 'raw_model_probability',
      title: '原始概率',
      render: (v) => {
        const val = v as number | null;
        return val != null ? `${(val * 100).toFixed(1)}%` : '—';
      },
    },
    {
      key: 'model_probability',
      title: '最终概率',
      render: (v, row) => {
        const val = v as number | null;
        if (val == null) return '—';
        return (
          <span>
            {(val * 100).toFixed(1)}%
            {row.feature_adjusted && (
              <small style={{ display: 'block', color: 'var(--fqp-success)' }}>特征已修正</small>
            )}
          </span>
        );
      },
    },
    {
      key: 'market_probability',
      title: '市场概率',
      render: (v) => {
        const val = v as number | null;
        return val !== null ? `${(val * 100).toFixed(1)}%` : '—';
      },
    },
    {
      key: 'ev',
      title: 'EV',
      render: (v) => {
        const val = v as number | null;
        if (val === null) return '—';
        const color = val > 0 ? 'var(--fqp-success)' : val < 0 ? 'var(--fqp-red-neon)' : 'var(--fqp-text-muted)';
        return <span className="fqp-mono" style={{ color }}>{val >= 0 ? '+' : ''}{val.toFixed(4)}</span>;
      },
    },
    {
      key: 'confidence',
      title: '置信度',
      render: (v) => {
        const val = v as number | null;
        return val !== null ? `${((val as number) * 100).toFixed(0)}%` : '—';
      },
    },
    {
      key: 'predict_time',
      title: '预测时间',
      render: (v) => String(v).replace('T', ' ').slice(0, 19),
    },
  ];

  return (
    <div>
      <PageHeader
        title="模型表现"
        subtitle="按独立比赛评估模型，并区分基础模型概率与特征修正后的最终概率"
      />

      {/* Stat cards — staggered entrance */}
      <div className="fqp-grid-4" style={{ marginBottom: '24px' }}>
        <Card title="预测总数" entranceDelay={0}>
          <div className="fqp-stat-card" style={{ padding: 0 }}>
            <div className="fqp-stat-value">{totalCount}</div>
            <div className="fqp-stat-sub">条预测记录</div>
          </div>
        </Card>
        <Card title="模型版本" entranceDelay={80}>
          <div className="fqp-stat-card" style={{ padding: 0 }}>
            <div className="fqp-stat-value">{modelNames.length}</div>
            <div className="fqp-stat-sub">
              {modelNames.map(modelNameLabel).join('、') || '无'}
            </div>
          </div>
        </Card>
        <Card title="正EV预测" entranceDelay={160}>
          <div className="fqp-stat-card" style={{ padding: 0 }}>
            <div className="fqp-stat-value">{positiveEvCount}</div>
            <div className="fqp-stat-sub">
              {totalCount > 0 ? `${((positiveEvCount / totalCount) * 100).toFixed(0)}%` : '—'}
            </div>
          </div>
        </Card>
        <Card title="平均置信度" entranceDelay={240}>
          <div className="fqp-stat-card" style={{ padding: 0 }}>
            <div className="fqp-stat-value">{Math.round(avgConfidence * 100)}%</div>
            <div className="fqp-stat-sub">
              {latestTime ? `最新: ${latestTime.replace('T', ' ').slice(0, 19)}` : '无数据'}
            </div>
          </div>
        </Card>
      </div>

      <ModelPerformanceCharts
        points={performanceHistory.points}
        window={performanceHistory.window}
        loading={historyLoading}
        error={historyError}
      />

      {/* Real evaluation metrics */}
      <Card title="评估指标" style={{ marginBottom: '20px' }}>
        {evalLoading ? (
          <div style={{ color: 'var(--fqp-text-muted)', padding: '16px 0' }}>加载评估数据...</div>
        ) : evalModels.length === 0 ? (
          <div style={{ display: 'flex', gap: '32px', flexWrap: 'wrap' }}>
            {[
              { label: 'Brier Score', value: '—', note: '需要结算数据' },
              { label: 'Log Loss', value: '—', note: '需要结算数据' },
              { label: 'ROI', value: '—', note: '需要回测数据' },
              { label: '最大回撤', value: '—', note: '需要回测数据' },
            ].map((m) => (
              <div key={m.label}>
                <div className="fqp-label">{m.label}</div>
                <div className="fqp-mono" style={{ fontSize: '18px', fontWeight: 700 }}>
                  {m.value}
                </div>
                <div style={{ fontSize: '11px', color: 'var(--fqp-text-muted)' }}>{m.note}</div>
              </div>
            ))}
          </div>
        ) : (
          <>
            <div style={{ display: 'flex', gap: '32px', flexWrap: 'wrap', marginBottom: '16px' }}>
              <div>
                <div className="fqp-label">最佳 Brier Score</div>
                <div className="fqp-mono" style={{ fontSize: '18px', fontWeight: 700, color: 'var(--fqp-success)' }}>
                  {bestBrier?.avg_brier.toFixed(4)}
                </div>
                <div style={{ fontSize: '11px', color: 'var(--fqp-text-muted)' }}>
                  {bestBrier ? modelNameLabel(bestBrier.model_name) : '—'}（{bestBrier?.n ?? 0} 场）
                </div>
              </div>
              <div>
                <div className="fqp-label">平均 Brier Score</div>
                <div className="fqp-mono" style={{ fontSize: '18px', fontWeight: 700 }}>
                  {overallBrier?.toFixed(4)}
                </div>
                <div style={{ fontSize: '11px', color: 'var(--fqp-text-muted)' }}>
                  {evalModels.length} 个模型
                </div>
              </div>
              <div>
                <div className="fqp-label">Log Loss (最优)</div>
                <div className="fqp-mono" style={{ fontSize: '18px', fontWeight: 700, color: 'var(--fqp-success)' }}>
                  {evalModels.length > 0
                    ? evalModels.reduce((best, m) => m.avg_logloss < best ? m.avg_logloss : best, Infinity).toFixed(4)
                    : '—'}
                </div>
                <div style={{ fontSize: '11px', color: 'var(--fqp-text-muted)' }}>
                  越低越好
                </div>
              </div>
              <div>
                <div className="fqp-label">有效评估数</div>
                <div className="fqp-mono" style={{ fontSize: '18px', fontWeight: 700 }}>
                  {evalModels.reduce((s, m) => s + m.n, 0)}
                </div>
                <div style={{ fontSize: '11px', color: 'var(--fqp-text-muted)' }}>
                  独立已结算比赛 × 模型
                </div>
              </div>
            </div>

            {/* Per-model metrics table */}
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--fqp-border)' }}>
                  <th style={thStyle}>模型</th>
                  <th style={thStyle}>评估数</th>
                  <th style={thStyle}>Brier ↓</th>
                  <th style={thStyle}>LogLoss ↓</th>
                  <th style={thStyle}>RPS ↓</th>
                  <th style={thStyle}>CLV</th>
                </tr>
              </thead>
              <tbody>
                {evalModels.map((m) => (
                  <tr key={m.model_name} style={{ borderBottom: '1px solid var(--fqp-border-light)' }}>
                    <td style={tdStyle}>
                      <strong>{modelNameLabel(m.model_name)}</strong>
                    </td>
                    <td style={{ ...tdStyle, textAlign: 'center' }} className="fqp-mono">{m.n}</td>
                    <td style={{ ...tdStyle, textAlign: 'right' }} className="fqp-mono">{m.avg_brier.toFixed(4)}</td>
                    <td style={{ ...tdStyle, textAlign: 'right' }} className="fqp-mono">{m.avg_logloss.toFixed(4)}</td>
                    <td style={{ ...tdStyle, textAlign: 'right' }} className="fqp-mono">{m.avg_rps.toFixed(4)}</td>
                    <td style={{ ...tdStyle, textAlign: 'right' }} className="fqp-mono">
                      <span style={{ color: m.avg_clv > 0 ? 'var(--fqp-success)' : 'var(--fqp-red-neon)' }}>
                        {m.avg_clv >= 0 ? '+' : ''}{m.avg_clv.toFixed(4)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </Card>

      {/* Predictions table */}
      {error ? (
        <ErrorState message={error} onRetry={() => window.location.reload()} />
      ) : (
        <Card style={{ padding: 0, overflow: 'hidden' }}>
          <DataTable
            columns={columns}
            rows={predictions}
            loading={loading}
            emptyText="暂无模型预测数据，请先运行模型计算任务"
            rowKey={(r) => String(r.id)}
          />
        </Card>
      )}
    </div>
  );
}

const thStyle: React.CSSProperties = {
  padding: '8px 12px',
  textAlign: 'left',
  fontWeight: 600,
  fontSize: '12px',
  color: 'var(--fqp-text-muted)',
  textTransform: 'uppercase',
};

const tdStyle: React.CSSProperties = {
  padding: '8px 12px',
};
