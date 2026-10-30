import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import PoolPage from './PoolPage';
import { ApiError, type PoolAnalysis } from '../core/types';

const mocks = vi.hoisted(() => ({ analyze: vi.fn(), issues: vi.fn(), plans: vi.fn(), save: vi.fn(), plan: vi.fn(), catalog: vi.fn(), catalogIssue: vi.fn() }));
vi.mock('../core/apiClient', () => ({ api: { pool: mocks } }));
function result(): PoolAnalysis {
  const issue = { id: 1, issue_no: '26100', game_type: 't14c', status: 'closed', sale_stop: '2026-10-27T10:00:00+08:00' };
  return { schema_version: 'football-pool/v2', issue, issue_state: 'closed', analysis_mode: 'historical',
    sf14_status: 'missing_predictions', rx9_status: 'ready', input_hash: 'a'.repeat(64),
    parameters: { budget: 256, strategy: 'balanced', issue_id: '1', pinned_orders: [], excluded_orders: [] },
    matches: [], missing_inputs: [{ match_order: 11, reason: '缺少合格完整预测组' }], warnings: [],
    full_combinations: { count: 0, total_cost: 0, combinations: [] },
    rx9: { selected_matches: [], combinations_count: 128, total_cost: 256,
      combinations: [{ selections: Array(9).fill('3'), all_correct_prob: .4 ** 9, expected_hits: 3.6 }],
      issue: { ...issue, id: 2, game_type: 'r9' }, missing_inputs: [] },
    probabilities: { hit14_prob: null, hit13_or_more_prob: null, rx9_prob: .05 }, data_as_of: '2026-10-27T10:00:00+08:00' };
}

describe('PoolPage corrected contracts', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.analyze.mockResolvedValue(result()); mocks.issues.mockResolvedValue({ issues: [] });
    mocks.plans.mockResolvedValue({ plans: [] });
    mocks.catalog.mockResolvedValue({ issues: [], total: 0, limit: 20, offset: 0 });
  });
  it('部分预测不足时仍展示任九，并明确区分历史参考', async () => {
    render(<PoolPage />);
    expect(await screen.findByText('历史期次复盘')).toBeInTheDocument();
    expect(screen.getByText(/不是当前投注推荐/)).toBeInTheDocument();
    expect(screen.getByText('14场：预测未齐；任九：可生成')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '任九' }));
    expect(screen.getByText('完整方案 128 注 · 实际成本 256 元')).toBeInTheDocument();
    expect(screen.getByText(/任九支持复式/)).toBeInTheDocument();
    expect(screen.getByText(/3.60 场/)).toBeInTheDocument();
    expect(screen.queryByText(/蒙特卡洛/)).not.toBeInTheDocument();
  });
  it('改预算后刷新失败，明确保留旧参数并禁止保存为新方案', async () => {
    render(<PoolPage />);
    await screen.findByText('历史期次复盘');
    fireEvent.change(screen.getByLabelText('每种玩法预算（元）'), { target: { value: '128' } });
    expect(screen.getByText(/与当前参数不同/)).toBeInTheDocument();
    mocks.analyze.mockRejectedValueOnce(new ApiError(503, '数据库暂不可用'));
    fireEvent.click(screen.getByRole('button', { name: '重新生成' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('上一份结果');
    expect(screen.getByText(/本结果预算 256 元/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '保存完整方案' })).toBeDisabled();
  });
  it('正常缺期次作为可读业务状态展示', async () => {
    mocks.analyze.mockResolvedValue({ ...result(), issue: null, issue_state: 'missing_issue', sf14_status: 'missing_issue', rx9_status: 'missing_issue',
      full_combinations: undefined, rx9: undefined, missing_inputs: [{ reason: '暂无已采集的体彩官方14场彩池' }] });
    render(<PoolPage />);
    expect(await screen.findByText(/暂无已采集的体彩官方14场彩池/)).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '保存完整方案' })).toBeDisabled();
  });
  it('显式保存带上输入摘要，读取列表更新', async () => {
    mocks.save.mockResolvedValue({ id: 7, snapshot_hash: 'a'.repeat(64) });
    render(<PoolPage />);
    await screen.findByText('历史期次复盘');
    fireEvent.click(screen.getByRole('button', { name: '保存完整方案' }));
    await waitFor(() => expect(mocks.save).toHaveBeenCalledWith({ ...result().parameters, input_hash: 'a'.repeat(64) }));
    expect(await screen.findByText(/方案 #7 已保存/)).toBeInTheDocument();
  });
  it('读取旧快照显示过期，导出使用原完整快照', async () => {
    mocks.plans.mockResolvedValue({ plans: [{ id: 8, issue: result().issue, parameters: result().parameters, created_at: '2026-10-27' }] });
    mocks.plan.mockResolvedValue({ id: 8, stale: true, snapshot: result() });
    render(<PoolPage />);
    fireEvent.click(await screen.findByRole('button', { name: /查看 #8/ }));
    expect(await screen.findByText('已保存方案 #8')).toBeInTheDocument();
    expect(screen.getByText(/已过期/)).toBeInTheDocument();
  });
});
