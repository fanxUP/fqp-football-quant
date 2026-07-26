import { describe, expect, it } from 'vitest';
import type { BettingOddsOption } from '../../core/types';
import { arrangeScoreOdds } from './scoreOddsLayout';

const scoreOption = (optionCode: string, optionName = optionCode): BettingOddsOption => ({
  option_code: optionCode,
  option_name: optionName,
  sp_value: 10,
});

describe('arrangeScoreOdds', () => {
  it('按主胜、平局、客胜的票面顺序排列全部比分', () => {
    const expectedCodes = [
      '1:0', '2:0', '2:1', '3:0', '3:1',
      '3:2', '4:0', '4:1', '4:2', '5:0',
      '5:1', '5:2', 'other_h',
      '0:0', '1:1', '2:2', '3:3', 'other_d',
      '0:1', '0:2', '1:2', '0:3', '1:3',
      '2:3', '0:4', '1:4', '2:4', '0:5',
      '1:5', '2:5', 'other_a',
    ];
    const shuffled = [...expectedCodes].reverse().map((code) => scoreOption(code));

    const arranged = arrangeScoreOdds(shuffled);

    expect(arranged.map((item) => item.option.option_code)).toEqual(expectedCodes);
  });

  it('只在展示层把三个其他比分改为图中的其它文案并标记跨列项', () => {
    const arranged = arrangeScoreOdds([
      scoreOption('other_h', '胜其他'),
      scoreOption('other_d', '平其他'),
      scoreOption('other_a', '负其他'),
    ]);

    expect(arranged.map(({ label, isWide }) => ({ label, isWide }))).toEqual([
      { label: '胜其它', isWide: true },
      { label: '平其它', isWide: false },
      { label: '负其它', isWide: true },
    ]);
    expect(arranged.map((item) => item.option.option_name)).toEqual(['胜其他', '平其他', '负其他']);
  });

  it('保留接口新增的未知比分并排在官方固定比分之后', () => {
    const arranged = arrangeScoreOdds([
      scoreOption('6:0'),
      scoreOption('2:1'),
      scoreOption('1:0'),
    ]);

    expect(arranged.map((item) => item.option.option_code)).toEqual(['1:0', '2:1', '6:0']);
  });
});
