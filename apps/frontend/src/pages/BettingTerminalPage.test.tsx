import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import BettingTerminalPage from './BettingTerminalPage';
import type { BettingMatch, CalculateItem, LiveRecommendation } from '../core/types';

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

const scoreDisplayCodes = [
  '1:0', '2:0', '2:1', '3:0', '3:1',
  '3:2', '4:0', '4:1', '4:2', '5:0',
  '5:1', '5:2', 'other_h',
  '0:0', '1:1', '2:2', '3:3', 'other_d',
  '0:1', '0:2', '1:2', '0:3', '1:3',
  '2:3', '0:4', '1:4', '2:4', '0:5',
  '1:5', '2:5', 'other_a',
];

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

const thirdMatch: BettingMatch = {
  ...secondMatch,
  match_id: 903,
  league_name: '挪威超级联赛',
  home_team_name: '罗森博格',
  away_team_name: '维京',
  kickoff_time: '2026-07-14T02:00:00',
  match_num_str: '周一202',
};

const recommendation: LiveRecommendation = {
  prediction_id: 10,
  match_id: firstMatch.match_id,
  play_type: 'spf',
  play_type_name: '胜平负',
  option_code: '3',
  option_name: '主胜',
  model_probability: 0.62,
  market_probability: 0.49,
  fair_odds: 2.04,
  ev: 0.13,
  edge: 0.12,
  confidence: 0.73,
  predict_time: '2026-07-12T09:00:00',
  model_name: 'xgb-main',
  home_team: firstMatch.home_team_name,
  away_team: firstMatch.away_team_name,
  league: firstMatch.league_name,
  kickoff_time: firstMatch.kickoff_time,
  match_status: firstMatch.match_status,
  match_num_str: firstMatch.match_num_str ?? null,
  ht_home_goals: null,
  ht_away_goals: null,
  ft_home_goals: null,
  ft_away_goals: null,
  et_home_goals: null,
  et_away_goals: null,
  pk_home_goals: null,
  pk_away_goals: null,
  spf_result: null,
  rqspf_result: null,
  total_goals_result: null,
  score_result: null,
  half_full_result: null,
};

const apiMocks = vi.hoisted(() => ({
  matches: vi.fn(),
  calculate: vi.fn(),
  createTicket: vi.fn(),
  recommendations: vi.fn(),
}));

const calculateResponse = async (body: { items: CalculateItem[]; pass_type: string; multiple: number }) => {
  const groups = new Map<number, CalculateItem[]>();
  body.items.forEach((item) => groups.set(item.match_id, [...(groups.get(item.match_id) ?? []), item]));
  const singleItems = body.items.filter((item) => item.is_single_allowed);
  const groupedItems = [...groups.values()];
  const countStraightPass = (requiredMatches: number): number => {
    let total = 0;
    const visit = (start: number, remaining: number, weight: number) => {
      if (remaining === 0) {
        total += weight;
        return;
      }
      for (let index = start; index <= groupedItems.length - remaining; index += 1) {
        visit(index + 1, remaining - 1, weight * groupedItems[index].length);
      }
    };
    visit(0, requiredMatches, 1);
    return total;
  };
  const passTypes = body.pass_type.split(',');
  const betCount = passTypes.reduce((total, passType) => {
    if (passType === 'single') return total + singleItems.length;
    return total + countStraightPass(Number.parseInt(passType.split('x')[0], 10));
  }, 0);
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
    liveRecommendations: apiMocks.recommendations,
    betting: { createTicket: apiMocks.createTicket, ocrUpload: vi.fn() },
  },
}));

vi.mock('../shared/components/Toast', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), warning: vi.fn() }),
}));

