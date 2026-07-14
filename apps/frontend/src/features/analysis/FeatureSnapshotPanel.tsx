import { useEffect, useState } from 'react';
import { api } from '../../core/apiClient';
import { ApiError, type FeatureSnapshot } from '../../core/types';
import Card from '../../shared/components/Card';
import DataTable, { type Column } from '../../shared/components/DataTable';
import ErrorState from '../../shared/components/ErrorState';
import TeamName from '../../shared/components/TeamName';

const MIN_PREDICTION_COMPLETENESS = 50;

export default function FeatureSnapshotPanel() {
  const [snapshots, setSnapshots] = useState<FeatureSnapshot[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.features({ limit: 100 })
      .then((response) => setSnapshots(response.snapshots || []))
      .catch((e) => setError(e instanceof ApiError ? e.message : '加载特征数据失败'))
      .finally(() => setLoading(false));
  }, []);

  const columns: Column<FeatureSnapshot>[] = [
    { key: 'match_num_str', title: '场次', render: (value) => typeof value === 'string' && value ? value : '—' },
    { key: 'home_team_name', title: '主队', render: (value) => <TeamName name={String(value)} /> },
    { key: 'away_team_name', title: '客队', render: (value) => <TeamName name={String(value)} /> },
    { key: 'league_name', title: '赛事' },
    { key: 'feature_version', title: '版本' },
    {
      key: 'data_completeness_score',
      title: '完整度',
      render: (value) => value == null ? '—' : `${Number(value).toFixed(1)}%`,
    },
    {
      key: 'uncertainty_score',
      title: '不确定性',
      render: (value) => value == null ? '—' : `${Number(value).toFixed(1)}%`,
    },
    {
      key: 'decision_effect',
      title: '决策作用',
      render: (_value, row) => Number(row.data_completeness_score || 0) >= MIN_PREDICTION_COMPLETENESS
        ? <span style={{ color: 'var(--fqp-success)' }}>可参与预测修正</span>
        : <span style={{ color: 'var(--fqp-text-muted)' }}>仅展示，数据不足</span>,
    },
    {
      key: 'snapshot_time',
      title: '生成时间',
      render: (value) => String(value || '').replace('T', ' ').slice(0, 19),
    },
  ];

  if (error) return <ErrorState message={error} />;

  return (
    <Card title="比赛特征数据健康" style={{ padding: 0, overflow: 'hidden' }}>
      <DataTable
        columns={columns}
        rows={snapshots}
        loading={loading}
        emptyText="暂无比赛特征快照"
        rowKey={(row) => row.id}
      />
    </Card>
  );
}
