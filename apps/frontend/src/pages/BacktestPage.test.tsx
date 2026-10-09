import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import BacktestPage from './BacktestPage';

const apiMocks = vi.hoisted(() => ({
  list: vi.fn(),
  get: vi.fn(),
  backtestEquity: vi.fn(),
  create: vi.fn(),
}));

vi.mock('../core/apiClient', () => ({
  api: {
    backtests: {
      list: apiMocks.list,
      get: apiMocks.get,
      create: apiMocks.create,
    },
    dashboard: { backtestEquity: apiMocks.backtestEquity },
  },
}));

vi.mock('../visualization/backtest/BacktestPerformanceCharts', () => ({
  default: ({ windowRows }: { windowRows: Array<{ run_id: number }> }) => <div aria-label="回测图表分析">{windowRows.map(row => `curve-${row.run_id}`).join(",")}</div>,
}));

describe('BacktestPage', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    apiMocks.backtestEquity.mockResolvedValue({ data: { series: [] } });
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

const run = (id: number, name = `界面测试${id}`) => ({ id, name, status: 'completed', created_at: '2026-10-08', config: { methodology_version: 3 } });
const detail = (id: number) => ({ run: run(id), results: [{ window_index: null, model_name: `model-${id}`, n_bets: 0, n_wins: 0, hit_rate: 0, roi: 0, total_profit: 0 }], windows: [] });
const deferred = <T,>() => { let resolve!: (value: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { promise, resolve }; };

describe('BacktestPage evidence isolation', () => {
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });
  beforeEach(() => {
    vi.resetAllMocks();
    apiMocks.list.mockResolvedValue({ runs: [run(1), run(2)], total: 55 });
    apiMocks.backtestEquity.mockResolvedValue({ data: { series: [] } });
  });
  it('快速切换记录忽略旧详情并清空旧结果', async () => {
    const first = deferred<ReturnType<typeof detail>>();
    apiMocks.get.mockImplementation((id: number) => id === 1 ? first.promise : Promise.resolve(detail(id)));
    render(<BacktestPage />);
    const buttons = await screen.findAllByRole('button', { name: '查看' });
    fireEvent.click(buttons[0]); fireEvent.click(buttons[1]);
    await screen.findAllByText('model-2');
    await act(async () => { first.resolve(detail(1)); });
    expect(screen.queryByText('model-1')).not.toBeInTheDocument();
    expect(screen.getAllByText('model-2')).toHaveLength(2);
  });
  it('迟到的曲线不会覆盖另一次运行的窗口', async () => {
    const first = deferred<{ data: { series: Array<{ run_id: number }> } }>();
    apiMocks.get.mockImplementation((id: number) => Promise.resolve(detail(id)));
    apiMocks.backtestEquity.mockImplementation(({ run_id }: { run_id: number }) => run_id === 1 ? first.promise : Promise.resolve({ data: { series: [{ run_id: 2 }] } }));
    render(<BacktestPage />);
    const buttons = await screen.findAllByRole('button', { name: '查看' });
    fireEvent.click(buttons[0]); await screen.findAllByText('model-1');
    fireEvent.click(buttons[1]); await screen.findByText('curve-2');
    await act(async () => { first.resolve({ data: { series: [{ run_id: 1 }] } }); });
    expect(screen.queryByText('curve-1')).not.toBeInTheDocument();
    expect(screen.getByText('curve-2')).toBeInTheDocument();
  });
  it('详情失败可以独立重试且不误报空结果', async () => {
    apiMocks.get.mockRejectedValueOnce(new Error('详情故障')).mockResolvedValue(detail(1));
    render(<BacktestPage />);
    fireEvent.click((await screen.findAllByRole('button', { name: '查看' }))[0]);
    await screen.findByText(/详情故障/);
    expect(screen.queryByText('暂无该回测的聚合结果')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '刷新回测详情' }));
    await screen.findAllByText('model-1');
    expect(apiMocks.list).toHaveBeenCalledTimes(1);
  });
  it('拒绝与所选运行不一致的详情', async () => {
    apiMocks.get.mockResolvedValue(detail(2));
    render(<BacktestPage />);
    fireEvent.click((await screen.findAllByRole('button', { name: '查看' }))[0]);
    expect(await screen.findByText(/回测详情与所选运行不一致/)).toBeInTheDocument();
    expect(screen.queryByText('model-2')).not.toBeInTheDocument();
  });
  it('曲线失败不阻断指标并可独立重试', async () => {
    apiMocks.get.mockResolvedValue(detail(1));
    apiMocks.backtestEquity.mockRejectedValueOnce(new Error('曲线故障')).mockResolvedValue({ data: { series: [{ run_id: 1 }] } });
    render(<BacktestPage />);
    fireEvent.click((await screen.findAllByRole('button', { name: '查看' }))[0]);
    await screen.findAllByText('model-1'); await screen.findByText(/曲线故障/);
    fireEvent.click(screen.getByRole('button', { name: '刷新窗口趋势' }));
    await screen.findByText('curve-1');
    expect(apiMocks.get).toHaveBeenCalledTimes(1);
  });
  it('筛选有限列表且分页，并区分全局总数', async () => {
    apiMocks.list.mockResolvedValue({ runs: Array.from({ length: 23 }, (_, i) => run(i + 1)), total: 55 });
    render(<BacktestPage />);
    expect(await screen.findAllByRole('button', { name: '查看' })).toHaveLength(10);
    expect(screen.getByText(/已获取 23.*数据库共 55/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '下一页回测' }));
    expect(screen.getByText('2 / 3 页')).toBeInTheDocument();
    fireEvent.change(screen.getByRole('searchbox', { name: '搜索回测记录' }), { target: { value: '界面测试23' } });
    expect(screen.getAllByRole('button', { name: '查看' })).toHaveLength(1);
    expect(screen.getByText('1 / 1 页')).toBeInTheDocument();
  });
  it('列表刷新失败保留记录并手动恢复', async () => {
    apiMocks.list.mockResolvedValueOnce({ runs: [run(1)], total: 1 }).mockRejectedValueOnce(new Error('列表故障')).mockResolvedValue({ runs: [], total: 0 });
    render(<BacktestPage />); await screen.findByText('界面测试1');
    fireEvent.click(screen.getByRole('button', { name: '刷新回测列表' }));
    await screen.findByText(/列表故障/); expect(screen.getByText('界面测试1')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '刷新回测列表' }));
    await waitFor(() => expect(screen.queryByText('界面测试1')).not.toBeInTheDocument());
  });
  it('提交概率0保留为0', async () => {
    apiMocks.create.mockResolvedValue({ status: 'ok' });
    render(<BacktestPage />); await screen.findByText('界面测试1');
    fireEvent.change(screen.getByLabelText('最低模型概率'), { target: { value: '0' } });
    fireEvent.click(screen.getByRole('button', { name: '开始回测' }));
    await waitFor(() => expect(apiMocks.create).toHaveBeenCalledWith(expect.objectContaining({ min_model_prob: 0 })));
  });
  it('可见时轮询列表，隐藏时停止读取', async () => {
    vi.useFakeTimers();
    render(<BacktestPage />);
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(apiMocks.list).toHaveBeenCalledTimes(1);
    await act(async () => { vi.advanceTimersByTime(30_000); await Promise.resolve(); });
    expect(apiMocks.list).toHaveBeenCalledTimes(2);
    const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden');
    await act(async () => { document.dispatchEvent(new Event('visibilitychange')); vi.advanceTimersByTime(60_000); });
    expect(apiMocks.list).toHaveBeenCalledTimes(2);
    visibility.mockRestore();
  });
  it('拒绝混入其他运行的窗口趋势', async () => {
    apiMocks.get.mockResolvedValue(detail(1));
    apiMocks.backtestEquity.mockResolvedValue({ data: { series: [{ run_id: 2 }] } });
    render(<BacktestPage />);
    fireEvent.click((await screen.findAllByRole('button', { name: '查看' }))[0]);
    expect(await screen.findByText(/窗口趋势与所选运行不一致/)).toBeInTheDocument();
    expect(screen.queryByText('curve-2')).not.toBeInTheDocument();
  });
  it('后端以空图表返回读取故障时明确报错', async () => {
    apiMocks.get.mockResolvedValue(detail(1));
    apiMocks.backtestEquity.mockResolvedValue({ empty: true, empty_reason: '无法读取回测视图', series: [] });
    render(<BacktestPage />);
    fireEvent.click((await screen.findAllByRole('button', { name: '查看' }))[0]);
    expect(await screen.findByText(/无法读取回测视图/)).toBeInTheDocument();
  });

});
