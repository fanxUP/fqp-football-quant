import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import BacktestPage from './BacktestPage';

const apiMocks = vi.hoisted(() => ({
  list: vi.fn(),
  get: vi.fn(),
  backtestEquity: vi.fn(),
}));

vi.mock('../core/apiClient', () => ({
  api: {
    backtests: {
      list: apiMocks.list,
      get: apiMocks.get,
      create: vi.fn(),
    },
    dashboard: { backtestEquity: apiMocks.backtestEquity },
  },
}));

vi.mock('../visualization/backtest/BacktestPerformanceCharts', () => ({
  default: () => <div aria-label="回测图表分析" />,
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

  it('查看回测详情后直接展示图表分析', async () => {
    apiMocks.list.mockResolvedValue({
      runs: [{ id: 19, name: '全量回测', status: 'completed', created_at: '2026-07-12' }],
      total: 1,
    });
    apiMocks.get.mockResolvedValue({
      run: { id: 19 },
      windows: [],
      results: [{
        window_index: null,
        model_name: 'elo_rating',
        n_bets: 100,
        n_wins: 40,
        hit_rate: 0.4,
        roi: 0.08,
        total_profit: 8,
        max_drawdown_pct: 7,
      }],
    });
    apiMocks.backtestEquity.mockResolvedValue({ data: { series: [] } });

    render(<BacktestPage />);
    fireEvent.click(await screen.findByRole('button', { name: '查看' }));

    expect(await screen.findByLabelText('回测图表分析')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '📈 查看资金曲线' })).not.toBeInTheDocument();
  });

  it('明确标记旧回测口径且不用于模型上线判断', async () => {
    apiMocks.list.mockResolvedValue({
      runs: [{
        id: 18,
        name: '旧全量回测',
        config: { methodology_version: 2 },
        status: 'completed',
        created_at: '2026-07-07',
      }],
      total: 1,
    });
    apiMocks.get.mockResolvedValue({
      run: { id: 18, config: { methodology_version: 2 } },
      windows: [],
      results: [{
        window_index: null,
        model_name: 'elo_rating',
        n_bets: 100,
        n_wins: 40,
        hit_rate: 0.4,
        roi: 0.08,
        total_profit: 8,
        max_drawdown_pct: 7,
      }],
    });
    apiMocks.backtestEquity.mockResolvedValue({ data: { series: [] } });

    render(<BacktestPage />);

    expect(await screen.findByText('旧口径')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '查看' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('旧口径结果仅供归档');
    expect(screen.queryByText('满足上线门槛')).not.toBeInTheDocument();
    expect(screen.queryByText('未完全满足上线门槛')).not.toBeInTheDocument();
  });

  it('将时区校准后的回测标记为当前V3口径', async () => {
    apiMocks.list.mockResolvedValue({
      runs: [{
        id: 21,
        name: '时区校准回测',
        config: { methodology_version: 3 },
        status: 'completed',
        created_at: '2026-07-15',
      }],
      total: 1,
    });

    render(<BacktestPage />);

    expect(await screen.findByText('当前 V3')).toBeInTheDocument();
  });
});
