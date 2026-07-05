import { useEffect, useState } from 'react';
import { api } from '../core/apiClient';
import type { Prediction, EvalModelSummary } from '../core/types';
import { ApiError } from '../core/types';
import PageHeader from '../shared/components/PageHeader';
import Card from '../shared/components/Card';
import DataTable, { type Column } from '../shared/components/DataTable';
import ErrorState from '../shared/components/ErrorState';
import DisclaimerBanner from '../shared/components/DisclaimerBanner';
import { playTypeLabel } from '../shared/constants';

export default function ModelsPage() {
  const [predictions, setPredictions] = useState<Prediction[]>([]);
  const [evalModels, setEvalModels] = useState<EvalModelSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [evalLoading, setEvalLoading] = useState(true);
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
    { key: 'model_name', title: '模型' },
    {
      key: 'home_team',
      title: '主队',
      width: '120px',
    },
    {
      key: 'away_team',
      title: '客队',
      width: '120px',
    },
    { key: 'play_type', title: '玩法', width: '80px', render: (v) => playTypeLabel(String(v)) },
    {
      key: 'option_code',
      title: '选项',
      width: '60px',
      render: (v) => <span className="fqp-mono">{String(v)}</span>,
    },
    {
      key: 'model_probability',
      title: '模型概率',
      render: (v) => {
        const val = v as number | null;
        return val !== null ? `${(val * 100).toFixed(1)}%` : '—';
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
      <PageHeader title="模型实验室" />
      <DisclaimerBanner
        text="模型评估数据仅用于学术研究和自我复盘，不构成投注建议。"
        type="page"
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
            <div className="fqp-stat-sub">{modelNames.join(', ') || '无'}</div>
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
                  {bestBrier?.model_name}（{bestBrier?.n} 条）
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
                  已结算比赛 × 模型预测
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
                      <strong>{m.model_name}</strong>
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