describe('BettingTerminalPage desktop workbench', () => {
  beforeEach(() => {
    apiMocks.matches.mockReset().mockResolvedValue({ matches: [firstMatch, secondMatch], total: 2 });
    apiMocks.calculate.mockReset().mockImplementation(calculateResponse);
    apiMocks.createTicket.mockReset().mockResolvedValue(ticketResponse);
    apiMocks.recommendations.mockReset().mockResolvedValue({ recommendations: [recommendation], total: 1, status: 'ok' });
  });

  it('keeps recommendation, new betting widget, and ticket preview as three linked desktop panels', async () => {
    render(<BettingTerminalPage />);

    const recommendationPanel = await screen.findByLabelText('推荐投注');
    const widgetPanel = screen.getByLabelText('投注器');
    const previewPanel = screen.getByLabelText('票面预览');
    const terminal = within(widgetPanel).getByRole('region', { name: '竞彩足球模拟试玩投注器' });
    expect(within(widgetPanel).getByRole('heading', { name: '投注器' })).toBeInTheDocument();
    expect(within(widgetPanel).queryByRole('heading', { name: '竞彩足球' })).not.toBeInTheDocument();
    expect(widgetPanel.querySelector('.sporttery-hero')).not.toBeInTheDocument();
    expect(within(terminal).getByRole('button', { name: '刷新赔率' })).toBeInTheDocument();
    expect(within(terminal).getByRole('button', { name: '混合过关' })).toBeInTheDocument();
    expect(within(terminal).getByRole('button', { name: '游戏规则' })).toBeInTheDocument();
    expect(within(terminal).getByRole('button', { name: '筛选' })).toBeInTheDocument();
    expect(within(terminal).getByText('周日203')).toBeInTheDocument();
    expect(within(terminal).getAllByLabelText('胜平负支持单场，支持过关')[0]).toHaveTextContent('单过');
    expect(within(terminal).getAllByLabelText('让球胜平负不支持单场，支持过关')[0]).toHaveTextContent('−过');
    expect(within(previewPanel).getByText('等待投注器生成票面')).toBeInTheDocument();

    fireEvent.click(within(recommendationPanel).getByRole('button', { name: '加入 主胜' }));

    await waitFor(() => expect(within(terminal).getByRole('button', { name: '胜平负 主胜 2.04' })).toHaveClass('is-selected'));
    expect(within(previewPanel).getByText('首尔FC vs 江原FC')).toBeInTheDocument();
    expect(within(previewPanel).getAllByText('推荐投注').length).toBeGreaterThan(0);
  });

  it('matches model 3/1/0 recommendation codes to official h/d/a options', async () => {
    apiMocks.matches.mockResolvedValue({
      matches: [{
        ...firstMatch,
        odds: {
          ...firstMatch.odds,
          spf: {
            ...firstMatch.odds.spf,
            options: [
              { option_code: 'h', option_name: '主胜', sp_value: 2.04 },
              { option_code: 'd', option_name: '平', sp_value: 2.95 },
              { option_code: 'a', option_name: '客胜', sp_value: 3.33 },
            ],
          },
        },
      }],
      total: 1,
    });

    render(<BettingTerminalPage />);

    const recommendationPanel = await screen.findByLabelText('推荐投注');
    fireEvent.click(within(recommendationPanel).getByRole('button', { name: '加入 主胜' }));

    const previewPanel = screen.getByLabelText('票面预览');
    await waitFor(() => expect(within(previewPanel).getByText('首尔FC vs 江原FC')).toBeInTheDocument());
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

  it('lays out score odds in the official five-column ticket order', async () => {
    const scoreNames: Record<string, string> = {
      other_h: '胜其他',
      other_d: '平其他',
      other_a: '负其他',
    };
    apiMocks.matches.mockResolvedValue({
      matches: [{
        ...firstMatch,
        odds: {
          ...completeOdds,
          bf: {
            ...completeOdds.bf,
            options: [...scoreDisplayCodes].reverse().map((optionCode, index) => ({
              option_code: optionCode,
              option_name: scoreNames[optionCode] ?? optionCode,
              sp_value: 10 + index,
            })),
          },
        },
      }],
      total: 1,
    });
    render(<BettingTerminalPage />);

    const matchCard = await screen.findByRole('article', { name: '周日203 首尔FC 对 江原FC' });
    fireEvent.click(within(matchCard).getByRole('button', { name: '全部游戏' }));

    const dialog = screen.getByRole('dialog', { name: '周日203 全部游戏' });
    const scoreSection = within(dialog).getByRole('heading', { name: '比分' }).closest('section');
    expect(scoreSection).not.toBeNull();
    const scoreGrid = scoreSection?.querySelector('.sporttery-score-grid');
    expect(scoreGrid).not.toBeNull();
    expect(within(scoreGrid as HTMLElement).getAllByRole('button').map((button) => button.querySelector('span')?.textContent)).toEqual([
      '1:0', '2:0', '2:1', '3:0', '3:1',
      '3:2', '4:0', '4:1', '4:2', '5:0',
      '5:1', '5:2', '胜其它',
      '0:0', '1:1', '2:2', '3:3', '平其它',
      '0:1', '0:2', '1:2', '0:3', '1:3',
      '2:3', '0:4', '1:4', '2:4', '0:5',
      '1:5', '2:5', '负其它',
    ]);
    expect(within(scoreGrid as HTMLElement).getByText('胜其它').closest('button')).toHaveClass('is-score-wide');
    expect(within(scoreGrid as HTMLElement).getByText('平其它').closest('button')).not.toHaveClass('is-score-wide');
    expect(within(scoreGrid as HTMLElement).getByText('负其它').closest('button')).toHaveClass('is-score-wide');

    const oneNil = within(scoreGrid as HTMLElement).getByText('1:0').closest('button');
    expect(oneNil).toHaveAttribute('aria-pressed', 'false');
    fireEvent.click(oneNil as HTMLButtonElement);
    await waitFor(() => expect(oneNil).toHaveAttribute('aria-pressed', 'true'));
    const slip = await screen.findByRole('complementary', { name: '投注单' });
    await waitFor(() => expect(within(slip).getByText((_, node) => node?.textContent === '共计: 1 注 2.00 元')).toBeInTheDocument());
  });

  it('marks single, pass, positive handicap, and negative handicap states semantically', async () => {
    apiMocks.matches.mockResolvedValue({
      matches: [
        firstMatch,
        {
          ...secondMatch,
          odds: {
            ...secondMatch.odds,
            rqspf: { ...secondMatch.odds.rqspf, handicap: 1 },
          },
        },
      ],
      total: 2,
    });
    render(<BettingTerminalPage />);

    const first = await screen.findByRole('article', { name: '周日203 首尔FC 对 江原FC' });
    const flags = within(first).getByLabelText('胜平负支持单场，支持过关');
    expect(within(flags).getByText('单')).toHaveClass('is-single');
    expect(within(flags).getByText('过')).toHaveClass('is-pass');
    expect(within(first).getByText('-1')).toHaveClass('is-negative');
    expect(within(screen.getByRole('article', { name: '周一201 马尔默 对 哥德堡' })).getByText('+1')).toHaveClass('is-positive');
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

    const preview = screen.getByLabelText('票面预览');
    expect(within(preview).getAllByText('首尔FC vs 江原FC')).toHaveLength(2);
    expect(within(preview).getByText('马尔默 vs 哥德堡')).toBeInTheDocument();
    fireEvent.click(within(preview).getAllByRole('button', { name: '移除' })[0]);
    expect(within(first).getByRole('button', { name: '胜平负 主胜 2.04' })).not.toHaveClass('is-selected');
  });

  it('archives a confirmed ticket and restores the default slip after completion', async () => {
    render(<BettingTerminalPage />);
    const first = await screen.findByRole('article', { name: '周日203 首尔FC 对 江原FC' });
    const second = screen.getByRole('article', { name: '周一201 马尔默 对 哥德堡' });
    fireEvent.click(within(first).getByRole('button', { name: '胜平负 主胜 2.04' }));
    fireEvent.click(within(second).getByRole('button', { name: '胜平负 主胜 1.67' }));

    const slip = await screen.findByRole('complementary', { name: '投注单' });
    const passGrid = within(slip).getByRole('group', { name: '过关方式' });
    expect(within(passGrid).getAllByRole('button')).toHaveLength(8);
    expect(within(passGrid).getByRole('button', { name: '3关' })).toBeDisabled();

    fireEvent.change(within(slip).getByLabelText('当前倍数'), { target: { value: '99' } });
    expect(within(slip).getByLabelText('当前倍数')).toHaveValue(50);
    expect(within(slip).getByRole('button', { name: '增加倍数' })).toBeDisabled();

    await waitFor(() => expect(within(slip).getByRole('button', { name: '确定' })).toBeEnabled());
    fireEvent.click(within(slip).getByRole('button', { name: '确定' }));
    await waitFor(() => expect(apiMocks.createTicket).toHaveBeenCalledTimes(1));
    expect(apiMocks.createTicket.mock.calls[0][0]).toMatchObject({ pass_type: '2x1', multiple: 50 });
    const confirmation = await screen.findByRole('dialog', { name: '模拟投注明细' });
    expect(confirmation).toHaveTextContent('已保存到我的彩票');

    fireEvent.click(within(confirmation).getByRole('button', { name: '完成' }));

    await waitFor(() => expect(screen.queryByRole('dialog', { name: '模拟投注明细' })).not.toBeInTheDocument());
    expect(screen.queryByRole('complementary', { name: '投注单' })).not.toBeInTheDocument();
    expect(within(screen.getByLabelText('票面预览')).getByText('等待投注器生成票面')).toBeInTheDocument();
    expect(within(first).getByRole('button', { name: '胜平负 主胜 2.04' })).not.toHaveClass('is-selected');
    expect(within(second).getByRole('button', { name: '胜平负 主胜 1.67' })).not.toHaveClass('is-selected');

    fireEvent.click(within(first).getByRole('button', { name: '胜平负 主胜 2.04' }));
    const freshSlip = await screen.findByRole('complementary', { name: '投注单' });
    expect(within(freshSlip).getByLabelText('当前倍数')).toHaveValue(1);
  });

  it('keeps the current slip when ticket saving fails', async () => {
    apiMocks.createTicket.mockRejectedValueOnce(new Error('save failed'));
    render(<BettingTerminalPage />);
    const first = await screen.findByRole('article', { name: '周日203 首尔FC 对 江原FC' });
    const second = screen.getByRole('article', { name: '周一201 马尔默 对 哥德堡' });
    const firstOption = within(first).getByRole('button', { name: '胜平负 主胜 2.04' });
    const secondOption = within(second).getByRole('button', { name: '胜平负 主胜 1.67' });
    fireEvent.click(firstOption);
    fireEvent.click(secondOption);

    const slip = await screen.findByRole('complementary', { name: '投注单' });
    const submit = within(slip).getByRole('button', { name: '确定' });
    await waitFor(() => expect(submit).toBeEnabled());
    fireEvent.click(submit);

    await waitFor(() => expect(apiMocks.createTicket).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(submit).toBeEnabled());
    expect(screen.queryByRole('dialog', { name: '模拟投注明细' })).not.toBeInTheDocument();
    expect(firstOption).toHaveClass('is-selected');
    expect(secondOption).toHaveClass('is-selected');
    expect(screen.getByRole('complementary', { name: '投注单' })).toBeInTheDocument();
  });

  it('allows single, 2-pass, and 3-pass selections on the same three-match ticket', async () => {
    apiMocks.matches.mockResolvedValue({ matches: [firstMatch, secondMatch, thirdMatch], total: 3 });
    render(<BettingTerminalPage />);

    for (const [label, option] of [
      ['周日203 首尔FC 对 江原FC', '胜平负 主胜 2.04'],
      ['周一201 马尔默 对 哥德堡', '胜平负 主胜 1.67'],
      ['周一202 罗森博格 对 维京', '胜平负 主胜 1.67'],
    ]) {
      const match = await screen.findByRole('article', { name: label });
      fireEvent.click(within(match).getByRole('button', { name: option }));
    }

    const slip = await screen.findByRole('complementary', { name: '投注单' });
    const single = within(slip).getByRole('button', { name: '单场' });
    const twoPass = within(slip).getByRole('button', { name: '2关' });
    const threePass = within(slip).getByRole('button', { name: '3关' });
    expect(threePass).toHaveAttribute('aria-pressed', 'true');

    fireEvent.click(single);
    fireEvent.click(twoPass);

    await waitFor(() => {
      expect(single).toHaveAttribute('aria-pressed', 'true');
      expect(twoPass).toHaveAttribute('aria-pressed', 'true');
      expect(threePass).toHaveAttribute('aria-pressed', 'true');
    });
    await waitFor(() => expect(apiMocks.calculate).toHaveBeenLastCalledWith(expect.objectContaining({
      pass_type: 'single,2x1,3x1',
    })));
    expect(within(slip).getByText((_, node) => node?.textContent === '共计: 7 注 14.00 元')).toBeInTheDocument();

    fireEvent.click(twoPass);
    await waitFor(() => expect(apiMocks.calculate).toHaveBeenLastCalledWith(expect.objectContaining({
      pass_type: 'single,3x1',
    })));
    expect(single).toHaveAttribute('aria-pressed', 'true');
    expect(twoPass).toHaveAttribute('aria-pressed', 'false');
    expect(threePass).toHaveAttribute('aria-pressed', 'true');

    fireEvent.click(twoPass);
    fireEvent.click(single);
    await waitFor(() => expect(apiMocks.calculate).toHaveBeenLastCalledWith(expect.objectContaining({
      pass_type: '2x1,3x1',
    })));
    expect(single).toHaveAttribute('aria-pressed', 'false');
    expect(twoPass).toHaveAttribute('aria-pressed', 'true');
    expect(threePass).toHaveAttribute('aria-pressed', 'true');

    fireEvent.click(single);
    await waitFor(() => expect(within(slip).getByRole('button', { name: '确定' })).toBeEnabled());
    fireEvent.click(within(slip).getByRole('button', { name: '确定' }));
    await waitFor(() => expect(apiMocks.createTicket).toHaveBeenCalledWith(expect.objectContaining({
      pass_type: 'single,2x1,3x1',
    })));
    expect(await screen.findByRole('dialog', { name: '模拟投注明细' })).toHaveTextContent('过关方式：单场 + 2关 + 3关');
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

  it('explains when official odds exist but no market is currently selectable', async () => {
    const unavailableOdds = Object.fromEntries(
      Object.entries(completeOdds).map(([playType, market]) => [
        playType,
        { ...market, is_single_allowed: false, is_pass_allowed: false },
      ]),
    );
    apiMocks.matches.mockResolvedValue({
      matches: [{ ...firstMatch, odds: unavailableOdds }],
      total: 1,
    });

    render(<BettingTerminalPage />);

    expect(await screen.findByText('官方赔率已发布，但当前未开放单关或过关，请稍后刷新。')).toBeInTheDocument();
  });
});
