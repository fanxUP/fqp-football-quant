import type { ThemeDefinition, ThemeId } from './types';

const defaults = {
  density: 'compact',
  motion: 'light',
  radius: 'subtle',
  cardStyle: 'bordered',
  numberFont: 'mono',
  chartStyle: 'professional',
} as const;

export const AVAILABLE_THEME_IDS: ThemeId[] = [
  'redline-quant',
  'black-gold-terminal',
  'polar-lab',
  'deep-navy',
];

export const THEME_REGISTRY: ThemeDefinition[] = [
  {
    id: 'redline-quant', name: '黑红量化', description: '冷峻专业的足球量化决策终端', category: 'professional', mode: 'dark', available: true,
    preview: { background: '#070809', surface: '#111318', primary: '#E32035', secondary: '#2ECF8D' }, defaults,
  },
  {
    id: 'black-gold-terminal', name: '黑金量化终端', description: '克制稳重的机构级投资终端', category: 'professional', mode: 'dark', available: true,
    preview: { background: '#08090B', surface: '#111317', primary: '#C9A968', secondary: '#45B883' }, defaults,
  },
  {
    id: 'deep-navy', name: '深海蓝机构版', description: '稳定可信的系统运行中心', category: 'professional', mode: 'dark', available: true,
    preview: { background: '#07111F', surface: '#0E1D2D', primary: '#2D7EF7', secondary: '#2BB6C4' }, defaults,
  },
  {
    id: 'graphite-minimal', name: '石墨极简', description: '高密度、低干扰的专业工作台', category: 'professional', mode: 'dark', available: false,
    preview: { background: '#111315', surface: '#1A1D20', primary: '#6EA8FE', secondary: '#4FC38A' }, defaults: { ...defaults, cardStyle: 'flat' },
  },
  {
    id: 'crimson-arena', name: '赤焰竞技', description: '面向比赛日的夜间球场氛围', category: 'football', mode: 'dark', available: false,
    preview: { background: '#09090B', surface: '#111216', primary: '#C91D2E', secondary: '#35C990' }, defaults,
  },
  {
    id: 'tactical-board', name: '绿茵战术板', description: '阵型、球员和比赛理解工作台', category: 'football', mode: 'dark', available: false,
    preview: { background: '#07120D', surface: '#0D1D15', primary: '#74D680', secondary: '#C9F36B' }, defaults,
  },
  {
    id: 'global-match-center', name: '全球赛事中心', description: '适合赛事日和大屏的转播包装', category: 'football', mode: 'dark', available: false,
    preview: { background: '#07101E', surface: '#0D1A2C', primary: '#235BC8', secondary: '#D1AA58' }, defaults,
  },
  {
    id: 'quantum-forecast', name: '未来预测引擎', description: '突出模型流程和概率分布的 AI 主题', category: 'future', mode: 'dark', available: false,
    preview: { background: '#070817', surface: '#101329', primary: '#3D7EFF', secondary: '#8B5CF6' }, defaults,
  },
  {
    id: 'neon-grid', name: '赛博朋克', description: '克制霓虹的数据网络和自动化界面', category: 'future', mode: 'dark', available: false,
    preview: { background: '#05060A', surface: '#0D1018', primary: '#00E5FF', secondary: '#9B5CFF' }, defaults: { ...defaults, cardStyle: 'glow', chartStyle: 'glow' },
  },
  {
    id: 'code-matrix', name: '代码矩阵', description: '面向采集、任务和日志的终端主题', category: 'future', mode: 'dark', available: false,
    preview: { background: '#020503', surface: '#071009', primary: '#00E676', secondary: '#33FF88' }, defaults: { ...defaults, density: 'terminal', radius: 'square' },
  },
  {
    id: 'polar-lab', name: '极地数据实验室', description: '适合长时间办公的数据研究浅色主题', category: 'personal', mode: 'light', available: true,
    preview: { background: '#F5F7FA', surface: '#FFFFFF', primary: '#2E7FC1', secondary: '#2AA7A0' }, defaults: { ...defaults, density: 'standard', cardStyle: 'elevated', numberFont: 'default' },
  },
  {
    id: 'anime-striker', name: '次元前锋', description: '未来学院风的轻度游戏化足球主题', category: 'personal', mode: 'dark', available: false,
    preview: { background: '#10121C', surface: '#181C2B', primary: '#5B8CFF', secondary: '#FF8FB8' }, defaults: { ...defaults, radius: 'soft', cardStyle: 'glass', numberFont: 'display' },
  },
];

export const THEME_BY_ID = new Map(THEME_REGISTRY.map((theme) => [theme.id, theme]));
