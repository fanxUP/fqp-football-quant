/** Panel & Module registry for FQP frontend. */

export type PanelType = 'dashboard' | 'list' | 'detail' | 'analytics' | 'workflow' | 'admin' | 'agent';

export interface PanelManifest {
  panelCode: string;
  moduleCode: string;
  panelName: string;
  panelType: PanelType;
  routePath: string;
  componentName: string;
  menuGroup: string;
  order: number;
  permissions: string[];
  featureFlags?: string[];
}

export interface ModuleManifest {
  moduleCode: string;
  moduleName: string;
  description: string;
  version: string;
  status: 'active' | 'inactive' | 'coming_soon';
  panels: string[];
  dependencies: string[];
}

export function filterVisiblePanels(
  panels: PanelManifest[],
  userPermissions: Set<string>,
  enabledFlags: Set<string>,
): PanelManifest[] {
  return panels
    .filter((panel) => panel.permissions.every((p) => userPermissions.has(p)))
    .filter(
      (panel) =>
        !panel.featureFlags || panel.featureFlags.every((f) => enabledFlags.has(f)),
    )
    .sort((a, b) => a.menuGroup.localeCompare(b.menuGroup) || a.order - b.order);
}

// ---- Static registries (mirrors configs/final_panel_registry.yaml) ----

export const MODULE_REGISTRY: ModuleManifest[] = [
  {
    moduleCode: 'official_data_core',
    moduleName: '官方数据核心',
    description: '采集、存储、展示官方竞彩赛程赔率赛果',
    version: '2.0.0',
    status: 'active',
    panels: ['today_dashboard', 'match_center', 'data_health'],
    dependencies: [],
  },
  {
    moduleCode: 'recommendation_core',
    moduleName: '推荐引擎',
    description: '模型预测、推荐票单生成、风控熔断',
    version: '2.0.0',
    status: 'active',
    panels: ['recommendation_center', 'model_lab'],
    dependencies: ['official_data_core'],
  },
  {
    moduleCode: 'real_ticket_module',
    moduleName: '实票管理',
    description: '手动录入、绑定推荐、结算、复盘',
    version: '1.0.0',
    status: 'active',
    panels: ['ticket_upload', 'review_center'],
    dependencies: ['recommendation_core'],
  },
  {
    moduleCode: 'multidim_feature_module',
    moduleName: '多维特征',
    description: '球队身价、伤停、天气、战意等多维情报',
    version: '0.1.0',
    status: 'coming_soon',
    panels: ['match_intelligence'],
    dependencies: ['official_data_core'],
  },
  {
    moduleCode: 'advanced_backtest_module',
    moduleName: '回测中心',
    description: '模型回测、Brier/LogLoss/ROI评估、Walk-forward验证',
    version: '1.0.0',
    status: 'active',
    panels: ['model_lab', 'backtest_lab'],
    dependencies: ['recommendation_core'],
  },
  {
    moduleCode: 'module_runtime_core',
    moduleName: '模块运行时',
    description: '模块启停、依赖检查、面板注册',
    version: '1.0.0',
    status: 'active',
    panels: ['module_admin'],
    dependencies: [],
  },
  {
    moduleCode: 'local_settings_core',
    moduleName: '本地配置',
    description: '预算、风控、PIN、备份等本地设置',
    version: '1.0.0',
    status: 'active',
    panels: ['settings'],
    dependencies: [],
  },
];

export const PANEL_REGISTRY: PanelManifest[] = [
  {
    panelCode: 'today_dashboard',
    moduleCode: 'official_data_core',
    panelName: '今日驾驶舱',
    panelType: 'dashboard',
    routePath: '/',
    componentName: 'DashboardPage',
    menuGroup: '首页总览',
    order: 10,
    permissions: [],
  },
  {
    panelCode: 'match_center',
    moduleCode: 'official_data_core',
    panelName: '比赛中心',
    panelType: 'list',
    routePath: '/matches',
    componentName: 'MatchesPage',
    menuGroup: '官方数据',
    order: 20,
    permissions: [],
  },
  {
    panelCode: 'recommendation_center',
    moduleCode: 'recommendation_core',
    panelName: '推荐票单',
    panelType: 'list',
    routePath: '/recommendations',
    componentName: 'RecommendationsPage',
    menuGroup: '推荐资金',
    order: 30,
    permissions: [],
  },
  {
    panelCode: 'ticket_upload',
    moduleCode: 'real_ticket_module',
    panelName: '实票上传',
    panelType: 'workflow',
    routePath: '/tickets',
    componentName: 'TicketsPage',
    menuGroup: '实票管理',
    order: 40,
    permissions: [],
  },
  {
    panelCode: 'review_center',
    moduleCode: 'real_ticket_module',
    panelName: '复盘中心',
    panelType: 'analytics',
    routePath: '/reviews',
    componentName: 'ReviewsPage',
    menuGroup: '实票管理',
    order: 50,
    permissions: [],
  },
  {
    panelCode: 'model_lab',
    moduleCode: 'recommendation_core',
    panelName: '模型实验室',
    panelType: 'analytics',
    routePath: '/models',
    componentName: 'ModelsPage',
    menuGroup: '模型研究',
    order: 60,
    permissions: [],
  },
  {
    panelCode: 'backtest_lab',
    moduleCode: 'advanced_backtest_module',
    panelName: '回测实验室',
    panelType: 'analytics',
    routePath: '/backtest',
    componentName: 'BacktestPage',
    menuGroup: '模型研究',
    order: 65,
    permissions: [],
  },
  {
    panelCode: 'match_intelligence',
    moduleCode: 'multidim_feature_module',
    panelName: '多维情报',
    panelType: 'analytics',
    routePath: '/intelligence',
    componentName: 'MatchIntelligencePage',
    menuGroup: '赛前情报',
    order: 70,
    permissions: [],
    featureFlags: ['multidim_feature_enabled'],
  },
  {
    panelCode: 'data_health',
    moduleCode: 'official_data_core',
    panelName: '数据源监控',
    panelType: 'admin',
    routePath: '/data-health',
    componentName: 'DataHealthPage',
    menuGroup: '运维管理',
    order: 80,
    permissions: [],
  },
  {
    panelCode: 'module_admin',
    moduleCode: 'module_runtime_core',
    panelName: '模块管理',
    panelType: 'admin',
    routePath: '/modules',
    componentName: 'ModulesPage',
    menuGroup: '运维管理',
    order: 90,
    permissions: [],
  },
  {
    panelCode: 'settings',
    moduleCode: 'local_settings_core',
    panelName: '本地设置',
    panelType: 'admin',
    routePath: '/settings',
    componentName: 'SettingsPage',
    menuGroup: '运维管理',
    order: 100,
    permissions: [],
  },
];
