import { useEffect, useState } from 'react';
import { api } from '../../core/apiClient';
import { ApiError, type FeatureSnapshot, type ObservedFeatureBatchSummary } from '../../core/types';
import Card from '../../shared/components/Card';
import DataTable, { type Column } from '../../shared/components/DataTable';
import ErrorState from '../../shared/components/ErrorState';
import TeamName from '../../shared/components/TeamName';

const batchStatusLabel = (status: unknown): string => {
  const labels: Record<string, string> = {
    complete: '完整批次',
    partial: '部分批次',
    running: '构建中',
  };
  return labels[String(status)] || '未知状态';
};

export default function FeatureSnapshotPanel() {
  const [snapshots, setSnapshots] = useState<FeatureSnapshot[]>([]);
  const [observedBatches, setObservedBatches] = useState<ObservedFeatureBatchSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.features({ limit: 100 })
      .then((response) => {
        setSnapshots(response.snapshots || []);
        setObservedBatches(response.observed_batches || []);
      })
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
      key: 'snapshot_time',
      title: '生成时间',
      render: (value) => String(value || '').replace('T', ' ').slice(0, 19),
    },
  ];

  const snapshotByMatch = new Map(snapshots.map((snapshot) => [snapshot.match_id, snapshot]));
  const observedBatchColumns: Column<ObservedFeatureBatchSummary>[] = [
    {
      key: 'match_id',
      title: '比赛',
      render: (_value, row) => {
        const snapshot = snapshotByMatch.get(row.match_id);
        return snapshot
          ? `${snapshot.match_num_str || `#${row.match_id}`} ${snapshot.home_team_name} - ${snapshot.away_team_name}`
          : `比赛 #${row.match_id}`;
      },
    },
    {
      key: 'status',
      title: '最新批次状态',
      render: (value) => batchStatusLabel(value),
    },
    {
      key: 'cutoff_as_of',
      title: '输入截止',
      render: (value) => String(value || '').replace('T', ' ').slice(0, 19),
    },
    {
      key: 'builder_version',
      title: '构建器 / 特征版本',
      render: (_value, row) => `${row.builder_version} / ${row.feature_schema_version}`,
    },
    {
      key: 'feature_fields_count',
      title: '字段记录',
      render: (_value, row) => {
        const otherStatusCount = Math.max(
          row.feature_fields_count - row.value_fields_count - row.unknown_fields_count,
          0,
        );
        return `${row.feature_fields_count}/${row.required_fields_count} 已记录；${row.value_fields_count} 有值；${row.unknown_fields_count} 未知；${otherStatusCount} 其他状态`;
      },
    },
  ];

  if (error) return <ErrorState message={error} />;

  return (
    <Card title="比赛特征与观测证据" style={{ padding: 0, overflow: 'hidden' }}>
      <p style={{ margin: '0 16px 12px', color: 'var(--fqp-text-muted)' }}>
        批次状态和字段计数按保存记录展示。旧快照完整度只表示资料覆盖比例，不代表模型已采用；具体使用以该次预测的输入记录为准。
      </p>
      <h4 style={{ margin: '12px 16px' }}>旧特征快照</h4>
      <DataTable
        columns={columns}
        rows={snapshots}
        loading={loading}
        emptyText="暂无比赛特征快照"
        rowKey={(row) => row.id}
      />
      <h4 style={{ margin: '20px 16px 12px' }}>对应比赛的 P104 观测批次</h4>
      <DataTable
        columns={observedBatchColumns}
        rows={observedBatches}
        loading={loading}
        emptyText="当前快照列表涉及的比赛暂无观测批次"
        rowKey={(row) => row.id}
      />
    </Card>
  );
}
