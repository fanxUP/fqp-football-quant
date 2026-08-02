/** Panel & Module registry for FQP frontend. */

export type ModuleCategory =
  | 'core_loop'
  | 'research'
  | 'strategy_lab'
  | 'maintenance';

export type PanelType =
  | 'dashboard'
  | 'list'
  | 'detail'
  | 'analytics'
  | 'workflow'
  | 'admin'
  | 'agent'
  | 'simulation';

export interface NavigationGroup {
  groupCode: string;
  groupName: string;
  order: number;
}

export interface PanelManifest {
  panelCode: string;
  moduleCode: string;
  panelName: string;
  panelType: PanelType;
  routePath: string;
  componentName: string;
  menuGroup: string;
  icon: string;
  order: number;
  permissions: string[];
  featureFlags?: string[];
  showInSidebar?: boolean;
}

export type SidebarPanel = Pick<
  PanelManifest,
  'panelCode' | 'moduleCode' | 'panelName' | 'menuGroup' | 'routePath' | 'icon' | 'order'
>;

export interface ModuleManifest {
  moduleCode: string;
  moduleName: string;
  description: string;
  version: string;
  category: ModuleCategory;
  status: 'active' | 'inactive' | 'coming_soon';
  required: boolean;
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

export function getSidebarPanels(
  disabledModules: Set<string>,
  userPermissions: Set<string> = new Set(),
  enabledFlags: Set<string> = new Set(),
): PanelManifest[] {
  const permissions =
    userPermissions.size > 0
      ? userPermissions
      : new Set(PANEL_REGISTRY.flatMap((panel) => panel.permissions));
  const flags =
    enabledFlags.size > 0
      ? enabledFlags
      : new Set(PANEL_REGISTRY.flatMap((panel) => panel.featureFlags ?? []));

  return filterVisiblePanels(PANEL_REGISTRY, permissions, flags)
    .filter((panel) => panel.showInSidebar !== false)
    .filter((panel) => !disabledModules.has(panel.moduleCode))
    .sort((a, b) => a.order - b.order);
}

// ---- Static registries (mirrors configs/final_module_registry.yaml / final_panel_registry.yaml) ----

export const NAVIGATION_GROUPS: NavigationGroup[] = [
  { groupCode: 'core_loop', groupName: '核心闭环', order: 10 },
  { groupCode: 'research', groupName: '研究优化', order: 20 },
  { groupCode: 'strategy_lab', groupName: '策略实验', order: 30 },
  { groupCode: 'maintenance', groupName: '运维设置', order: 40 },
];

export const MODULE_REGISTRY: ModuleManifest[] = [
  {
    moduleCode: 'official_data_core',
    moduleName: '官方数据核心',
    description: '采集、存储、展示官方竞彩赛程赔率赛果',
    version: '2.0.0',
    category: 'core_loop',
    status: 'active',
    required: true,
    panels: ['today_dashboard', 'match_center', 'event_center', 'odds_movement'],
    dependencies: [],
  },
  {
    moduleCode: 'recommendation_core',
    moduleName: '推荐与资金核心',
    description: '模型预测、推荐票单生成、风控熔断、资金约束',
    version: '2.0.0',
    category: 'core_loop',
    status: 'active',
    required: true,
    panels: ['deep_analysis'],
    dependencies: ['official_data_core'],
  },
  {
    moduleCode: 'betting_center_module',
    moduleName: '投注中心',
    description: '投注器、彩票台账、Agent 结果和赛后结算',
    version: '1.0.0',
    category: 'core_loop',
    status: 'active',
    required: true,
    panels: ['betting_center'],
    dependencies: ['recommendation_core'],
  },
  {
    moduleCode: 'multidim_feature_module',
    moduleName: '特征数据健康',
    description: '检查球队身价、伤停、天气、战意等特征的覆盖率与完整度',
    version: '0.1.0',
    category: 'research',
    status: 'active',
    required: false,
    panels: ['feature_snapshots'],
    dependencies: ['official_data_core'],
  },
  {
    moduleCode: 'model_research_module',
    moduleName: '模型研究',
    description: '模型版本、解释分析、回测评估与人工启用',
    version: '1.0.0',
    category: 'research',
    status: 'active',
    required: false,
    panels: ['model_lab', 'backtest_lab'],
    dependencies: ['official_data_core', 'multidim_feature_module'],
  },
  {
    moduleCode: 'model_provider_module',
    moduleName: '模型接入',
    description: '统一管理模型服务商、密钥加密存储、连通性与启停状态',
    version: '1.0.0',
    category: 'research',
    status: 'active',
    required: false,
    panels: ['model_providers'],
    dependencies: [],
  },
  {
    moduleCode: 'agent_workspace_module',
    moduleName: '智能工作台',
    description: '人工发起模型分析任务，明确职责边界并即时查看结果',
    version: '2.0.0',
    category: 'research',
    status: 'active',
    required: false,
    panels: ['agent_workspace'],
    dependencies: ['model_provider_module'],
  },
  {
    moduleCode: 'upset_intelligence_module',
    moduleName: '冷门研究',
    description: '冷门识别、证据复盘、周期报告与决策知识沉淀',
    version: '1.0.0',
    category: 'research',
    status: 'active',
    required: false,
    panels: ['upset_research'],
    dependencies: ['official_data_core', 'betting_center_module', 'model_research_module'],
  },
  {
    moduleCode: 'pool_lottery_module',
    moduleName: '传统足彩',
    description: '胜负彩、任选九与组合优化',
    version: '1.0.0',
    category: 'strategy_lab',
    status: 'active',
    required: false,
    panels: ['pool_lottery'],
    dependencies: ['official_data_core', 'model_research_module'],
  },
  {
    moduleCode: 'codex_agent_module',
    moduleName: 'Codex 多 Agent',
    description: '本地 Agent 任务、协作边界与维护自动化',
    version: '1.0.0',
    category: 'maintenance',
    status: 'active',
    required: false,
    panels: ['codex_console'],
    dependencies: [],
  },
  {
    moduleCode: 'module_runtime_core',
    moduleName: '模块运行时',
    description: '模块启停、依赖检查、面板注册',
    version: '1.0.0',
    category: 'maintenance',
    status: 'active',
    required: false,
    panels: ['module_admin'],
    dependencies: [],
  },
  {
    moduleCode: 'local_settings_core',
    moduleName: '本地配置',
    description: '预算、风控、PIN、备份等本地设置',
    version: '1.0.0',
    category: 'maintenance',
    status: 'active',
    required: false,
    panels: ['settings'],
    dependencies: [],
  },
  {
    moduleCode: 'ops_admin',
    moduleName: '运维后台',
    description: '系统监控、数据健康和运行状态',
    version: '1.0.0',
    category: 'maintenance',
    status: 'active',
    required: false,
    panels: ['data_health'],
    dependencies: ['official_data_core'],
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
    menuGroup: '核心闭环',
    icon: '📊',
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
    menuGroup: '核心闭环',
    icon: '⚽',
    order: 20,
    permissions: [],
  },
  {
    panelCode: 'event_center',
    moduleCode: 'official_data_core',
    panelName: '赛事中心',
    panelType: 'list',
    routePath: '/events',
    componentName: 'EventsPage',
    menuGroup: '核心闭环',
    icon: '🏆',
    order: 30,
    permissions: [],
  },
  {
    panelCode: 'odds_movement',
    moduleCode: 'official_data_core',
    panelName: '赔率走势',
    panelType: 'analytics',
    routePath: '/odds',
    componentName: 'OddsMovementPage',
    menuGroup: '核心闭环',
    icon: '📉',
    order: 50,
    permissions: [],
  },
  {
    panelCode: 'betting_center',
    moduleCode: 'betting_center_module',
    panelName: '投注中心',
    panelType: 'workflow',
    routePath: '/betting',
    componentName: 'BettingCenterPage',
    menuGroup: '核心闭环',
    icon: '🎫',
    order: 60,
    permissions: [],
  },
  {
    panelCode: 'deep_analysis',
    moduleCode: 'recommendation_core',
    panelName: '今日决策分析',
    panelType: 'analytics',
    routePath: '/analysis',
    componentName: 'AnalysisPage',
    menuGroup: '核心闭环',
    icon: '🔬',
    order: 70,
    permissions: [],
  },
  {
    panelCode: 'model_lab',
    moduleCode: 'model_research_module',
    panelName: '模型表现',
    panelType: 'analytics',
    routePath: '/models',
    componentName: 'ModelsPage',
    menuGroup: '研究优化',
    icon: '🧠',
    order: 110,
    permissions: [],
  },
  {
    panelCode: 'model_providers',
    moduleCode: 'model_provider_module',
    panelName: '模型接入',
    panelType: 'admin',
    routePath: '/model-providers',
    componentName: 'ModelProvidersPage',
    menuGroup: '研究优化',
    icon: '🔌',
    order: 115,
    permissions: [],
  },
  {
    panelCode: 'agent_workspace',
    moduleCode: 'agent_workspace_module',
    panelName: '智能工作台',
    panelType: 'workflow',
    routePath: '/agent-workspace',
    componentName: 'AgentWorkspacePage',
    menuGroup: '研究优化',
    icon: '🧭',
    order: 118,
    permissions: [],
  },
  {
    panelCode: 'feature_snapshots',
    moduleCode: 'multidim_feature_module',
    panelName: '特征数据健康',
    panelType: 'analytics',
    routePath: '/feature-snapshots',
    componentName: 'AnalysisPage',
    menuGroup: '研究优化',
    icon: 'radar',
    order: 105,
    permissions: [],
  },
  {
    panelCode: 'upset_research',
    moduleCode: 'upset_intelligence_module',
    panelName: '冷门研究',
    panelType: 'analytics',
    routePath: '/upsets',
    componentName: 'UpsetsPage',
    menuGroup: '研究优化',
    icon: '🧊',
    order: 120,
    permissions: [],
  },
  {
    panelCode: 'backtest_lab',
    moduleCode: 'model_research_module',
    panelName: '策略验证',
    panelType: 'analytics',
    routePath: '/backtest',
    componentName: 'BacktestPage',
    menuGroup: '研究优化',
    icon: '⏪',
    order: 130,
    permissions: [],
  },
  {
    panelCode: 'pool_lottery',
    moduleCode: 'pool_lottery_module',
    panelName: '足彩彩池',
    panelType: 'workflow',
    routePath: '/pool',
    componentName: 'PoolPage',
    menuGroup: '策略实验',
    icon: '🎱',
    order: 210,
    permissions: [],
  },
  {
    panelCode: 'data_health',
    moduleCode: 'ops_admin',
    panelName: '系统监控',
    panelType: 'admin',
    routePath: '/data-health',
    componentName: 'DataHealthPage',
    menuGroup: '运维设置',
    icon: '🗄️',
    order: 310,
    permissions: [],
  },
  {
    panelCode: 'module_admin',
    moduleCode: 'module_runtime_core',
    panelName: '功能模块',
    panelType: 'admin',
    routePath: '/modules',
    componentName: 'ModulesPage',
    menuGroup: '运维设置',
    icon: '🧩',
    order: 320,
    permissions: [],
  },
  {
    panelCode: 'settings',
    moduleCode: 'local_settings_core',
    panelName: '系统设置',
    panelType: 'admin',
    routePath: '/settings',
    componentName: 'SettingsPage',
    menuGroup: '运维设置',
    icon: '⚙️',
    order: 330,
    permissions: [],
  },
  {
    panelCode: 'codex_console',
    moduleCode: 'codex_agent_module',
    panelName: '智能代理',
    panelType: 'agent',
    routePath: '/agents',
    componentName: 'AgentPanel',
    menuGroup: '运维设置',
    icon: '🤖',
    order: 340,
    permissions: [],
  },
];
