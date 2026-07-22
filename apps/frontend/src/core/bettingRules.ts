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

/**
 * 体彩竞彩足球过关拆分规则。每个元组表示：从 n 场中任选 k 场生成一注。
 * 例如 4×11 = 6 个 2 串1 + 4 个 3 串1 + 1 个 4 串1。
 */
const PASS_TYPE_SPECS: Record<string, Array<[number, number]>> = {
  single: [[1, 1]],
  '2x1': [[2, 2]],
  '3x1': [[3, 3]], '3x3': [[3, 2]], '3x4': [[3, 2], [3, 3]],
  '4x1': [[4, 4]], '4x4': [[4, 3]], '4x5': [[4, 3], [4, 4]], '4x6': [[4, 2]], '4x11': [[4, 2], [4, 3], [4, 4]],
  '5x1': [[5, 5]], '5x5': [[5, 4]], '5x6': [[5, 4], [5, 5]], '5x10': [[5, 2]], '5x16': [[5, 3], [5, 4], [5, 5]], '5x20': [[5, 2], [5, 3]], '5x26': [[5, 2], [5, 3], [5, 4], [5, 5]],
  '6x1': [[6, 6]], '6x6': [[6, 5]], '6x7': [[6, 5], [6, 6]], '6x15': [[6, 2]], '6x20': [[6, 3]], '6x22': [[6, 4], [6, 5], [6, 6]], '6x35': [[6, 2], [6, 3]], '6x42': [[6, 3], [6, 4], [6, 5], [6, 6]], '6x50': [[6, 2], [6, 3], [6, 4]], '6x57': [[6, 2], [6, 3], [6, 4], [6, 5], [6, 6]],
  '7x1': [[7, 7]], '7x7': [[7, 6]], '7x8': [[7, 6], [7, 7]], '7x21': [[7, 5]], '7x35': [[7, 4]], '7x120': [[7, 2], [7, 3], [7, 4], [7, 5], [7, 6], [7, 7]],
  '8x1': [[8, 8]], '8x8': [[8, 7]], '8x9': [[8, 7], [8, 8]], '8x28': [[8, 6]], '8x56': [[8, 5]], '8x70': [[8, 4]], '8x247': [[8, 2], [8, 3], [8, 4], [8, 5], [8, 6], [8, 7], [8, 8]],
};

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
  return items.some((item) => item.is_single_allowed === true);
}

function groupItemsByMatch(items: BetSlipItem[]): BetSlipItem[][] {
  const grouped = new Map<number, BetSlipItem[]>();
  items.forEach((item) => grouped.set(item.match_id, [...(grouped.get(item.match_id) ?? []), item]));
  return [...grouped.values()];
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

/** Returns every officially supported pass type for the current selections. */
export function getAvailablePassTypes(items: BetSlipItem[]): string[] {
  const matchCount = groupItemsByMatch(items).length;
  if (matchCount === 0) return [];

  return Object.entries(PASS_TYPE_SPECS)
    .filter(([passType, specs]) => {
      if (passType === 'single') return canUseSinglePass(items);
      if (items.some((item) => item.is_pass_allowed === false)) return false;
      const strictestLimit = Math.min(...items.map((item) => getPlayRule(item.play_type).maxMatches));
      if (specs.some(([required]) => required > strictestLimit)) return false;
      if (passType.endsWith('x1')) return matchCount >= specs[0][0];
      return specs.some(([requiredMatchCount]) => requiredMatchCount === matchCount);
    })
    .map(([passType]) => passType)
    .sort((left, right) => {
      const leftMatches = left === 'single' ? 1 : Number(left.split('x')[0]);
      const rightMatches = right === 'single' ? 1 : Number(right.split('x')[0]);
      return leftMatches - rightMatches || Number(left.split('x')[1] || 1) - Number(right.split('x')[1] || 1);
    });
}

/**
 * Count actual ticket bets after applying banker (胆码) selections.
 * This mirrors the server calculator so the amount shown before submission
 * is the same amount that will be archived on the ticket.
 */
export function getPassTypeBetCount(items: BetSlipItem[], passType: string): number {
  if (passType === 'single') return items.filter((item) => item.is_single_allowed === true).length;
  const specs = PASS_TYPE_SPECS[passType];
  if (!specs || items.length === 0) return 0;
  const groups = groupItemsByMatch(items);
  const danGroups = groups.filter((group) => group.some((item) => item.is_dan));
  const normalGroups = groups.filter((group) => !group.some((item) => item.is_dan));
  const danCount = danGroups.length;
  const normalCount = normalGroups.length;
  const danWeight = danGroups.reduce((weight, group) => weight * group.length, 1);

  const weightedCombinations = (count: number): number => {
    if (count < 0 || count > normalGroups.length) return 0;
    let total = 0;
    const visit = (start: number, remaining: number, weight: number) => {
      if (remaining === 0) {
        total += weight;
        return;
      }
      for (let index = start; index <= normalGroups.length - remaining; index += 1) {
        visit(index + 1, remaining - 1, weight * normalGroups[index].length);
      }
    };
    visit(0, count, danWeight);
    return total;
  };

  return specs.reduce((total, [requiredMatchCount, selectionCount]) => {
    if (passType.endsWith('x1') ? groups.length < requiredMatchCount : groups.length !== requiredMatchCount) return total;
    const normalSelections = selectionCount - danCount;
    if (normalSelections < 0 || normalSelections > normalCount) return total;
    return total + weightedCombinations(normalSelections);
  }, 0);
}

export function getPassTypesBetCount(items: BetSlipItem[], passTypes: string[]): number {
  return passTypes.reduce((sum, passType) => sum + getPassTypeBetCount(items, passType), 0);
}

export function getPassTypesGroupCount(matchCount: number, passTypes: string[]): number {
  return passTypes.reduce((sum, passType) => sum + getPassTypeGroupCount(matchCount, passType), 0);
}

export function getSlipWarnings(items: BetSlipItem[], passType: string): string[] {
  const warnings: string[] = [];
  if (items.length === 0) return warnings;

  const matchCount = groupItemsByMatch(items).length;
  const strictestRule = items.map((item) => getPlayRule(item.play_type)).reduce((left, right) => left.maxMatches <= right.maxMatches ? left : right);
  if (matchCount > strictestRule.maxMatches) {
    warnings.push(`${strictestRule.label}最多支持${strictestRule.maxMatches}场，当前${matchCount}场。`);
  }

  if (passType === 'single') {
    if (!canUseSinglePass(items)) {
      warnings.push('所选比赛包含未开单关的选项，请改用过关。');
    }
    return warnings;
  }

  if (items.some((item) => item.is_pass_allowed === false)) {
    warnings.push('所选比赛包含仅支持单场的选项，不能用于过关。');
  }

  const requiredMatchCount = getPassTypeRequiredMatchCount(passType);
  if (requiredMatchCount != null && matchCount < requiredMatchCount) {
    warnings.push(`${passType.replace('x', '串')}至少需要${requiredMatchCount}场，当前${matchCount}场。`);
  }

  if (matchCount >= (requiredMatchCount ?? 0) && getPassTypeBetCount(items, passType) === 0) {
    warnings.push(`${passType.replace('x', '串')}的胆码数量不符合该过关方式。`);
  }

  return warnings;
}
