import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import CommandCenter from './CommandCenter';
const api = vi.hoisted(() => ({ matches: { active: vi.fn(), detail: vi.fn() }, official: { oddsSnapshots: vi.fn() } }));
vi.mock('../../core/apiClient', () => ({ api }));
vi.mock('./PitchScene', () => ({ default: ({ onSelect }: { onSelect: (id: number) => void }) => <button onClick={() => onSelect(2)}>场景选择赛事2</button> }));
const matches = [1, 2].map(id => ({ match_id: id, home_team_name: `主队${id}`, away_team_name: `客队${id}`, league_name: '联赛', kickoff_time: '2026-10-08T20:00:00', match_status: 'scheduled', match_num_str: `周四00${id}` }));
const detail = (id: number) => ({ match: { id, home_team_name: `主队${id}`, away_team_name: `客队${id}` }, predictions: null, scores: null, feature_snapshot: null });
describe('CommandCenter real match selection', () => {
  beforeEach(() => {
    vi.clearAllMocks(); api.matches.active.mockResolvedValue({ matches, total: 2 });
    api.matches.detail.mockImplementation((id: number) => Promise.resolve(detail(id)));
    api.official.oddsSnapshots.mockResolvedValue({ snapshots: [], total: 0 });
  });
  afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
  it('keeps full 2D navigation without WebGL', async () => {
    render(<CommandCenter />);
    fireEvent.click(await screen.findByRole('button', { name: /周四002.*主队2.*客队2/ }));
    await waitFor(() => expect(api.matches.detail).toHaveBeenCalledWith(2));
    expect(screen.getByRole('link', { name: '完整比赛详情' })).toHaveAttribute('href', '#/matches/2');
    expect(screen.getByText('暂无模型预测')).toBeInTheDocument();
    expect(api.official.oddsSnapshots).toHaveBeenCalledWith(2);
  });
  it('synchronizes selection from the scene back to the 2D list', async () => {
    vi.stubGlobal('WebGL2RenderingContext', class {});
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ getExtension: () => null } as unknown as WebGL2RenderingContext);
    render(<CommandCenter />);
    fireEvent.click(await screen.findByRole('button', { name: '场景选择赛事2' }));
    await waitFor(() => expect(screen.getByRole('button', { name: /周四002.*主队2.*客队2/ })).toHaveAttribute('aria-pressed', 'true'));
    expect(screen.getByRole('link', { name: '完整比赛详情' })).toHaveAttribute('href', '#/matches/2');
  });
  it('rejects mismatched detail IDs', async () => {
    api.matches.detail.mockResolvedValue(detail(99)); render(<CommandCenter />);
    expect(await screen.findByText(/赛事 ID 不一致/)).toBeInTheDocument();
  });
  it('ignores a late response for a previous selection', async () => {
    let resolve!: (value: unknown) => void;
    api.matches.detail.mockImplementation((id: number) => id === 1 ? new Promise(r => { resolve = r; }) : Promise.resolve(detail(2)));
    render(<CommandCenter />);
    fireEvent.click(await screen.findByRole('button', { name: /周四002.*主队2.*客队2/ }));
    await screen.findByText('暂无模型预测');
    await act(async () => { resolve(detail(1)); });
    expect(screen.getByRole('link', { name: '完整比赛详情' })).toHaveAttribute('href', '#/matches/2');
  });
  it('distinguishes failed and empty responses', async () => {
    api.matches.active.mockRejectedValue(new Error('网络异常')); render(<CommandCenter />);
    expect(await screen.findByText(/网络异常/)).toBeInTheDocument();
    expect(screen.queryByText('暂无未结束比赛')).not.toBeInTheDocument();
  });
});
