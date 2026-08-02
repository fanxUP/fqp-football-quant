import { useEffect, useState } from 'react';
import { api } from '../core/apiClient';
import type { FeatureSnapshot, Prediction } from '../core/types';
import { ApiError } from '../core/types';
import PageHeader from '../shared/components/PageHeader';
import Card from '../shared/components/Card';
import LoadingSpinner from '../shared/components/LoadingSpinner';
import ErrorState from '../shared/components/ErrorState';
import EmptyState from '../shared/components/EmptyState';
import DataTable, { type Column } from '../shared/components/DataTable';
import { playTypeLabel } from '../shared/constants';

interface MatchDetailPageProps {
  matchId: number;
}

type TabKey = 'features' | 'predictions';

export default function MatchDetailPage({ matchId }: MatchDetailPageProps) {
  const [activeTab, setActiveTab] = useState<TabKey>('features');
  const [features, setFeatures] = useState<FeatureSnapshot[]>([]);
  const [predictions, setPredictions] = useState<Prediction[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const matchInfo = features.length > 0 ? features[0] : null;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    Promise.all([
      api.features({ match_id: matchId, limit: 10 }),
      api.predictions({ match_id: matchId, limit: 50 }),
    ])
      .then(([f, p]) => {
        if (cancelled) return;
        setFeatures(f.snapshots);
        setPredictions(p.predictions);
        setLoading(false);
      })
      .catch((e) => {
        if (!cancelled) {
          setError(e instanceof ApiError ? e.message : '加载失败');
          setLoading(false);
        }
      });

    return () => { cancelled = true; };
  }, [matchId]);

  if (loading) return <LoadingSpinner text="加载比赛详情..." size="lg" />;
  if (error) return <ErrorState message={error} onRetry={() => window.location.reload()} />;

  const predColumns: Column<Prediction>[] = [
    { key: 'model_name', title: '模型' },
    { key: 'play_type', title: '玩法', render: (v) => playTypeLabel(String(v)) },
    { key: 'option_code', title: '选项', render: (v) => <span className="fqp-mono">{String(v)}</span> },
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
        return <span style={{ color }}>{val >= 0 ? '+' : ''}{val.toFixed(4)}</span>;
      },
    },
    {
      key: 'confidence',
      title: '置信度',
      render: (v) => {
        const val = v as number | null;
        return val !== null ? `${(val * 100).toFixed(0)}%` : '—';
      },
    },
  ];

  return (
    <div>
      <PageHeader
        title={matchInfo ? `${matchInfo.home_team_name} 对阵 ${matchInfo.away_team_name}` : `比赛 #${matchId}`}
        lastUpdated={matchInfo?.snapshot_time}
      />

      {matchInfo && (
        <Card style={{ marginBottom: '20px' }}>
          <div style={{ display: 'flex', gap: '32px', flexWrap: 'wrap' }}>
            {[
              { label: '联赛', value: matchInfo.league_name },
              { label: '特征版本', value: matchInfo.feature_version, mono: true },
              { label: '数据完整度', value: matchInfo.data_completeness_score !== null ? `${Math.round(matchInfo.data_completeness_score)}%` : '—' },
              { label: '不确定度', value: matchInfo.uncertainty_score !== null ? `${Math.round(matchInfo.uncertainty_score)}%` : '—' },
              { label: '主队休息天数', value: `${matchInfo.home_rest_days} 天` },
              { label: '客队休息天数', value: `${matchInfo.away_rest_days} 天` },
            ].map((info, i) => (
              <div
                key={info.label}
                style={{
                  animation: `fqpPopIn 0.3s cubic-bezier(0.34,1.56,0.64,1) both`,
                  animationDelay: `${i * 60}ms`,
                }}
              >
                <div className="fqp-label">{info.label}</div>
                <div className={(info as { mono?: boolean }).mono ? 'fqp-mono' : ''}>{info.value}</div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Tabs */}
      <div className="fqp-tabs">
        <button
          className={`fqp-tab${activeTab === 'features' ? ' active' : ''}`}
          onClick={() => setActiveTab('features')}
        >
          多维特征 ({features.length})
        </button>
        <button
          className={`fqp-tab${activeTab === 'predictions' ? ' active' : ''}`}
          onClick={() => setActiveTab('predictions')}
        >
          模型预测 ({predictions.length})
        </button>
      </div>

      {/* Tab content with transition */}
      <div key={activeTab} className="fqp-anim-fadeIn">
        {activeTab === 'features' && (
          <Card>
            {features.length > 0 ? (
              <DataTable
                columns={[
                  { key: 'snapshot_time', title: '快照时间' },
                  { key: 'feature_version', title: '版本' },
                  {
                    key: 'data_completeness_score',
                    title: '完整度',
                    render: (v) => (v !== null ? `${Math.round(v as number)}%` : '—'),
                  },
                  {
                    key: 'uncertainty_score',
                    title: '不确定度',
                    render: (v) => (v !== null ? `${Math.round(v as number)}%` : '—'),
                  },
                  { key: 'rest_days_diff', title: '休息差', render: (v) => `${v ?? '—'} 天` },
                ]}
                rows={features}
                rowKey={(r) => String(r.id)}
              />
            ) : (
              <EmptyState icon="📊" title="暂无特征快照" description="该比赛尚未生成多维特征快照" />
            )}
          </Card>
        )}

        {activeTab === 'predictions' && (
          <Card>
            {predictions.length > 0 ? (
              <DataTable
                columns={predColumns}
                rows={predictions}
                rowKey={(r) => String(r.id)}
              />
            ) : (
              <EmptyState icon="🧠" title="暂无模型预测" description="该比赛尚未运行模型预测" />
            )}
          </Card>
        )}
      </div>
    </div>
  );
}
