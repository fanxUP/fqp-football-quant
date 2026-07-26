import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import ModelSampleSufficiency, { sampleLevel } from './ModelSampleSufficiency';

describe('sampleLevel', () => {
  it('uses explicit sample thresholds without treating sample size as model quality', () => {
    expect(sampleLevel(0).label).toBe('无样本');
    expect(sampleLevel(29).label).toBe('观察中');
    expect(sampleLevel(30).label).toBe('初步可看');
    expect(sampleLevel(99).label).toBe('初步可看');
    expect(sampleLevel(100).label).toBe('样本较稳');
  });
});

describe('ModelSampleSufficiency', () => {
  it('shows every active model and fills missing play types with zero', () => {
    render(
      <ModelSampleSufficiency
        days={365}
        modelNames={['elo_rating', 'maher_poisson']}
        samples={[
          {
            play_type: 'all',
            model_name: 'elo_rating',
            total_samples: 105,
            settled_dates: 20,
            first_date: '2026-06-01',
            last_date: '2026-07-12',
          },
          {
            play_type: 'spf',
            model_name: 'elo_rating',
            total_samples: 29,
            settled_dates: 8,
            first_date: '2026-06-01',
            last_date: '2026-07-12',
          },
        ]}
      />,
    );

    const table = screen.getByRole('table', { name: '模型与玩法赛前有效样本量' });
    const tableView = within(table);
    expect(tableView.getByText('Elo 实力评分')).toBeInTheDocument();
    expect(tableView.getByText('马赫泊松进球模型')).toBeInTheDocument();
    expect(tableView.getByText('105')).toBeInTheDocument();
    expect(tableView.getByText('样本较稳')).toBeInTheDocument();
    expect(tableView.getByText('29')).toBeInTheDocument();
    expect(tableView.getByText('观察中')).toBeInTheDocument();
    expect(tableView.getAllByText('无样本').length).toBeGreaterThan(0);
    expect(screen.getByText(/365 天/)).toBeInTheDocument();
    expect(screen.getByText(/不代表模型有效/)).toBeInTheDocument();
  });
});
