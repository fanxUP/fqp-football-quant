import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import PoolFixtureCatalog from './PoolFixtureCatalog';
import type { PoolCatalogIssue, PoolCatalogPage, PoolCatalogDetail } from '../../core/types';

const mocks = vi.hoisted(() => ({ catalog: vi.fn(), catalogIssue: vi.fn() }));
vi.mock('../../core/apiClient', () => ({ api: { pool: mocks } }));
const issue: PoolCatalogIssue = {
  id: 7, issue_no: '26001', game_type: 'jq4', expected_matches: 4, total_matches: 4,
  stored_matches: 4, linked_matches: 2, pending_matches: 1, conflict_matches: 1,
  unique_fixtures: 2, source_verified: true, catalogue_complete: true,
  state: 'unknown', sale_stop: null, first_kickoff: '2026-10-30T20:00:00+08:00',
  last_kickoff: null,
};
const page = (issues = [issue], total = issues.length): PoolCatalogPage => ({ issues, total, offset: 0, limit: 20 });
const detail: PoolCatalogDetail = { issue, fixtures: [
  { match_order: 1, fixture_id: 9, official_match_id: null, identity_status: 'linked', identity_reason: null,
    league: '样本联赛', home_team: '主队A', away_team: '客队A', kickoff: '2026-10-30T20:00:00+08:00' },
  { match_order: 2, fixture_id: null, official_match_id: null, identity_status: 'pending', identity_reason: 'missing_typed_source_identity',
    league: '', home_team: '', away_team: '', kickoff: null },
  { match_order: 3, fixture_id: null, official_match_id: null, identity_status: 'conflict', identity_reason: 'source_identity_fields_conflict',
    league: '样本联赛', home_team: '主队B', away_team: '客队B', kickoff: null },
] };

