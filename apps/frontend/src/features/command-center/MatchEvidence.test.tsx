import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { MatchDetail, TodayMatch } from '../../core/types';
import MatchEvidence from './MatchEvidence';

const { detail, oddsSnapshots } = vi.hoisted(() => ({ detail: vi.fn(), oddsSnapshots: vi.fn() }));
vi.mock('../../core/apiClient', () => ({ api: { matches: { detail }, official: { oddsSnapshots } } }));
const match = { match_id: 11, home_team_name: '界面测试主队', away_team_name: '界面测试客队', league_name: '界面测试联赛', kickoff_time: '2026-07-12T19:35:00', match_status: 'Selling' } as TodayMatch;
function response(id = 11) {
  return { match: { id, home_team_name: match.home_team_name, away_team_name: match.away_team_name }, predictions: { models: [
    { model_name: '测试模型A', play_type: 'spf', predict_time: '2026-07-12T10:00:00', option_code: '3', model_probability: 0 },
    { model_name: '测试模型B', play_type: 'spf', predict_time: '2026-07-12T10:00:00', option_code: '3', model_probability: .8 },
  ] } } as MatchDetail;
}
beforeEach(() => { detail.mockReset(); oddsSnapshots.mockReset(); detail.mockResolvedValue(response()); oddsSnapshots.mockResolvedValue({ snapshots: [] }); });
describe('MatchEvidence shared by command center and matches', () => {
  it('shows zero probability, isolates model groups, and offers the correct deep link', async () => {
    render(<MatchEvidence match={match} />);
    expect(await screen.findByText('0.0%')).toBeInTheDocument();
    expect(screen.queryByText('80.0%')).not.toBeInTheDocument();
    const select = screen.getByLabelText('模型 / 玩法 / 预测时间');
    const options = within(select).getAllByRole('option');
    fireEvent.change(select, { target: { value: (options[1] as HTMLOptionElement).value } });
    expect(screen.getByText('80.0%')).toBeInTheDocument();
    expect(screen.queryByText('0.0%')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: '完整比赛详情' })).toHaveAttribute('href', '#/matches/11');
  });
  it('rejects a detail response belonging to another match', async () => {
    detail.mockResolvedValueOnce(response(12)); render(<MatchEvidence match={match} />);
    expect(await screen.findByText(/赛事 ID 不一致/)).toBeInTheDocument();
    expect(screen.queryByText('0.0%')).not.toBeInTheDocument();
  });
  it('ignores late old detail and odds after changing the selected ID', async () => {
    let resolveOld!: (value: MatchDetail) => void;
    let resolveOdds!: (value: unknown) => void;
    detail.mockReturnValueOnce(new Promise(resolve => { resolveOld = resolve; })).mockResolvedValueOnce({ ...response(12), predictions: { models: [] } });
    oddsSnapshots.mockReturnValueOnce(new Promise(resolve => { resolveOdds = resolve; })).mockResolvedValueOnce({ snapshots: [] });
    const view = render(<MatchEvidence key={11} match={match} />);
    await waitFor(() => expect(detail).toHaveBeenCalledWith(11));
    view.rerender(<MatchEvidence key={12} match={{ ...match, match_id: 12 }} />);
    await screen.findByText('暂无模型预测');
    await act(async () => { resolveOld(response()); resolveOdds({ snapshots: [{ match_id: 11, id: 1, play_type: 'spf', option_code: '3', sp_value: 1.23, snapshot_time: '2026-07-12T10:00:00', is_open: true }] }); });
    expect(screen.queryByText('0.0%')).not.toBeInTheDocument();
    expect(screen.queryByText('1.23')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: '完整比赛详情' })).toHaveAttribute('href', '#/matches/12');
  });
  it('keeps the last successful evidence and reports a manual refresh failure', async () => {
    render(<MatchEvidence match={match} />); await screen.findByText('0.0%');
    detail.mockRejectedValueOnce(new Error('详情网络失败'));
    fireEvent.click(screen.getAllByRole('button', { name: '刷新' })[0]);
    expect(await screen.findByText(/详情网络失败.*保留上次成功数据/)).toBeInTheDocument();
    expect(screen.getByText('0.0%')).toBeInTheDocument();
  });
  it('does not substitute model output for missing official odds or accept mismatched odds IDs', async () => {
    oddsSnapshots.mockResolvedValueOnce({ snapshots: [{ match_id: 12, id: 1, snapshot_time: '2026-07-12T10:00:00' }] });
    render(<MatchEvidence match={match} />);
    expect(await screen.findByText(/赔率赛事 ID 或快照不一致/)).toBeInTheDocument();
    expect(screen.queryByText('暂无官方赔率快照')).not.toBeInTheDocument();
  });
});
