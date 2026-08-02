import { describe, expect, it } from 'vitest';
import {
  modelNameLabel,
  optionLabel,
  passTypeLabel,
  playTypeLabel,
  agentLabel,
  agentTypeLabel,
  reviewStatusLabel,
  permissionLevelLabel,
  riskLabel,
  statusLabel,
  strategyPoolLabel,
} from './constants';

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
    expect(playTypeLabel('virtual_recommendation')).toBe('智能代理推荐票');
    expect(optionLabel('bf', 'other_h')).toBe('胜其他');
    expect(optionLabel('bf', 'other_d')).toBe('平其他');
    expect(optionLabel('bf', 'other_a')).toBe('负其他');
  });
});

describe('推荐票内部标识中文标签', () => {
  it('将 Agent 虚拟推荐、待激活与参考级显示为中文', () => {
    expect(strategyPoolLabel('agent_virtual_recommendation')).toBe('智能代理虚拟推荐');
    expect(statusLabel('generated')).toBe('待激活');
    expect(riskLabel('reference')).toBe('参考级');
  });
});

describe('智能代理内部标识中文标签', () => {
  it('将代理代码与审核状态显示为中文', () => {
    expect(agentLabel('recommendation_agent')).toBe('推荐代理');
    expect(agentLabel('review_agent')).toBe('复盘代理');
    expect(agentTypeLabel('orchestrator')).toBe('任务编排');
    expect(permissionLevelLabel('P3_controlled')).toBe('P3-受控执行');
    expect(reviewStatusLabel('approved')).toBe('已批准');
    expect(reviewStatusLabel('rejected')).toBe('已拒绝');
  });
});
