export const LANGUAGE_STORAGE_KEY = 'fqp-language';

export type AppLanguage = 'zh-CN' | 'en';

export const DEFAULT_LANGUAGE: AppLanguage = 'zh-CN';

export const LANGUAGE_OPTIONS: ReadonlyArray<{ value: AppLanguage; label: string; flag: string }> = [
  { value: 'zh-CN', label: '简体中文', flag: '🇨🇳' },
  { value: 'en', label: 'English', flag: '🇬🇧' },
];

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
