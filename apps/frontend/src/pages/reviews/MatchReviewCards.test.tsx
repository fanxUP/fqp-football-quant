import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import MatchReviewCards from './MatchReviewCards';

const apiMocks = vi.hoisted(() => ({ matchCards: vi.fn() }));

vi.mock('../../core/apiClient', () => ({ api: { reviews: { matchCards: apiMocks.matchCards } } }));

describe('MatchReviewCards', () => {
  beforeEach(() => {
    apiMocks.matchCards.mockResolvedValue({
      date: '2026-08-09', total: 1, cards: [{
        matchId: 7, officialCode: '周日001', leagueName: '英超', homeTeamName: '主队', awayTeamName: '客队', kickoffTime: null,
        result: { homeGoals: 2, awayGoals: 1, spfResult: '主胜', status: 'confirmed', publishedAt: null },
        modelSignals: [{ modelName: 'elo_rating', playType: 'spf', optionCode: 'h', modelProbability: 0.62, marketProbability: 0.55, ev: 0.12, confidenceScore: 0.78, predictTime: null }],
        oddsSignals: [{ playType: 'spf', optionCode: 'h', optionName: '主胜', spValue: 1.82, handicap: null, snapshotTime: null }],
        evidence: [], evidenceStatus: '未查到可靠资料',
      }],
    });
  });

  it('displays immutable pre-match signals, official result, and an explicit evidence gap', async () => {
    render(<MatchReviewCards reviewDate="2026-08-09" />);

    expect(await screen.findByRole('heading', { name: '单场复盘' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '主队 VS 客队' })).toBeInTheDocument();
    expect(screen.getByText('2 : 1')).toBeInTheDocument();
    expect(screen.getByText('Elo 实力评分')).toBeInTheDocument();
    expect(screen.getByText('62.0%')).toBeInTheDocument();
    expect(screen.getByText('未查到可靠资料')).toBeInTheDocument();
    expect(apiMocks.matchCards).toHaveBeenCalledWith('2026-08-09');
  });
});
