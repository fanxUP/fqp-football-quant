import { useEffect, useState } from 'react';
import { api } from '../core/apiClient';
import type { Prediction } from '../core/types';
import { ApiError } from '../core/types';
import PageHeader from '../shared/components/PageHeader';
import Card from '../shared/components/Card';
import DataTable, { type Column } from '../shared/components/DataTable';
import ErrorState from '../shared/components/ErrorState';

export default function ModelsPage() {
  const [predictions, setPredictions] = useState<Prediction[]>([]);
  const [loading, setLoading] = useState(true);
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

  // Stats
  const modelNames = [...new Set(predictions.map((p) => p.model_name))];
  const totalCount = predictions.length;
  const latestTime = predictions.length > 0 ? predictions[0].predict_time : null;
  const positiveEvCount = predictions.filter((p) => (p.ev ?? 0) > 0).length;
  const avgConfidence =
    predictions.length > 0
      ? predictions.reduce((s, p) => s + (p.confidence ?? 0), 0) / predictions.length
      : 0;

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
    { key: 'play_type', title: '玩法', width: '80px' },
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

      {/* Stat cards */}
      <div className="fqp-grid-4" style={{ marginBottom: '24px' }}>
        <Card title="预测总数">
          <div className="fqp-stat-card" style={{ padding: 0 }}>
            <div className="fqp-stat-value">{totalCount}</div>
            <div className="fqp-stat-sub">条预测记录</div>
          </div>
        </Card>
        <Card title="模型版本">
          <div className="fqp-stat-card" style={{ padding: 0 }}>
            <div className="fqp-stat-value">{modelNames.length}</div>
            <div className="fqp-stat-sub">{modelNames.join(', ') || '无'}</div>
          </div>
        </Card>
        <Card title="正EV预测">
          <div className="fqp-stat-card" style={{ padding: 0 }}>
            <div className="fqp-stat-value">{positiveEvCount}</div>
            <div className="fqp-stat-sub">
              {totalCount > 0 ? `${((positiveEvCount / totalCount) * 100).toFixed(0)}%` : '—'}
            </div>
          </div>
        </Card>
        <Card title="平均置信度">
          <div className="fqp-stat-card" style={{ padding: 0 }}>
            <div className="fqp-stat-value">{Math.round(avgConfidence * 100)}%</div>
            <div className="fqp-stat-sub">
              {latestTime ? `最新: ${latestTime.replace('T', ' ').slice(0, 19)}` : '无数据'}
            </div>
          </div>
        </Card>
      </div>

      {/* Metrics placeholders */}
      <Card title="评估指标" style={{ marginBottom: '20px' }}>
        <div style={{ display: 'flex', gap: '32px', flexWrap: 'wrap' }}>
          {[
            { label: 'Brier Score', value: '—', note: '需要结算数据' },
            { label: 'Log Loss', value: '—', note: '需要结算数据' },
            { label: 'ROI', value: '—', note: '需要结算数据' },
            { label: '最大回撤', value: '—', note: '需要结算数据' },
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
