import { describe, expect, it } from 'vitest';
import { modelNameLabel, optionLabel, passTypeLabel, playTypeLabel } from './constants';

describe('modelNameLabel', () => {
  it.each([
    ['elo_rating', 'Elo 实力评分'],
    ['market_baseline', '市场赔率基准'],
    ['dixon_coles', '迪克森-科尔斯比分模型'],
    ['maher_poisson', '马赫泊松进球模型'],
  ])('将 %s 显示为 %s', (code, label) => {
    expect(modelNameLabel(code)).toBe(label);
  });

  it('保留未知模型名以避免丢失信息', () => {
    expect(modelNameLabel('new_model')).toBe('new_model');
  });
});

describe('彩票玩法中文标签', () => {
  it('将 mixed 和 single 转换为中文业务名称', () => {
    expect(playTypeLabel('mixed')).toBe('混合过关');
    expect(playTypeLabel('single')).toBe('单关');
    expect(passTypeLabel('single')).toBe('单关');
  });

  it('将 Agent 票种和比分其他选项转换为中文', () => {
    expect(playTypeLabel('virtual_recommendation')).toBe('Agent 推荐票');
    expect(optionLabel('bf', 'other_h')).toBe('胜其他');
    expect(optionLabel('bf', 'other_d')).toBe('平其他');
    expect(optionLabel('bf', 'other_a')).toBe('负其他');
  });
});
