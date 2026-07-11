import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import BettingTerminalPage, { calculateSentimentWeight } from './BettingTerminalPage';
import type { BettingMatch, LiveRecommendation } from '../core/types';

const match: BettingMatch = {
  match_id: 901,
  business_date: '2026-07-08',
  league_name: '中超',
  home_team_name: '上海海港',
  away_team_name: '山东泰山',
  kickoff_time: '2026-07-08T19:35:00',
  match_status: 'Scheduled',
  match_num_str: '3001',
  odds: {
    spf: {
      is_single_allowed: true,
      options: [
        { option_code: '3', option_name: '主胜', sp_value: 1.66 },
        { option_code: '1', option_name: '平', sp_value: 3.4 },
        { option_code: '0', option_name: '客胜', sp_value: 4.9 },
      ],
    },
    rqspf: {
      is_single_allowed: false,
      handicap: -1,
      options: [
        { option_code: '3', option_name: '让主胜', sp_value: 2.9 },
        { option_code: '1', option_name: '让平', sp_value: 3.6 },
        { option_code: '0', option_name: '让客胜', sp_value: 2.2 },
      ],
    },
    zjq: { is_single_allowed: false, options: [] },
    bf: { is_single_allowed: false, options: [] },
    bqc: { is_single_allowed: false, options: [] },
  },
};

const secondMatch: BettingMatch = {
  ...match,
  match_id: 902,
  business_date: '2026-07-08',
  home_team_name: '北京国安',
  away_team_name: '成都蓉城',
  match_num_str: '3002',
  odds: {
    ...match.odds,
    spf: {
      is_single_allowed: true,
      options: [
        { option_code: 'h', option_name: '主胜', sp_value: 2.05 },
        { option_code: 'd', option_name: '平', sp_value: 3.1 },
        { option_code: 'a', option_name: '客胜', sp_value: 3.8 },
      ],
    },
    rqspf: {
      is_single_allowed: false,
      handicap: 1,
      options: [
        { option_code: 'h', option_name: '让主胜', sp_value: 1.42 },
        { option_code: 'd', option_name: '让平', sp_value: 4.1 },
        { option_code: 'a', option_name: '让客胜', sp_value: 5.6 },
      ],
    },
  },
};

const thirdMatch: BettingMatch = {
  ...match,
  match_id: 903,
  business_date: '2026-07-08',
  home_team_name: '天津津门虎',
  away_team_name: '河南队',
  match_num_str: '3003',
  odds: {
    ...match.odds,
    spf: {
      is_single_allowed: true,
      options: [
        { option_code: '3', option_name: '主胜', sp_value: 2.25 },
        { option_code: '1', option_name: '平', sp_value: 3.0 },
        { option_code: '0', option_name: '客胜', sp_value: 3.2 },
      ],
    },
  },
};

