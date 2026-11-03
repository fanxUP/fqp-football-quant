import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import FeatureSnapshotPanel from './FeatureSnapshotPanel';

const features = vi.hoisted(() => vi.fn());

vi.mock('../../core/apiClient', () => ({ api: { features } }));

describe('FeatureSnapshotPanel', () => {
  it('说明特征快照是否能够参与预测修正', async () => {
    features.mockResolvedValue({
      snapshots: [
        {
          id: 1,
          match_id: 101,
          snapshot_time: '2026-07-14T12:00:00',
          feature_version: 'feature_rule_v1',
          data_completeness_score: 80,
          uncertainty_score: 20,
          home_team_name: '英格兰',
          away_team_name: '阿根廷',
          league_name: '测试联赛',
          match_num_str: '周一001',
        },
        {
          id: 2,
          match_id: 102,
          snapshot_time: '2026-07-14T12:00:00',
          feature_version: 'feature_rule_v1',
          data_completeness_score: 40,
          uncertainty_score: 60,
          home_team_name: '法国',
          away_team_name: '西班牙',
          league_name: '测试联赛',
          match_num_str: '周一002',
        },
      ],
      observed_batches: [
        {
          id: 9,
          match_id: 101,
          cutoff_id: 'cutoff-9',
          cutoff_as_of: '2026-07-14T11:55:00',
          builder_version: 'observed_input_v2',
          feature_schema_version: 'observed-form/v3',
          status: 'complete',
          required_fields_count: 55,
          feature_fields_count: 55,
          value_fields_count: 30,
          unknown_fields_count: 20,
        },
      ],
    });

    render(<FeatureSnapshotPanel />);

    expect(await screen.findByText('完整批次')).toBeInTheDocument();
    expect(screen.getByText(/完整度只表示资料覆盖比例/)).toBeInTheDocument();
    expect(screen.getByText('55/55 已记录；30 有值；20 未知；5 其他状态')).toBeInTheDocument();
    expect(screen.queryByText('可参与预测修正')).not.toBeInTheDocument();
  });
});
