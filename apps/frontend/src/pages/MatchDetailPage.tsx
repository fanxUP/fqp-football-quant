import { useState } from 'react';
import { api } from '../core/apiClient';
import type { FeatureSnapshot, Prediction } from '../core/types';
import PageHeader from '../shared/components/PageHeader';
import Card from '../shared/components/Card';
import LoadingSpinner from '../shared/components/LoadingSpinner';
import EmptyState from '../shared/components/EmptyState';
import DataTable, { type Column } from '../shared/components/DataTable';
import { optionLabel, playTypeLabel } from '../shared/constants';
import useManualEvidence from './useManualEvidence';
import ReadEvidenceStatus from './ReadEvidenceStatus';
import RosterEvidencePanel from '../features/tactics/RosterEvidencePanel';

interface MatchDetailPageProps {
  matchId: number;
}

type TabKey = 'features' | 'predictions' | 'roster';

function MatchQuery({ matchId }: MatchDetailPageProps) {
  const [activeTab, setActiveTab] = useState<TabKey>('features');
  const featureResource = useManualEvidence(async () => {
    const result = await api.features({ match_id: matchId, limit: 10 });
    if (!Array.isArray(result.snapshots) || result.snapshots.length > 10 || result.snapshots.some(row => row.match_id !== matchId)) throw new Error('特征快照与所选比赛不一致');
    return result.snapshots;
  });
  const predictionResource = useManualEvidence(async () => {
    const result = await api.predictions({ match_id: matchId, limit: 50 });
    if (!Array.isArray(result.predictions) || result.predictions.length > 50 || result.predictions.some(row => row.match_id !== matchId)) throw new Error('预测与所选比赛不一致');
    return result.predictions;
  });
  const features: FeatureSnapshot[] = featureResource.data ?? [];
  const predictions: Prediction[] = predictionResource.data ?? [];
  const matchInfo = features[0] ?? null;

  const predColumns: Column<Prediction>[] = [
    { key: 'model_name', title: '模型' },
    { key: 'play_type', title: '玩法', render: (v) => playTypeLabel(String(v)) },
    { key: 'option_code', title: '选项', render: (v, row) => <span className="fqp-mono">{optionLabel(row.play_type, String(v))}</span> },
    {
      key: 'model_probability',
      title: '模型概率',
      render: (v) => {
        const val = v as number | null;
        return typeof val === 'number' && Number.isFinite(val) ? `${(val * 100).toFixed(1)}%` : '—';
      },
    },
    {
      key: 'market_probability',
      title: '市场概率',
      render: (v) => {
        const val = v as number | null;
        return typeof val === 'number' && Number.isFinite(val) ? `${(val * 100).toFixed(1)}%` : '—';
      },
    },
    {
      key: 'ev',
      title: 'EV',
      render: (v) => {
        const val = v as number | null;
        if (typeof val !== 'number' || !Number.isFinite(val)) return '—';
        const color = val > 0 ? 'var(--fqp-success)' : val < 0 ? 'var(--fqp-red-neon)' : 'var(--fqp-text-muted)';
        return <span style={{ color }}>{val >= 0 ? '+' : ''}{val.toFixed(4)}</span>;
      },
    },
    {
      key: 'confidence',
      title: '置信度',
      render: (v) => {
        const val = v as number | null;
        return typeof val === 'number' && Number.isFinite(val) ? `${(val * 100).toFixed(0)}%` : '—';
      },
    },
  ];

  return (
    <div className="be-page">
      <PageHeader
        title={matchInfo ? `${matchInfo.home_team_name} VS ${matchInfo.away_team_name}` : `比赛 #${matchId}`}
        lastUpdated={matchInfo?.snapshot_time}
      />

      {matchInfo && (
        <Card style={{ marginBottom: '20px' }}>
          <div style={{ display: 'flex', gap: '32px', flexWrap: 'wrap' }}>
            {[
              { label: '联赛', value: matchInfo.league_name },
              { label: '特征版本', value: matchInfo.feature_version, mono: true },
              { label: '数据完整度', value: Number.isFinite(matchInfo.data_completeness_score) && matchInfo.data_completeness_score !== null ? `${Math.round(matchInfo.data_completeness_score)}%` : '—' },
              { label: '不确定度', value: Number.isFinite(matchInfo.uncertainty_score) && matchInfo.uncertainty_score !== null ? `${Math.round(matchInfo.uncertainty_score)}%` : '—' },
              { label: '主队休息天数', value: `${matchInfo.home_rest_days ?? '—'} 天` },
              { label: '客队休息天数', value: `${matchInfo.away_rest_days ?? '—'} 天` },
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

      <p>历史特征与模型预测独立读取；阵容与伤停页展示当前情报，不能用于重建历史赛前证据。</p>
      {/* Tabs */}
      <div className="fqp-tabs" style={{ flexWrap: 'wrap' }}>
        <button type="button" className={`fqp-tab${activeTab === 'roster' ? ' active' : ''}`} aria-pressed={activeTab === 'roster'} onClick={() => setActiveTab('roster')}>阵容与伤停</button>
        <button
          className={`fqp-tab${activeTab === 'features' ? ' active' : ''}`}
          aria-pressed={activeTab === 'features'}
          onClick={() => setActiveTab('features')}
        >
          多维特征 ({featureResource.data === null ? '—' : features.length})
        </button>
        <button
          className={`fqp-tab${activeTab === 'predictions' ? ' active' : ''}`}
          aria-pressed={activeTab === 'predictions'}
          onClick={() => setActiveTab('predictions')}
        >
          模型预测 ({predictionResource.data === null ? '—' : predictions.length})
        </button>
      </div>

      {/* Tab content with transition */}
      <div key={activeTab} className="fqp-anim-fadeIn">
        {activeTab === 'roster' && <RosterEvidencePanel matchId={matchId} />}
        {activeTab === 'features' && (
          <Card>
            <ReadEvidenceStatus resource={featureResource} label="刷新多维特征" note="最多 10 个快照" />
            {featureResource.data === null ? (featureResource.loading ? <LoadingSpinner text="读取特征快照" /> : null) : <>
            {features.length > 0 ? (
              <DataTable
                columns={[
                  { key: 'snapshot_time', title: '快照时间' },
                  { key: 'feature_version', title: '版本' },
                  {
                    key: 'data_completeness_score',
                    title: '完整度',
                    render: (v) => (typeof v === 'number' && Number.isFinite(v) ? `${Math.round(v)}%` : '—'),
                  },
                  {
                    key: 'uncertainty_score',
                    title: '不确定度',
                    render: (v) => (typeof v === 'number' && Number.isFinite(v) ? `${Math.round(v)}%` : '—'),
                  },
                  { key: 'rest_days_diff', title: '休息差', render: (v) => `${v ?? '—'} 天` },
                ]}
                rows={features}
                rowKey={(r) => String(r.id)}
              />
            ) : (
              <EmptyState icon="📊" title="暂无特征快照" description="该比赛尚未生成多维特征快照" />
            )}
            </>}
          </Card>
        )}

        {activeTab === 'predictions' && (
          <Card>
            <ReadEvidenceStatus resource={predictionResource} label="刷新模型预测" note="最多 50 条预测" />
            {predictionResource.data === null ? (predictionResource.loading ? <LoadingSpinner text="读取模型预测" /> : null) : <>
            {predictions.length > 0 ? (
              <DataTable
                columns={predColumns}
                rows={predictions}
                rowKey={(r) => String(r.id)}
              />
            ) : (
              <EmptyState icon="🧠" title="暂无模型预测" description="该比赛尚未运行模型预测" />
            )}
            </>}
          </Card>
        )}
      </div>
    </div>
  );
}

export default function MatchDetailPage({ matchId }: MatchDetailPageProps) { return <MatchQuery key={matchId} matchId={matchId} />; }