const recommendation: LiveRecommendation = {
  prediction_id: 10,
  match_id: 901,
  play_type: 'spf',
  play_type_name: '胜平负',
  option_code: '3',
  option_name: '主胜',
  model_probability: 0.62,
  market_probability: 0.5,
  fair_odds: 1.66,
  ev: 0.13,
  edge: 0.12,
  confidence: 0.73,
  predict_time: '2026-07-08T09:00:00',
  model_name: 'xgb-main',
  home_team: '上海海港',
  away_team: '山东泰山',
  league: '中超',
  kickoff_time: '2026-07-08T19:35:00',
  match_status: 'Scheduled',
  match_num_str: '3001',
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

vi.mock('../core/apiClient', () => ({
  api: {
    bettingTerminal: {
      matches: vi.fn(async () => ({ matches: [match, secondMatch, thirdMatch], total: 3 })),
      calculate: vi.fn(async (body: { items: unknown[]; pass_type: string; multiple: number }) => {
        const matchCount = body.items.length;
        const passTypes = matchCount >= 3 ? ['single', '2x1', '3x1', '3x3', '3x4'] : matchCount >= 2 ? ['single', '2x1'] : ['single'];
        return {
          pass_type: body.pass_type,
          multiple: body.multiple,
          bet_count: body.pass_type === 'single' ? matchCount : 1,
          total_cost: (body.pass_type === 'single' ? matchCount * 2 : 2) * body.multiple,
          max_prize: 3.32 * matchCount * body.multiple,
          match_count: matchCount,
          combinations: [],
          available_pass_types: passTypes,
        };
      }),
    },
    liveRecommendations: vi.fn(async () => ({
      status: 'ok',
      recommendations: [recommendation],
      total: 1,
    })),
    betting: {
      ocrUpload: vi.fn(),
      createTicket: vi.fn(async () => ({})),
    },
  },
}));

vi.mock('../shared/components/Toast', () => ({
  useToast: () => ({
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
  }),
}));

describe('BettingTerminalPage', () => {
  it('keeps the sentiment weight bounded and responsive to confidence', () => {
    expect(calculateSentimentWeight({ edge: 0.12, ev: 0.13, confidence: 0.73 })).toBeGreaterThan(50);
    expect(calculateSentimentWeight({ edge: -0.1, ev: -0.2, confidence: 0.2 })).toBeLessThan(50);
  });

  it('renders recommendation, terminal, and slip columns with recommendation rationale', async () => {
    render(<BettingTerminalPage />);

    const recommendationPanel = await screen.findByLabelText('推荐单');
    expect(within(recommendationPanel).getByText((_, node) => node?.textContent === '上海海港 vs 山东泰山')).toBeInTheDocument();
    const terminalPanel = screen.getByLabelText('投注器');
    const slipPanel = screen.getByLabelText('投注单');
    expect(within(recommendationPanel).getByRole('heading', { name: '推荐单' })).toBeInTheDocument();
    expect(within(terminalPanel).getByRole('heading', { name: '投注器' })).toBeInTheDocument();
    expect(within(slipPanel).getByRole('heading', { name: '投注单' })).toBeInTheDocument();
    expect(screen.getAllByRole('heading', { name: '投注器' })).toHaveLength(1);
    expect(within(terminalPanel).getByRole('tab', { name: '胜负平/让球' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    expect(within(terminalPanel).queryByRole('tab', { name: '让球胜平负' })).not.toBeInTheDocument();
    const combinedOdds = within(terminalPanel).getAllByLabelText('胜负平/让球赔率')[0];
    expect(
      within(combinedOdds)
        .getAllByRole('button')
        .filter((button) => button.getAttribute('aria-pressed') !== null)
        .map((button) => button.textContent),
    ).toEqual([
      '主胜1.66',
      '平3.40',
      '主负4.90',
      '主胜2.90',
      '平3.60',
      '主负2.20',
    ]);
    expect(within(combinedOdds).getByRole('button', { name: /全部\s*游戏/ })).toBeInTheDocument();
    expect(within(combinedOdds).getByLabelText('胜平负支持单关，支持过关，让球-')).toBeInTheDocument();
    expect(within(combinedOdds).getByLabelText('让球胜平负不支持单关，支持过关，让球-1')).toBeInTheDocument();

    fireEvent.click(within(recommendationPanel).getByRole('button', { name: /加入 主胜/ }));

    await waitFor(() => {
      expect(within(slipPanel).getByText('模型 62.0%')).toBeInTheDocument();
    });

    expect(within(terminalPanel).getByText('过关方式')).toBeInTheDocument();
    expect(within(terminalPanel).getByRole('checkbox', { name: '单关' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(terminalPanel).getByLabelText('投注倍数')).toHaveValue(1);
    expect(within(terminalPanel).getByLabelText('方案备注')).toBeInTheDocument();
    expect(within(terminalPanel).getByLabelText('上传彩票图片进行 OCR 识别')).toBeInTheDocument();
    expect(within(slipPanel).queryByRole('radiogroup', { name: '投注方式' })).not.toBeInTheDocument();
    expect(within(slipPanel).queryByLabelText('投注倍数')).not.toBeInTheDocument();
    expect(within(slipPanel).queryByLabelText('方案备注')).not.toBeInTheDocument();
    expect(within(slipPanel).getByText('市场 50.0%')).toBeInTheDocument();
    expect(within(slipPanel).getByText('情绪权重')).toBeInTheDocument();
    expect(within(slipPanel).getByText(/互联网情绪/)).toBeInTheDocument();
    expect(within(slipPanel).getByText('推荐单')).toBeInTheDocument();
    expect(within(slipPanel).getByText('投注金额')).toBeInTheDocument();
    expect(within(slipPanel).getAllByText('¥2.00').length).toBeGreaterThan(0);
  }, 10_000);

  it('offers pass type buttons in the terminal based on selected matches', async () => {
    render(<BettingTerminalPage />);

    const terminalPanel = await screen.findByLabelText('投注器');
    const slipPanel = screen.getByLabelText('投注单');
    fireEvent.click(within(terminalPanel).getByRole('button', { name: '主负4.90' }));
    fireEvent.click(within(terminalPanel).getByRole('button', { name: '主负3.80' }));

    await waitFor(() => {
      expect(within(terminalPanel).getByRole('checkbox', { name: '2×1' })).toBeInTheDocument();
    });
    expect(within(terminalPanel).getAllByText('1组').length).toBeGreaterThan(0);

    fireEvent.click(within(terminalPanel).getByRole('button', { name: '+' }));

    await waitFor(() => {
      expect(within(slipPanel).getByText('2×1')).toBeInTheDocument();
    });

    expect(within(terminalPanel).getByLabelText('投注倍数')).toHaveValue(2);
    expect(within(slipPanel).getByText('2 倍')).toBeInTheDocument();
    expect(within(slipPanel).getByText('2 场')).toBeInTheDocument();
    expect(within(slipPanel).getByText('1 组')).toBeInTheDocument();
    expect(within(slipPanel).getByText('1 注')).toBeInTheDocument();
    expect(within(slipPanel).getAllByText('¥4.00').length).toBeGreaterThan(0);
  });

  it('supports multiple pass buttons and toggles an already selected odd off', async () => {
    render(<BettingTerminalPage />);

    const terminalPanel = await screen.findByLabelText('投注器');
    const slipPanel = screen.getByLabelText('投注单');
    fireEvent.click(within(terminalPanel).getByRole('button', { name: '主负4.90' }));
    fireEvent.click(within(terminalPanel).getByRole('button', { name: '主负3.80' }));
    fireEvent.click(within(terminalPanel).getByRole('button', { name: '主负3.20' }));

    await waitFor(() => {
      expect(within(terminalPanel).getByRole('checkbox', { name: '3×1' })).toBeInTheDocument();
    });

    expect(within(terminalPanel).queryByRole('checkbox', { name: '3×3' })).not.toBeInTheDocument();
    expect(within(terminalPanel).queryByRole('checkbox', { name: '3×4' })).not.toBeInTheDocument();
    await waitFor(() => {
      expect(within(slipPanel).getByText('3×1')).toBeInTheDocument();
    });

    fireEvent.click(within(terminalPanel).getByRole('checkbox', { name: '2×1' }));

    await waitFor(() => {
      expect(within(slipPanel).getByText('3×1 + 2×1')).toBeInTheDocument();
    });
    expect(within(terminalPanel).getByRole('checkbox', { name: '2×1' })).toHaveTextContent('3组');
    expect(within(slipPanel).getByText('4 组')).toBeInTheDocument();
    expect(within(slipPanel).getByText('4 注')).toBeInTheDocument();
    expect(within(slipPanel).getByText('¥8.00')).toBeInTheDocument();
    expect(within(slipPanel).queryByText(/2串1至少需要/)).not.toBeInTheDocument();

    fireEvent.click(within(terminalPanel).getByRole('button', { name: '主负3.20' }));

    await waitFor(() => {
      expect(within(slipPanel).getByText('2 场')).toBeInTheDocument();
    });
    expect(within(terminalPanel).queryByText('天津津门虎 vs 河南队')).not.toBeInTheDocument();
  });

  it('replaces a selection when another play is picked from the same match', async () => {
    render(<BettingTerminalPage />);

    const terminalPanel = await screen.findByLabelText('投注器');
    const slipPanel = screen.getByLabelText('投注单');

    fireEvent.click(within(terminalPanel).getByRole('button', { name: '主负4.90' }));
    await waitFor(() => {
      expect(within(slipPanel).getByText('主负')).toBeInTheDocument();
      expect(within(slipPanel).getByText('@ 4.90')).toBeInTheDocument();
    });

    fireEvent.click(within(terminalPanel).getAllByRole('button', { name: '主负2.20' })[0]);

    await waitFor(() => {
      expect(within(slipPanel).getByText('主负')).toBeInTheDocument();
      expect(within(slipPanel).getByText('@ 2.20')).toBeInTheDocument();
    });
    expect(within(slipPanel).getByText('1 场')).toBeInTheDocument();
    expect(within(slipPanel).queryByText('@ 4.90')).not.toBeInTheDocument();
    expect(within(slipPanel).getAllByText('让球胜平负')).toHaveLength(2);
    expect(
      within(terminalPanel)
        .getAllByRole('button')
        .filter((button) => button.getAttribute('aria-pressed') === 'true'),
    ).toHaveLength(1);
  });
});
