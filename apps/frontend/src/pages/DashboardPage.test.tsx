import { StrictMode } from 'react';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import DashboardPage from './DashboardPage';
import { LiveStatusProvider } from '../features/command-center/LiveStatus';

const api = vi.hoisted(() => ({
  health: vi.fn().mockResolvedValue({ status: 'ok' }),
  ops: { pipeline: vi.fn().mockResolvedValue({ jobs: [], sources: [] }) },
  teams: vi.fn().mockResolvedValue({ total: 0, teams: [] }),
  predictions: vi.fn().mockResolvedValue({ total: 0, predictions: [] }),
  tickets: vi.fn().mockResolvedValue({ total: 0, tickets: [] }),
  betting: { tickets: vi.fn().mockResolvedValue({ total: 0, tickets: [] }) },
  reviews: { daily: vi.fn().mockResolvedValue({ total: 0, reviews: [] }) },
  dashboard: {
    predictionCount: vi.fn().mockResolvedValue({ total: 0 }),
    today: vi.fn().mockResolvedValue({ data: { kpis: [], extras: {} } }),
    roiDaily: vi.fn().mockResolvedValue({ data: { series: [] } }),
    modelPerformance: vi.fn().mockResolvedValue({ data: { series: [] } }),
  },
}));

vi.mock('../core/apiClient', () => ({ api }));
vi.mock('../features/command-center/useReducedMotion', () => ({ default: () => true }));
vi.mock('../features/command-center/MatchOverview', () => ({ default: () => <div /> }));
vi.mock('../shared/components/ChartCard', () => ({ default: () => <div /> }));
vi.mock('../visualization', () => ({
  RoiLineChart: () => <div data-testid="roi-chart" />,
  EmptyChartState: ({ title, description }: { title: string; description: string }) => <div>{title}<span>{description}</span></div>,
  AiPoolDashboard: ({ models, loading, error }: { models: unknown[]; loading: boolean; error?: string }) => <div data-testid="model-chart">{error || `${models.length}个模型 · ${loading ? '加载中' : '就绪'}`}</div>,
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

function stat(title: string) {
  return within(screen.getByRole('heading', { name: title }).closest('.fqp-card') as HTMLElement);
}

describe('DashboardPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.dashboard.predictionCount.mockResolvedValue({ total: 0 });
    api.dashboard.roiDaily.mockResolvedValue({ data: { series: [] } });
    api.dashboard.modelPerformance.mockResolvedValue({ data: { series: [] } });
    api.dashboard.today.mockResolvedValue({
      data: {
        kpis: [
          { key: 'predicted_match_count', label: '已预测比赛', value: 15 },
          { key: 'ai_stake_today', label: 'AI 模拟投入', value: 120 },
          { key: 'ai_ticket_count', label: 'AI 票单数', value: 4 },
          { key: 'pending_settlement_count', label: '待开奖', value: 3 },
        ],
        extras: {},
      },
    });
    api.betting.tickets.mockResolvedValue({ total: 23, tickets: [] });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('loads its initial dashboard data once in StrictMode', async () => {
    render(<StrictMode><LiveStatusProvider><DashboardPage /></LiveStatusProvider></StrictMode>);

    await waitFor(() => expect(api.dashboard.today).toHaveBeenCalledTimes(1));
    expect(api.health).toHaveBeenCalledTimes(1);
    expect(api.teams).toHaveBeenCalledTimes(1);
    expect(api.dashboard.predictionCount).toHaveBeenCalledTimes(1);
    expect(api.predictions).not.toHaveBeenCalled();
  });

  it('shows other statistics and starts charts while the exact prediction count is pending', async () => {
    vi.useFakeTimers();
    const count = deferred<{ total: number }>();
    api.dashboard.predictionCount.mockReturnValueOnce(count.promise);
    api.tickets.mockResolvedValueOnce({ total: 8, tickets: [] });
    api.dashboard.roiDaily.mockResolvedValueOnce({ data: { series: [{ snapshot_date: '2026-10-16', agent_cumulative_roi: 0, user_cumulative_roi: 0 }] } });
    render(<LiveStatusProvider><DashboardPage /></LiveStatusProvider>);

    await act(async () => { await vi.advanceTimersByTimeAsync(800); });
    expect(stat('活跃推荐').getByText('8')).toBeInTheDocument();
    expect(stat('彩票记录').getByText('23')).toBeInTheDocument();
    expect(stat('模型预测').getByText('—')).toBeInTheDocument();
    expect(screen.getByTestId('roi-chart')).toBeInTheDocument();
    expect(api.dashboard.modelPerformance).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId('model-chart')).toHaveTextContent('就绪');

    await act(async () => { count.resolve({ total: 1234 }); await vi.advanceTimersByTimeAsync(800); });
    expect(stat('模型预测').getByText('1,234')).toBeInTheDocument();
  });

  it('shows completed statistics and ROI without waiting for model performance', async () => {
    vi.useFakeTimers();
    const models = deferred<{ data: { series: unknown[] } }>();
    api.dashboard.modelPerformance.mockReturnValueOnce(models.promise);
    api.dashboard.predictionCount.mockResolvedValueOnce({ total: 45 });
    api.dashboard.roiDaily.mockResolvedValueOnce({ data: { series: [{ snapshot_date: '2026-10-16', agent_cumulative_roi: 0, user_cumulative_roi: 0 }] } });
    render(<LiveStatusProvider><DashboardPage /></LiveStatusProvider>);

    await act(async () => { await vi.advanceTimersByTimeAsync(800); });
    expect(stat('模型预测').getByText('45')).toBeInTheDocument();
    expect(screen.getByTestId('roi-chart')).toBeInTheDocument();
    expect(screen.getByTestId('model-chart')).toHaveTextContent('加载中');
    await act(async () => { models.resolve({ data: { series: [{}] } }); });
    expect(screen.getByTestId('model-chart')).toHaveTextContent('1个模型 · 就绪');
  });

  it('shows model performance without waiting for ROI', async () => {
    const roi = deferred<{ data: { series: never[] } }>();
    api.dashboard.roiDaily.mockReturnValueOnce(roi.promise);
    api.dashboard.modelPerformance.mockResolvedValueOnce({ data: { series: [{}] } });
    render(<LiveStatusProvider><DashboardPage /></LiveStatusProvider>);

    await waitFor(() => expect(screen.getByTestId('model-chart')).toHaveTextContent('1个模型 · 就绪'));
    await act(async () => { roi.resolve({ data: { series: [] } }); });
  });

  it('keeps a failed count unknown while other cards and charts remain usable', async () => {
    api.dashboard.predictionCount.mockRejectedValueOnce(new Error('count unavailable'));
    api.dashboard.modelPerformance.mockResolvedValueOnce({ data: { series: [{}] } });
    render(<LiveStatusProvider><DashboardPage /></LiveStatusProvider>);

    await waitFor(() => expect(api.dashboard.modelPerformance).toHaveBeenCalledTimes(1));
    expect(stat('模型预测').getByText('—')).toBeInTheDocument();
    expect(stat('模型预测').queryByText('等待模型计算')).not.toBeInTheDocument();
    await waitFor(() => expect(stat('彩票记录').getByText('张彩票已归档')).toBeInTheDocument());
    expect(screen.getByTestId('model-chart')).toHaveTextContent('1个模型 · 就绪');
    expect(screen.getByText('预测总数读取失败')).toBeInTheDocument();
  });

  it('shows model read failures independently of successful today KPIs', async () => {
    api.dashboard.modelPerformance.mockRejectedValueOnce(new Error('model read failed'));
    render(<LiveStatusProvider><DashboardPage /></LiveStatusProvider>);
    await waitFor(() => expect(screen.getByTestId('model-chart')).toHaveTextContent('请求失败'));
  });

  it.each(['pending', 'failed'])('shows completed models when today KPIs are %s', async (status) => {
    const today = deferred<unknown>();
    if (status === 'pending') api.dashboard.today.mockReturnValueOnce(today.promise);
    else api.dashboard.today.mockRejectedValueOnce(new Error('today unavailable'));
    api.dashboard.modelPerformance.mockResolvedValueOnce({ data: { series: [{}] } });
    render(<LiveStatusProvider><DashboardPage /></LiveStatusProvider>);
    await waitFor(() => expect(screen.getByTestId('model-chart')).toHaveTextContent('1个模型 · 就绪'));
    if (status === 'pending') await act(async () => { today.resolve({ data: { kpis: [], extras: {} } }); });
  });

  it('shows ROI read failure and clears it when a background refresh succeeds', async () => {
    vi.useFakeTimers();
    api.dashboard.roiDaily.mockRejectedValueOnce(new Error('ROI read failed'));
    render(<LiveStatusProvider><DashboardPage /></LiveStatusProvider>);
    await act(async () => { await vi.advanceTimersByTimeAsync(800); });
    expect(screen.getByText('读取失败')).toBeInTheDocument();
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(screen.queryByText('读取失败')).not.toBeInTheDocument();
  });

  it('accepts an empty exact count as zero', async () => {
    render(<LiveStatusProvider><DashboardPage /></LiveStatusProvider>);
    await waitFor(() => expect(stat('模型预测').getByText('等待模型计算')).toBeInTheDocument());
    expect(stat('模型预测').getByText('0')).toBeInTheDocument();
  });

  it('ignores pending results after unmount', async () => {
    const count = deferred<{ total: number }>();
    api.dashboard.predictionCount.mockReturnValueOnce(count.promise);
    const view = render(<LiveStatusProvider><DashboardPage /></LiveStatusProvider>);
    view.unmount();
    await act(async () => { count.resolve({ total: 19 }); });
    expect(view.container).toBeEmptyDOMElement();
  });

  it('使用真实 Agent 投入和待开奖数，并定时刷新驾驶舱', async () => {
    vi.useFakeTimers();

    render(<LiveStatusProvider><DashboardPage /></LiveStatusProvider>);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
      vi.advanceTimersByTime(700);
    });

    expect(screen.getByText('已使用 ¥120 / ¥500 （每日预算）')).toBeInTheDocument();
    expect(screen.getByText('张彩票已归档')).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(30_000);
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(api.dashboard.today).toHaveBeenCalledTimes(2);
    expect(api.betting.tickets).toHaveBeenCalledTimes(2);
  });
});
