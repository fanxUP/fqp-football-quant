import type { BettingOddsOption } from '../../core/types';

const SCORE_DISPLAY_ORDER = [
  '1:0', '2:0', '2:1', '3:0', '3:1',
  '3:2', '4:0', '4:1', '4:2', '5:0',
  '5:1', '5:2', 'other_h',
  '0:0', '1:1', '2:2', '3:3', 'other_d',
  '0:1', '0:2', '1:2', '0:3', '1:3',
  '2:3', '0:4', '1:4', '2:4', '0:5',
  '1:5', '2:5', 'other_a',
] as const;

const SCORE_RANK = new Map<string, number>(
  SCORE_DISPLAY_ORDER.map((optionCode, index) => [optionCode, index]),
);

const OTHER_SCORE_LABELS: Record<string, string> = {
  other_h: '胜其它',
  other_d: '平其它',
  other_a: '负其它',
};

export interface ScoreOddsLayoutItem {
  option: BettingOddsOption;
  label: string;
  isWide: boolean;
}

export function arrangeScoreOdds(options: ReadonlyArray<BettingOddsOption>): ScoreOddsLayoutItem[] {
  return options
    .map((option, sourceIndex) => ({ option, sourceIndex }))
    .sort((left, right) => {
      const leftRank = SCORE_RANK.get(left.option.option_code) ?? SCORE_DISPLAY_ORDER.length;
      const rightRank = SCORE_RANK.get(right.option.option_code) ?? SCORE_DISPLAY_ORDER.length;
      return leftRank - rightRank || left.sourceIndex - right.sourceIndex;
    })
    .map(({ option }) => ({
      option,
      label: OTHER_SCORE_LABELS[option.option_code] ?? option.option_name,
      isWide: option.option_code === 'other_h' || option.option_code === 'other_a',
    }));
}
