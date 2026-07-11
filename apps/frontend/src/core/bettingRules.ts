import type { BetSlipItem } from './types';

export type WagerSource = 'simulator' | 'real-user' | 'real-agent';
export type TicketMode = 'single' | 'parlay';

export type SportteryPlayType = 'spf' | 'rqspf' | 'zjq' | 'bf' | 'bqc';

export interface PlayRule {
  code: SportteryPlayType;
  label: string;
  shortLabel: string;
  maxMatches: number;
  settlementBasis: string;
}

export const STAKE_UNIT = 2;

export const SPORTTERY_PLAY_RULES: Record<SportteryPlayType, PlayRule> = {
  spf: {
    code: 'spf',
    label: '胜平负',
    shortLabel: '胜平负',
    maxMatches: 8,
    settlementBasis: '全场90分钟含伤停补时赛果，主队胜/平/负。',
  },
  rqspf: {
    code: 'rqspf',
    label: '让球胜平负',
    shortLabel: '让球',
    maxMatches: 8,
    settlementBasis: '按官方让球数调整后的胜/平/负结果结算。',
  },
  zjq: {
    code: 'zjq',
    label: '总进球数',
    shortLabel: '进球',
    maxMatches: 6,
    settlementBasis: '全场双方总进球数，7球及以上归为7+。',
  },
  bf: {
    code: 'bf',
    label: '比分',
    shortLabel: '比分',
    maxMatches: 4,
    settlementBasis: '全场正确比分，未列比分按官方其他选项口径结算。',
  },
  bqc: {
    code: 'bqc',
    label: '半全场',
    shortLabel: '半全场',
    maxMatches: 4,
    settlementBasis: '半场赛果与全场赛果组合。',
  },
};

export const WAGER_SOURCE_OPTIONS: Array<{
  code: WagerSource;
  label: string;
  description: string;
  submitLabel: string;
}> = [
  {
    code: 'real-user',
    label: '我的彩票',
    description: '选号或 OCR 识别后生成投注确认，进入彩票台账结算。',
    submitLabel: '确认投注',
  },
];

export function getPlayRule(playType: string): PlayRule {
  return SPORTTERY_PLAY_RULES[(playType as SportteryPlayType) in SPORTTERY_PLAY_RULES ? playType as SportteryPlayType : 'spf'];
}

export function getTicketPlayType(items: BetSlipItem[]): string {
  if (items.length === 0) return 'spf';
  const playTypes = new Set(items.map((item) => item.play_type));
  return playTypes.size === 1 ? items[0].play_type : 'hhgg';
}

export function getSelectionKey(matchId: number, playType: string): string {
  return `${matchId}:${playType}`;
}

export function normalizePassType(mode: TicketMode, selectedPassType: string, matchCount: number): string {
  if (mode === 'single' || matchCount <= 1) return 'single';
  if (selectedPassType === 'single') return `${matchCount}x1`;
  return selectedPassType;
}

export function canUseSinglePass(items: BetSlipItem[]): boolean {
  return items.length > 0 && items.every((item) => item.is_single_allowed === true);
}

export function getPassTypeRequiredMatchCount(passType: string): number | null {
  if (passType === 'single') return 1;
  const match = passType.match(/^(\d+)x1$/);
  if (!match) return null;
  return Number.parseInt(match[1], 10);
}

function combination(total: number, count: number): number {
  if (!Number.isInteger(total) || !Number.isInteger(count) || count < 0 || total < count) return 0;
  if (count === 0 || count === total) return 1;
  const picks = Math.min(count, total - count);
  let result = 1;
  for (let i = 1; i <= picks; i += 1) {
    result = (result * (total - picks + i)) / i;
  }
  return Math.round(result);
}

export function getPassTypeGroupCount(matchCount: number, passType: string): number {
  const requiredMatchCount = getPassTypeRequiredMatchCount(passType);
  if (requiredMatchCount == null || matchCount < requiredMatchCount) return 0;
  return passType === 'single' ? matchCount : combination(matchCount, requiredMatchCount);
}

export function getPassTypesGroupCount(matchCount: number, passTypes: string[]): number {
  return passTypes.reduce((sum, passType) => sum + getPassTypeGroupCount(matchCount, passType), 0);
}

export function getSlipWarnings(items: BetSlipItem[], passType: string): string[] {
  const warnings: string[] = [];
  if (items.length === 0) return warnings;

  const countsByPlay = new Map<string, number>();
  items.forEach((item) => {
    countsByPlay.set(item.play_type, (countsByPlay.get(item.play_type) ?? 0) + 1);
  });

  countsByPlay.forEach((count, playType) => {
    const rule = getPlayRule(playType);
    if (count > rule.maxMatches) {
      warnings.push(`${rule.label}最多支持${rule.maxMatches}场，当前${count}场。`);
    }
  });

  if (passType === 'single') {
    if (!canUseSinglePass(items)) {
      warnings.push('所选比赛包含未开单关的选项，请改用过关。');
    }
    return warnings;
  }

  const selectedMatchIds = new Set(items.map((item) => item.match_id));
  if (selectedMatchIds.size !== items.length) {
    warnings.push('同一场比赛的不同玩法不可串关，请只保留该场一个玩法。');
  }

  const requiredMatchCount = getPassTypeRequiredMatchCount(passType);
  if (requiredMatchCount != null && items.length < requiredMatchCount) {
    warnings.push(`${passType.replace('x', '串')}至少需要${requiredMatchCount}场，当前${items.length}场。`);
  }

  return warnings;
}
