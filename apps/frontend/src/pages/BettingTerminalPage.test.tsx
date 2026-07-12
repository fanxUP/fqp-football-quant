import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import BettingTerminalPage from './BettingTerminalPage';
import type { BettingMatch, CalculateItem } from '../core/types';

const completeOdds = {
  spf: {
    is_single_allowed: true,
    is_pass_allowed: true,
    options: [
      { option_code: '3', option_name: '主胜', sp_value: 2.04 },
      { option_code: '1', option_name: '平', sp_value: 2.95 },
      { option_code: '0', option_name: '主负', sp_value: 3.33 },
    ],
  },
  rqspf: {
    handicap: -1,
    is_single_allowed: false,
    is_pass_allowed: true,
    options: [
      { option_code: '3', option_name: '让主胜', sp_value: 4.8 },
      { option_code: '1', option_name: '让平', sp_value: 3.33 },
      { option_code: '0', option_name: '让主负', sp_value: 1.61 },
    ],
  },
  bf: {
    is_single_allowed: true,
    is_pass_allowed: true,
    options: [
      { option_code: '1:0', option_name: '1:0', sp_value: 8.5 },
      { option_code: '2:0', option_name: '2:0', sp_value: 14 },
    ],
  },
  zjq: {
    is_single_allowed: true,
    is_pass_allowed: true,
    options: [
      { option_code: '0', option_name: '0球', sp_value: 9 },
      { option_code: '1', option_name: '1球', sp_value: 4.8 },
    ],
  },
  bqc: {
    is_single_allowed: true,
    is_pass_allowed: true,
    options: [
      { option_code: '33', option_name: '胜/胜', sp_value: 3.2 },
      { option_code: '31', option_name: '胜/平', sp_value: 12 },
    ],
  },
};

const firstMatch: BettingMatch = {
  match_id: 901,
  business_date: '2026-07-12',
  league_name: '韩国职业联赛',
  home_team_name: '首尔FC',
  away_team_name: '江原FC',
  kickoff_time: '2026-07-13T01:15:00',
  match_status: 'scheduled',
  match_num_str: '周日203',
  odds: completeOdds,
};

const secondMatch: BettingMatch = {
  ...firstMatch,
  match_id: 902,
  league_name: '瑞典超级联赛',
  home_team_name: '马尔默',
  away_team_name: '哥德堡',
  kickoff_time: '2026-07-14T01:00:00',
  match_num_str: '周一201',
  odds: {
    ...completeOdds,
    spf: {
      ...completeOdds.spf,
      options: [
        { option_code: '3', option_name: '主胜', sp_value: 1.67 },
        { option_code: '1', option_name: '平', sp_value: 3.76 },
        { option_code: '0', option_name: '主负', sp_value: 3.78 },
      ],
    },
  },
};

const apiMocks = vi.hoisted(() => ({
  matches: vi.fn(),
  calculate: vi.fn(),
  createTicket: vi.fn(),
}));

const calculateResponse = async (body: { items: CalculateItem[]; pass_type: string; multiple: number }) => {
  const groups = new Map<number, CalculateItem[]>();
  body.items.forEach((item) => groups.set(item.match_id, [...(groups.get(item.match_id) ?? []), item]));
  const singleItems = body.items.filter((item) => item.is_single_allowed);
  const betCount = body.pass_type === 'single'
    ? singleItems.length
    : [...groups.values()].reduce((count, group) => count * group.length, 1);
  return {
    pass_type: body.pass_type,
    multiple: body.multiple,
    bet_count: betCount,
    total_cost: betCount * 2 * body.multiple,
    max_prize: betCount * 8.2 * body.multiple,
    match_count: groups.size,
    selection_count: body.items.length,
    combinations: [],
    available_pass_types: groups.size >= 2 ? ['single', '2x1'] : ['single'],
  };
};
const ticketResponse = {
  status: 'ok',
  ticketUid: 'real:88',
  legacyId: 88,
  owner: 'me' as const,
  kind: 'real' as const,
  source: 'manual',
  stake: 4,
  maxPrize: 16.4,
  betCount: 2,
  route: '/betting?tab=tickets',
};

vi.mock('../core/apiClient', () => ({
  api: {
    bettingTerminal: { matches: apiMocks.matches, calculate: apiMocks.calculate },
    liveRecommendations: vi.fn(async () => ({ recommendations: [], total: 0, status: 'ok' })),
    betting: { createTicket: apiMocks.createTicket, ocrUpload: vi.fn() },
  },
}));

vi.mock('../shared/components/Toast', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), warning: vi.fn() }),
}));

