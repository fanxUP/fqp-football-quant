import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import PoolPage from './PoolPage';

const apiMocks = vi.hoisted(() => ({
  analyze: vi.fn(),
}));

vi.mock('../core/apiClient', () => ({
  api: {
    pool: {
      analyze: apiMocks.analyze,
    },
  },
}));

describe('PoolPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.analyze.mockResolvedValue({
      period_id: '26092',
      analysis_mode: 'historical',
      issue: {
        id: 92,
        issue_no: '26092',
        status: 'closed',
        sale_stop: '2026-07-14T22:00:00+08:00',
        source: 'sporttery',
      },
      matches: [],
      classification: { dan: [], tuo: [], defense: [] },
      full_combinations: { count: 0, total_cost: 0, combinations: [] },
      rx9: { selected_matches: [], combinations_count: 0, total_cost: 0 },
      monte_carlo: {
        hit14_prob: 0,
        hit13_prob: 0,
        rx9_prob: 0,
        simulations: 0,
      },
      warnings: [],
      generated_at: '2026-07-18T12:00:00+08:00',
    });
  });

  it('将已停售官方期次明确标记为历史复盘', async () => {
    render(<PoolPage />);

    expect(await screen.findByText('历史期次复盘')).toBeInTheDocument();
    expect(screen.getByText(/26092/)).toBeInTheDocument();
    expect(screen.getByText(/不是当前投注推荐/)).toBeInTheDocument();
  });
});
