import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import BacktestPage from './BacktestPage';

const apiMocks = vi.hoisted(() => ({
  list: vi.fn(),
}));

vi.mock('../core/apiClient', () => ({
  api: {
    backtests: {
      list: apiMocks.list,
      get: vi.fn(),
      create: vi.fn(),
    },
    dashboard: { backtestEquity: vi.fn() },
  },
}));

describe('BacktestPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.list.mockResolvedValue({ runs: [], total: 0, limit: 30, offset: 0 });
  });

  it('明确说明时间窗回测不会重新训练模型', async () => {
    render(<BacktestPage />);

    expect(await screen.findByText('策略验证')).toBeInTheDocument();
    expect(screen.getByText('滚动时间窗（不重训模型）')).toBeInTheDocument();
  });
});
