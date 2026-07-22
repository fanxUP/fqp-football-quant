import { describe, expect, it } from 'vitest';
import {
  getSidebarPanels,
  MODULE_REGISTRY,
  NAVIGATION_GROUPS,
  PANEL_REGISTRY,
} from './panelRegistry';

describe('panel registry', () => {
  it('does not reference unknown modules or panels', () => {
    const moduleCodes = new Set(MODULE_REGISTRY.map((module) => module.moduleCode));
    const panelCodes = new Set(PANEL_REGISTRY.map((panel) => panel.panelCode));

    for (const panel of PANEL_REGISTRY) {
      expect(moduleCodes.has(panel.moduleCode), `${panel.panelCode} module`).toBe(true);
    }

    for (const module of MODULE_REGISTRY) {
      for (const panelCode of module.panels) {
        expect(panelCodes.has(panelCode), `${module.moduleCode}.${panelCode}`).toBe(true);
      }
    }
  });

  it('keeps sidebar panels in one functional order', () => {
    const labels = getSidebarPanels(new Set()).map((panel) => panel.panelName);

    expect(labels).toEqual([
      '今日驾驶舱',
      '比赛中心',
      '赛事中心',
      '赔率走势',
      '投注中心',
      '今日决策分析',
      '特征数据健康',
      '模型表现',
      '冷门研究',
      '策略验证',
      '足彩彩池',
      '系统监控',
      '功能模块',
      '系统设置',
      '智能代理',
    ]);
  });

  it('groups every module into the optimized four-layer structure', () => {
    const groupCodes = new Set(NAVIGATION_GROUPS.map((group) => group.groupCode));

    for (const module of MODULE_REGISTRY) {
      expect(groupCodes.has(module.category), `${module.moduleCode} category`).toBe(true);
    }
  });

  it('keeps research, pool, and operations dependencies one-directional', () => {
    const modules = new Map(MODULE_REGISTRY.map((module) => [module.moduleCode, module]));
    const modelResearch = modules.get('model_research_module');
    const poolLottery = modules.get('pool_lottery_module');
    const operationsPanel = PANEL_REGISTRY.find((panel) => panel.panelCode === 'data_health');

    expect(modelResearch?.dependencies).toEqual(['official_data_core', 'multidim_feature_module']);
    expect(poolLottery?.dependencies).toEqual(['official_data_core', 'model_research_module']);
    expect(operationsPanel?.moduleCode).toBe('ops_admin');
  });
});
