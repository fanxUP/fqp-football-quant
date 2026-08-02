export const LANGUAGE_STORAGE_KEY = 'fqp-language';

export type AppLanguage = 'zh-CN' | 'en';

export const DEFAULT_LANGUAGE: AppLanguage = 'zh-CN';

export const LANGUAGE_OPTIONS: ReadonlyArray<{ value: AppLanguage; label: string; flag: string }> = [
  { value: 'zh-CN', label: '简体中文', flag: '🇨🇳' },
  { value: 'en', label: 'English', flag: '🇬🇧' },
];

const ENGLISH_TEXT: Record<string, string> = {
  '加载中...': 'Loading...',
  '加载数据中...': 'Loading data...',
  '加载失败': 'Failed to load',
  '登录失败': 'Sign-in failed',
  '重试': 'Retry',
  '暂无数据': 'No data available',
  '最后更新': 'Last updated',
  '页面不存在': 'Page not found',
  '路径': 'Path',
  '返回': 'Back',
  '取消': 'Cancel',
  '确认': 'Confirm',
  '保存': 'Save',
  '删除': 'Delete',
  '编辑': 'Edit',
  '关闭': 'Close',
  '刷新': 'Refresh',
  '筛选': 'Filter',
  '清除': 'Clear',
  '全部': 'All',
  '状态': 'Status',
  '操作': 'Actions',
  '日期': 'Date',
  '时间': 'Time',
  '类型': 'Type',
  '名称': 'Name',
  '详情': 'Details',
  '说明': 'Description',
  '加载页面...': 'Loading page...',
  '正在进入页面...': 'Opening page...',
  '正在进入投注中心...': 'Opening betting center...',
  '请输入访问密码': 'Enter access password',
  '登录': 'Sign in',
  '登录中...': 'Signing in...',
  '今日驾驶舱': 'Today dashboard',
  '比赛中心': 'Match center',
  '赛事中心': 'Event center',
  '投注中心': 'Betting center',
  '比赛结果': 'Match results',
  '推荐票单': 'Recommendation tickets',
  '复盘中心': 'Review center',
  '今日决策分析': 'Today decision analysis',
  '特征数据健康': 'Feature data health',
  '数据源与系统监控': 'Data sources and system monitor',
  '模块管理': 'Module management',
  '模型表现': 'Model performance',
  '模型接入': 'Model providers',
  '智能工作台': 'Agent workspace',
  '智能代理中心': 'Smart agent center',
  '冷门研究': 'Upset research',
  '策略验证': 'Strategy validation',
  '赔率走势': 'Odds movement',
  '足彩彩池': 'Football pools',
};

const ENGLISH_SIDEBAR_GROUPS: Record<string, string> = {
  核心闭环: 'Core workflow',
  研究优化: 'Research',
  策略实验: 'Strategy lab',
  系统管理: 'System',
};

const ENGLISH_PANELS: Record<string, string> = {
  today_dashboard: 'Today dashboard',
  match_center: 'Match center',
  event_center: 'Event center',
  odds_movement: 'Odds movement',
  betting_center: 'Betting center',
  deep_analysis: 'Decision analysis',
  model_lab: 'Model performance',
  model_providers: 'Model providers',
  agent_workspace: 'Agent workspace',
  feature_snapshots: 'Feature health',
  upset_research: 'Upset research',
  backtest_lab: 'Strategy validation',
  pool_lottery: 'Football pools',
  data_health: 'System monitor',
  module_admin: 'Modules',
  settings: 'Settings',
  codex_console: 'Smart agents',
};

export function isAppLanguage(value: string | null): value is AppLanguage {
  return value === 'zh-CN' || value === 'en';
}

export function translateText(language: AppLanguage, text: string): string {
  if (language !== 'en') return text;
  return ENGLISH_TEXT[text] ?? text.replace(/^最后更新:\s*/, 'Last updated: ');
}

export function shellText(language: AppLanguage) {
  if (language === 'en') {
    return {
      accountActions: 'Account actions',
      language: 'Language',
      logout: 'Sign out',
      openMenu: 'Open menu',
      darkTheme: 'Switch to dark red theme',
      lightTheme: 'Switch to polar light theme',
    };
  }
  return {
    accountActions: '账户操作',
    language: '界面语言',
    logout: '退出登录',
    openMenu: '打开菜单',
    darkTheme: '切换黑红主题',
    lightTheme: '切换极地浅色',
  };
}

export function sidebarGroupLabel(language: AppLanguage, groupName: string): string {
  return language === 'en' ? ENGLISH_SIDEBAR_GROUPS[groupName] ?? groupName : groupName;
}

export function sidebarPanelLabel(language: AppLanguage, panelCode: string, fallback: string): string {
  return language === 'en' ? ENGLISH_PANELS[panelCode] ?? fallback : fallback;
}
