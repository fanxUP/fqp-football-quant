import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import MatchDetailDrawer from './MatchDetailDrawer';

const mocks = vi.hoisted(() => ({ detail: vi.fn(), detailSection: vi.fn() }));
vi.mock('../../core/apiClient', () => ({ api: { matches: mocks } }));

function fixture(id = 101) {
  return {
    match: { id, home_team_name: `主${id}`, away_team_name: `客${id}`, kickoff_time: '2026-10-29T20:00:00', match_status: 'scheduled', sale_status: 'selling', league_name: '测试联赛' },
    scores: null,
    teams: { home: { id: 1, name_cn: `主${id}`, name_en: null, short_name: null, country: null }, away: { id: 2, name_cn: `客${id}`, name_en: null, short_name: null, country: null } },
    feature_snapshot: null,
    predictions: { models: [{ model_name: '测试模型', play_type: 'spf', option_code: '3', model_probability: 0, market_probability: null, ev: 0 }], best_ev_model: '测试模型', best_ev_option: '3' },
    h2h: { total_matches: 0, home_wins: 0, draws: 0, away_wins: 0, recent_matches: [] },
    form: { home: [], away: [] }, lineups: { home: null, away: null }, standings: [], injuries: [],
  };
}

function section(id: number, name: string) {
  const all = fixture(id);
  const base = { match: all.match, teams: all.teams, scores: all.scores };
  switch (name) {
    case 'core': return { ...base, predictions: all.predictions, feature_snapshot: all.feature_snapshot };
    case 'overview': return { ...base, form: all.form, h2h: all.h2h };
    case 'data': return { ...base, lineups: all.lineups, standings: all.standings };
    case 'injuries': return { ...base, injuries: all.injuries };
    default: throw new Error('Unexpected section');
  }
}

