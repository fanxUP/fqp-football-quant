import { describe, expect, it } from 'vitest';
import type { BetSlipItem } from './types';
import {
  getPassTypeGroupCount,
  getPassTypeBetCount,
  getPassTypesGroupCount,
  getAvailablePassTypes,
  getSlipWarnings,
  getTicketPlayType,
  normalizePassType,
  SPORTTERY_PLAY_RULES,
  STAKE_UNIT,
  WAGER_SOURCE_OPTIONS,
} from './bettingRules';

function slipItem(overrides: Partial<BetSlipItem>): BetSlipItem {
  return {
    match_id: overrides.match_id ?? 1,
    home_team: '主队',
    away_team: '客队',
    league_name: '测试联赛',
    kickoff_time: '2026-07-07T19:30:00',
    play_type: overrides.play_type ?? 'spf',
    play_type_label: overrides.play_type_label ?? '胜平负',
    option_code: overrides.option_code ?? '3',
    option_name: overrides.option_name ?? '主胜',
    sp_value: overrides.sp_value ?? 2.1,
    handicap: overrides.handicap,
    is_single_allowed: overrides.is_single_allowed ?? true,
    is_dan: overrides.is_dan ?? false,
  };
}

describe('bettingRules', () => {
  it('keeps Sporttery stake and play limits explicit', () => {
    expect(STAKE_UNIT).toBe(2);
    expect(SPORTTERY_PLAY_RULES.spf.maxMatches).toBe(8);
    expect(SPORTTERY_PLAY_RULES.rqspf.maxMatches).toBe(8);
    expect(SPORTTERY_PLAY_RULES.zjq.maxMatches).toBe(6);
    expect(SPORTTERY_PLAY_RULES.bf.maxMatches).toBe(4);
    expect(SPORTTERY_PLAY_RULES.bqc.maxMatches).toBe(4);
  });

  it('keeps the betting terminal focused on user tickets', () => {
    expect(WAGER_SOURCE_OPTIONS).toEqual([
      {
        code: 'real-user',
        label: '我的彩票',
        description: '选号或 OCR 识别后生成投注确认，进入彩票台账结算。',
        submitLabel: '确认投注',
      },
    ]);
  });

  it('marks mixed play slips as hhgg for submission', () => {
    expect(getTicketPlayType([slipItem({ play_type: 'spf' }), slipItem({ match_id: 2, play_type: 'spf' })])).toBe('spf');
    expect(getTicketPlayType([slipItem({ play_type: 'spf' }), slipItem({ match_id: 2, play_type: 'rqspf' })])).toBe('hhgg');
  });

  it('normalizes single and parlay pass modes', () => {
    expect(normalizePassType('single', '3x1', 3)).toBe('single');
    expect(normalizePassType('parlay', 'single', 3)).toBe('3x1');
    expect(normalizePassType('parlay', '3x4', 3)).toBe('3x4');
  });

  it('counts straight pass groups by selected match combinations', () => {
    expect(getPassTypeGroupCount(3, '3x1')).toBe(1);
    expect(getPassTypeGroupCount(3, '2x1')).toBe(3);
    expect(getPassTypesGroupCount(3, ['3x1', '2x1'])).toBe(4);
    expect(getPassTypeGroupCount(4, '2x1')).toBe(6);
    expect(getPassTypeGroupCount(1, 'single')).toBe(1);
  });

  it('exposes official compound pass types for an exact match count', () => {
    expect(getAvailablePassTypes([slipItem({ match_id: 1 }), slipItem({ match_id: 2 }), slipItem({ match_id: 3 })])).toEqual([
      'single', '2x1', '3x1', '3x3', '3x4',
    ]);
    expect(getAvailablePassTypes(Array.from({ length: 4 }, (_, index) => slipItem({ match_id: index + 1 })))).toContain('4x11');
  });

  it('counts compound passes and adjusts combinations for dan selections', () => {
    const items = [
      slipItem({ match_id: 1, is_dan: true }),
      slipItem({ match_id: 2 }),
      slipItem({ match_id: 3 }),
    ];

    expect(getPassTypeBetCount(items, '3x3')).toBe(2);
    expect(getPassTypeBetCount(items, '3x4')).toBe(3);
    expect(getPassTypeBetCount(items, '2x1')).toBe(2);
  });

  it('warns when slip violates play limits or pass type lacks enough matches', () => {
    const items = Array.from({ length: 5 }, (_, index) => slipItem({ match_id: index + 1, play_type: 'bf' }));

    expect(getSlipWarnings(items, '4x1')).toEqual([
      '比分最多支持4场，当前5场。',
    ]);
    expect(getSlipWarnings(items.slice(0, 3), '4x1')).toEqual(['4串1至少需要4场，当前3场。']);
    expect(getSlipWarnings(items.slice(0, 3), '2x1')).toEqual([]);
  });

  it('requires official single-game availability for single pass', () => {
    expect(getSlipWarnings([slipItem({ is_single_allowed: false })], 'single')).toEqual([
      '所选比赛包含未开单关的选项，请改用过关。',
    ]);
    expect(getSlipWarnings([slipItem({ match_id: 1 }), slipItem({ match_id: 1, play_type: 'rqspf' })], '2x1')).toEqual([
      '同一场比赛的不同玩法不可串关，请只保留该场一个玩法。',
    ]);
  });
});