describe('BettingTerminalPage complete replacement', () => {
  beforeEach(() => {
    apiMocks.matches.mockReset().mockResolvedValue({ matches: [firstMatch, secondMatch], total: 2 });
    apiMocks.calculate.mockReset().mockImplementation(calculateResponse);
    apiMocks.createTicket.mockReset().mockResolvedValue(ticketResponse);
  });

  it('renders the standalone Sporttery terminal structure instead of the legacy workbench', async () => {
    render(<BettingTerminalPage />);

    const terminal = await screen.findByRole('region', { name: '竞彩足球模拟试玩投注器' });
    expect(within(terminal).getByRole('heading', { name: '竞彩足球' })).toBeInTheDocument();
    expect(within(terminal).getByText('模拟试玩')).toBeInTheDocument();
    expect(within(terminal).getByRole('button', { name: '刷新赔率' })).toBeInTheDocument();
    expect(within(terminal).getByRole('button', { name: '混合过关' })).toBeInTheDocument();
    expect(within(terminal).getByRole('button', { name: '游戏规则' })).toBeInTheDocument();
    expect(within(terminal).getByRole('button', { name: '筛选' })).toBeInTheDocument();
    expect(within(terminal).getByText('周日203')).toBeInTheDocument();
    expect(within(terminal).getAllByLabelText('胜平负支持单场，支持过关')[0]).toHaveTextContent('单过');
    expect(within(terminal).getAllByLabelText('让球胜平负不支持单场，支持过关')[0]).toHaveTextContent('−过');
    expect(screen.queryByLabelText('推荐单')).not.toBeInTheDocument();
    expect(screen.queryByText('OCR 识别')).not.toBeInTheDocument();
  });

  it('opens the complete five-play selector with single and pass flags', async () => {
    render(<BettingTerminalPage />);
    const matchCard = await screen.findByRole('article', { name: '周日203 首尔FC 对 江原FC' });
    fireEvent.click(within(matchCard).getByRole('button', { name: '全部游戏' }));

    const dialog = screen.getByRole('dialog', { name: '周日203 全部游戏' });
    for (const title of ['胜平负', '让球胜平负', '比分', '总进球', '半全场']) {
      expect(within(dialog).getByRole('heading', { name: title })).toBeInTheDocument();
    }
    expect(within(dialog).getAllByText('单场').length).toBeGreaterThan(0);
    expect(within(dialog).getAllByText('过关')).toHaveLength(5);
  });

  it('expands same-match alternatives and links selection, pass, amount, and prize', async () => {
    render(<BettingTerminalPage />);
    const first = await screen.findByRole('article', { name: '周日203 首尔FC 对 江原FC' });
    const second = screen.getByRole('article', { name: '周一201 马尔默 对 哥德堡' });

    fireEvent.click(within(first).getByRole('button', { name: '胜平负 主胜 2.04' }));
    fireEvent.click(within(first).getByRole('button', { name: '让球胜平负 主胜 4.80' }));
    fireEvent.click(within(second).getByRole('button', { name: '胜平负 主胜 1.67' }));

    const slip = await screen.findByRole('complementary', { name: '投注单' });
    await waitFor(() => expect(within(slip).getByText((_, node) => node?.textContent === '共计: 2 注 4.00 元')).toBeInTheDocument());
    expect(within(slip).getByText('2', { selector: '.selected-count strong' })).toBeInTheDocument();
    expect(within(slip).getByText((_, node) => node?.textContent === '理论最高奖金: 16.40元')).toBeInTheDocument();
    expect(within(slip).getByRole('button', { name: '2关' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(first).getByRole('button', { name: '已选 2项' })).toBeInTheDocument();
  });

  it('provides the 1-8 pass grid, clamps multiple to 50, and archives a confirmed ticket', async () => {
    render(<BettingTerminalPage />);
    const first = await screen.findByRole('article', { name: '周日203 首尔FC 对 江原FC' });
    const second = screen.getByRole('article', { name: '周一201 马尔默 对 哥德堡' });
    fireEvent.click(within(first).getByRole('button', { name: '胜平负 主胜 2.04' }));
    fireEvent.click(within(second).getByRole('button', { name: '胜平负 主胜 1.67' }));

    const slip = await screen.findByRole('complementary', { name: '投注单' });
    const passGrid = within(slip).getByRole('group', { name: '过关方式' });
    expect(within(passGrid).getAllByRole('button')).toHaveLength(8);
    expect(within(passGrid).getByRole('button', { name: '3关' })).toBeDisabled();

    for (let index = 1; index < 50; index += 1) {
      fireEvent.click(within(slip).getByRole('button', { name: '增加倍数' }));
    }
    expect(within(slip).getByLabelText('当前倍数')).toHaveTextContent('50');
    expect(within(slip).getByRole('button', { name: '增加倍数' })).toBeDisabled();

    await waitFor(() => expect(within(slip).getByRole('button', { name: '确定' })).toBeEnabled());
    fireEvent.click(within(slip).getByRole('button', { name: '确定' }));
    await waitFor(() => expect(apiMocks.createTicket).toHaveBeenCalledTimes(1));
    expect(apiMocks.createTicket.mock.calls[0][0]).toMatchObject({ pass_type: '2x1', multiple: 50 });
    expect(await screen.findByRole('dialog', { name: '模拟投注明细' })).toHaveTextContent('已保存到我的彩票');
  });

  it('filters leagues and can restrict the list to single-play markets', async () => {
    render(<BettingTerminalPage />);
    const terminal = await screen.findByRole('region', { name: '竞彩足球模拟试玩投注器' });
    fireEvent.click(within(terminal).getByRole('button', { name: '筛选' }));

    const dialog = screen.getByRole('dialog', { name: '筛选比赛' });
    fireEvent.change(within(dialog).getByLabelText('联赛'), { target: { value: '瑞典超级联赛' } });
    fireEvent.click(within(dialog).getByRole('button', { name: '完成' }));

    expect(within(terminal).queryByText('周日203')).not.toBeInTheDocument();
    expect(within(terminal).getByText('周一201')).toBeInTheDocument();
  });

  it('does not allow selection when the official market supports neither single nor pass betting', async () => {
    apiMocks.matches.mockResolvedValue({
      matches: [{
        ...firstMatch,
        odds: {
          ...completeOdds,
          spf: { ...completeOdds.spf, is_single_allowed: false, is_pass_allowed: false },
        },
      }],
      total: 1,
    });

    render(<BettingTerminalPage />);

    const matchCard = await screen.findByRole('article', { name: '周日203 首尔FC 对 江原FC' });
    expect(within(matchCard).getByRole('button', { name: '胜平负 主胜 2.04' })).toBeDisabled();
    expect(within(matchCard).getByLabelText('胜平负不支持单场，不支持过关')).toHaveTextContent('−−');
  });
});