beforeEach(() => {
  mocks.detail.mockReset().mockImplementation(async id => fixture(id));
  mocks.detailSection.mockReset().mockImplementation(async (id, name) => section(id, name));
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe('MatchDetailDrawer section reads', () => {
  it('shows core before slow overview and requests other sections only when selected', async () => {
    let resolve!: (value: unknown) => void;
    mocks.detailSection.mockImplementation((id, name) => name === 'overview' ? new Promise(r => { resolve = r; }) : Promise.resolve(section(id, name)));
    render(<MatchDetailDrawer matchId={101} onClose={vi.fn()} />);
    await screen.findByText('主101 VS 客101');
    await waitFor(() => expect(mocks.detailSection).toHaveBeenCalledWith(101, 'overview'));
    expect(mocks.detail).not.toHaveBeenCalled();
    expect(mocks.detailSection.mock.calls.map(call => call[1])).toEqual(['core', 'overview']);
    fireEvent.click(screen.getByRole('button', { name: /赔率/ }));
    expect(screen.getByText(/测试模型/)).toBeInTheDocument();
    expect(screen.getByText('0%')).toBeInTheDocument();
    expect(mocks.detailSection).toHaveBeenCalledTimes(2);
    await act(async () => { resolve(section(101, 'overview')); });
    fireEvent.click(screen.getByRole('button', { name: /赛况/ }));
    await screen.findByText('暂无赛况数据');
  });

  it('keeps empty tabs discoverable and reuses the loaded section while open', async () => {
    render(<MatchDetailDrawer matchId={101} onClose={vi.fn()} />);
    await screen.findByText('暂无赛况数据');
    fireEvent.click(screen.getByRole('button', { name: /数据$/ }));
    await screen.findByRole('button', { name: '刷新比赛数据' });
    await waitFor(() => expect(mocks.detailSection).toHaveBeenCalledWith(101, 'data'));
    fireEvent.click(screen.getByRole('button', { name: /伤停$/ }));
    await screen.findByText(/尚无可用伤停记录/);
    fireEvent.click(screen.getByRole('button', { name: /数据$/ }));
    expect(mocks.detailSection.mock.calls.filter(call => call[1] === 'data')).toHaveLength(1);
    expect(mocks.detailSection.mock.calls.filter(call => call[1] === 'injuries')).toHaveLength(1);
  });

  it('isolates a failed extension and supports retry without rereading core', async () => {
    mocks.detailSection.mockImplementation(async (id, name) => {
      if (name === 'overview') throw new Error('赛况暂时失败');
      return section(id, name);
    });
    render(<MatchDetailDrawer matchId={101} onClose={vi.fn()} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('赛况暂时失败');
    expect(screen.getByText('主101 VS 客101')).toBeInTheDocument();
    mocks.detailSection.mockImplementation(async (id, name) => section(id, name));
    fireEvent.click(screen.getByRole('button', { name: '刷新赛况' }));
    await screen.findByText('暂无赛况数据');
    expect(mocks.detailSection.mock.calls.filter(call => call[1] === 'core')).toHaveLength(1);
  });

  it('rejects a section whose match identity changed since the core read', async () => {
    mocks.detailSection.mockImplementation(async (id, name) => {
      const data = section(id, name);
      if (name === 'overview') data.match = { ...data.match, kickoff_time: '2026-10-30T20:00:00' };
      return data;
    });
    render(<MatchDetailDrawer matchId={101} onClose={vi.fn()} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('比赛信息已变化');
    expect(screen.queryByText('暂无赛况数据')).not.toBeInTheDocument();
  });

  it('ignores late core and section results after a match switch or close', async () => {
    let resolveOld!: (value: unknown) => void;
    mocks.detailSection.mockImplementation((id, name) => id === 101 ? new Promise(r => { resolveOld = r; }) : Promise.resolve(section(id, name)));
    const { rerender } = render(<MatchDetailDrawer matchId={101} onClose={vi.fn()} />);
    rerender(<MatchDetailDrawer matchId={102} onClose={vi.fn()} />);
    await screen.findByText('主102 VS 客102');
    await act(async () => { resolveOld(section(101, 'core')); });
    expect(screen.queryByText('主101 VS 客101')).not.toBeInTheDocument();
    rerender(<MatchDetailDrawer matchId={null} onClose={vi.fn()} />);
    expect(screen.queryByText('主102 VS 客102')).not.toBeInTheDocument();
  });

  it('does not start extension requests when core fails and retries explicitly', async () => {
    mocks.detailSection.mockRejectedValueOnce(new Error('基础读取失败'));
    render(<MatchDetailDrawer matchId={101} onClose={vi.fn()} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('基础读取失败');
    expect(mocks.detailSection).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: '刷新比赛与预测' }));
    await screen.findByText('主101 VS 客101');
    await screen.findByText('暂无赛况数据');
  });

  it('ignores a delayed old-match extension after core for the next match has loaded', async () => {
    let resolve!: (value: unknown) => void;
    mocks.detailSection.mockImplementation((id, name) => id === 101 && name === 'overview' ? new Promise(r => { resolve = r; }) : Promise.resolve(section(id, name)));
    const { rerender } = render(<MatchDetailDrawer matchId={101} onClose={vi.fn()} />);
    await waitFor(() => expect(mocks.detailSection).toHaveBeenCalledWith(101, 'overview'));
    rerender(<MatchDetailDrawer matchId={102} onClose={vi.fn()} />);
    await screen.findByText('主102 VS 客102');
    await act(async () => { resolve(section(101, 'overview')); });
    expect(screen.queryByText('主101 VS 客101')).not.toBeInTheDocument();
    expect(screen.getByText('主102 VS 客102')).toBeInTheDocument();
  });

  it('retains loaded extension data after a failed manual refresh', async () => {
    mocks.detailSection.mockImplementation(async (id, name) => name === 'overview' ? {
      ...section(id, name), form: { home: [{ date: '2026-10-20', opponent: '样本对手', status: 'W', is_home: true, goals_for: 1, goals_against: 0 }], away: [] },
    } : section(id, name));
    render(<MatchDetailDrawer matchId={101} onClose={vi.fn()} />);
    await screen.findByText('比赛近况');
    mocks.detailSection.mockRejectedValueOnce(new Error('刷新失败'));
    fireEvent.click(screen.getByRole('button', { name: '刷新赛况' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('保留本查询上次成功数据');
    expect(screen.getByText('比赛近况')).toBeInTheDocument();
  });

  it('reloads extensions when a manual core refresh changes the kickoff identity', async () => {
    let changed = false;
    mocks.detailSection.mockImplementation(async (id, name) => {
      const value = section(id, name);
      if (changed) value.match = { ...value.match, kickoff_time: '2026-10-30T20:00:00' };
      return value;
    });
    render(<MatchDetailDrawer matchId={101} onClose={vi.fn()} />);
    await screen.findByText('暂无赛况数据');
    changed = true;
    fireEvent.click(screen.getByRole('button', { name: '刷新比赛与预测' }));
    await screen.findByText('2026-10-30 20:00');
    await waitFor(() => expect(mocks.detailSection.mock.calls.filter(call => call[1] === 'overview')).toHaveLength(2));
    await screen.findByText('暂无赛况数据');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('mounts the drawer above page animation containers and keeps keyboard focus inside', async () => {
    const previousOverflow = document.body.style.overflow;
    const trigger = document.createElement('button');
    document.body.appendChild(trigger);
    trigger.focus();
    const { container, unmount } = render(<MatchDetailDrawer matchId={101} onClose={vi.fn()} />);
    await screen.findByText('暂无赛况数据');
    const dialog = screen.getByRole('dialog', { name: '主101 VS 客101' });
    expect(container.contains(dialog)).toBe(false);
    expect(document.body.style.overflow).toBe('hidden');
    const close = screen.getByRole('button', { name: '关闭比赛详情' });
    await waitFor(() => expect(close).toHaveFocus());
    fireEvent.keyDown(close, { key: 'Tab', shiftKey: true });
    expect(screen.getByRole('button', { name: '刷新赛况' })).toHaveFocus();
    fireEvent.keyDown(document.activeElement!, { key: 'Tab' });
    expect(close).toHaveFocus();
    unmount();
    expect(document.body.style.overflow).toBe(previousOverflow);
    expect(trigger).toHaveFocus();
    trigger.remove();
  });

  it('reuses a recent tab but refreshes it when selected again after one minute', async () => {
    let now = Date.now();
    vi.spyOn(Date, 'now').mockImplementation(() => now);
    render(<MatchDetailDrawer matchId={101} onClose={vi.fn()} />);
    await screen.findByText('暂无赛况数据');
    now += 61_000;
    fireEvent.click(screen.getByRole('button', { name: /赔率/ }));
    fireEvent.click(screen.getByRole('button', { name: /赛况/ }));
    await waitFor(() => expect(mocks.detailSection.mock.calls.filter(call => call[1] === 'overview')).toHaveLength(2));
    await waitFor(() => expect(screen.getByRole('button', { name: '刷新赛况' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: /赔率/ }));
    fireEvent.click(screen.getByRole('button', { name: /赛况/ }));
    expect(mocks.detailSection.mock.calls.filter(call => call[1] === 'overview')).toHaveLength(2);
  });
});