describe('PoolFixtureCatalog', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.catalog.mockResolvedValue(page());
    mocks.catalogIssue.mockResolvedValue(detail);
  });

  it('四玩法入口及查询详情展示真实身份缺口，不将传统独有比赛当缺失', async () => {
    render(<PoolFixtureCatalog />);
    expect(screen.getByRole('option', { name: '6场半全场' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: '4场进球' })).toBeInTheDocument();
    fireEvent.click(await screen.findByRole('button', { name: /查看4场进球第26001期/ }));
    expect(await screen.findByText('主队A vs 客队A')).toBeInTheDocument();
    expect(screen.getByText('已关联 · 比赛 #9')).toBeInTheDocument();
    expect(screen.getAllByText('无竞彩关联').length).toBe(3);
    expect(screen.getByText('缺少可核实来源ID')).toBeInTheDocument();
    expect(screen.getByText('来源对阵信息冲突')).toBeInTheDocument();
    expect(screen.getByText(/赛季归属尚待核实/)).toBeInTheDocument();
    expect(screen.queryByText(/预测概率/)).not.toBeInTheDocument();
  });

  it('换玩法独立查询，并清除上期详情；日期按提交应用', async () => {
    render(<PoolFixtureCatalog />);
    fireEvent.click(await screen.findByRole('button', { name: /查看4场进球第26001期/ }));
    await screen.findByText('主队A vs 客队A');
    mocks.catalog.mockResolvedValue(page([]));
    fireEvent.change(screen.getByLabelText('查询玩法'), { target: { value: 'bqc6' } });
    await waitFor(() => expect(mocks.catalog).toHaveBeenLastCalledWith(expect.objectContaining({ game_type: 'bqc6', offset: 0 })));
    expect(screen.queryByText('主队A vs 客队A')).not.toBeInTheDocument();
    const before = mocks.catalog.mock.calls.length;
    fireEvent.change(screen.getByLabelText('开球起始日期'), { target: { value: '2026-10-30' } });
    expect(mocks.catalog).toHaveBeenCalledTimes(before);
    fireEvent.click(screen.getByRole('button', { name: '查询期次' }));
    await waitFor(() => expect(mocks.catalog).toHaveBeenLastCalledWith(expect.objectContaining({ game_type: 'bqc6', date_from: '2026-10-30' })));
    expect(await screen.findByText(/暂无符合条件的已采集期次/)).toBeInTheDocument();
  });

  it('列表失败可以重试，空记录不显示系统异常', async () => {
    mocks.catalog.mockRejectedValueOnce(new Error('暂时不可用')).mockResolvedValue(page([]));
    render(<PoolFixtureCatalog />);
    expect(await screen.findByRole('alert')).toHaveTextContent('期次查询失败：暂时不可用');
    fireEvent.click(screen.getByRole('button', { name: '重试期次查询' }));
    expect(await screen.findByText(/暂无符合条件的已采集期次/)).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('分页仅查询下一页，修改玩法回到第一页', async () => {
    mocks.catalog.mockResolvedValue(page([issue], 41));
    render(<PoolFixtureCatalog />);
    await screen.findByRole('button', { name: /查看4场进球第26001期/ });
    fireEvent.click(screen.getByRole('button', { name: '下一页期次' }));
    await waitFor(() => expect(mocks.catalog).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 20 })));
    fireEvent.change(screen.getByLabelText('查询玩法'), { target: { value: 'r9' } });
    await waitFor(() => expect(mocks.catalog).toHaveBeenLastCalledWith(expect.objectContaining({ game_type: 'r9', offset: 0 })));
  });

  it('快速切换后较慢的旧详情不能覆盖新选择', async () => {
    let finish!: (value: PoolCatalogDetail) => void;
    mocks.catalog.mockResolvedValue(page([issue, { ...issue, id: 8, game_type: 'bqc6' }]));
    mocks.catalogIssue.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }))
      .mockResolvedValueOnce({ issue: { ...issue, id: 8, game_type: 'bqc6' }, fixtures: [] });
    render(<PoolFixtureCatalog />);
    fireEvent.click(await screen.findByRole('button', { name: /查看4场进球第26001期/ }));
    fireEvent.click(screen.getByRole('button', { name: /查看6场半全场第26001期/ }));
    expect(await screen.findByText('6场半全场 · 第26001期')).toBeInTheDocument();
    await act(async () => { finish(detail); });
    expect(screen.queryByText('主队A vs 客队A')).not.toBeInTheDocument();
  });

  it('详情失败保留期次列表供重试，反向日期不发送请求', async () => {
    mocks.catalogIssue.mockRejectedValueOnce(new Error('加载失败')).mockResolvedValue(detail);
    render(<PoolFixtureCatalog />);
    fireEvent.click(await screen.findByRole('button', { name: /查看4场进球第26001期/ }));
    expect(await screen.findByRole('alert')).toHaveTextContent('比赛列表加载失败');
    fireEvent.click(screen.getByRole('button', { name: '重试比赛列表' }));
    expect(await screen.findByText('主队A vs 客队A')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('开球起始日期'), { target: { value: '2026-11-01' } });
    fireEvent.change(screen.getByLabelText('开球结束日期'), { target: { value: '2026-10-30' } });
    const before = mocks.catalog.mock.calls.length;
    fireEvent.click(screen.getByRole('button', { name: '查询期次' }));
    expect(screen.getByRole('alert')).toHaveTextContent('起始日期不能晚于结束日期');
    expect(mocks.catalog).toHaveBeenCalledTimes(before);
  });

  it('较慢的旧列表不能覆盖换玩法后的新列表', async () => {
    let finish!: (value: PoolCatalogPage) => void;
    mocks.catalog.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }))
      .mockResolvedValueOnce(page([]));
    render(<PoolFixtureCatalog />);
    fireEvent.change(screen.getByLabelText('查询玩法'), { target: { value: 'r9' } });
    await screen.findByText(/暂无符合条件的已采集期次/);
    await act(async () => { finish(page()); });
    expect(screen.queryByRole('button', { name: /查看4场进球第26001期/ })).not.toBeInTheDocument();
    expect(screen.getByLabelText('查询玩法')).toHaveValue('r9');
  });

  it('有期次但没有比赛材料时显示缺项，不隐藏该期', async () => {
    mocks.catalogIssue.mockResolvedValue({ issue: { ...issue, catalogue_complete: false, stored_matches: 0, unique_fixtures: 0 }, fixtures: [] });
    render(<PoolFixtureCatalog />);
    fireEvent.click(await screen.findByRole('button', { name: /查看4场进球第26001期/ }));
    expect(await screen.findByText('该期尚未采集到比赛材料。')).toBeInTheDocument();
    expect(screen.getByText(/场序或玩法来源尚未核实完整/)).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
