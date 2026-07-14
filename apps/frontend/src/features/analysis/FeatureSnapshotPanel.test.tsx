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
    });

    render(<FeatureSnapshotPanel />);

    expect(await screen.findByText('可参与预测修正')).toBeInTheDocument();
    expect(screen.getByText('仅展示，数据不足')).toBeInTheDocument();
  });
});
