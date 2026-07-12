/** Shared label maps — single source of truth for all code→Chinese mappings. */

// ── Play types (canonical codes → Chinese) ──────────────────────

export const PLAY_TYPE_LABELS: Record<string, string> = {
  spf: '胜平负',
  rqspf: '让球胜平负',
  zjq: '总进球数',
  bf: '比分',
  bqc: '半全场',
  hhgg: '混合过关',
  // legacy aliases
  score: '比分',
  total_goals: '总进球数',
  half_full: '半全场',
};

export function playTypeLabel(code: string): string {
  return PLAY_TYPE_LABELS[code] || code;
}

// ── Pass types ──────────────────────────────────────────────────

export const PASS_TYPE_LABELS: Record<string, string> = {
  single: '单关',
  '2x1': '2串1', '3x1': '3串1', '4x1': '4串1', '5x1': '5串1',
  '6x1': '6串1', '7x1': '7串1', '8x1': '8串1',
  '3x3': '3串3', '3x4': '3串4',
  '4x4': '4串4', '4x5': '4串5', '4x6': '4串6', '4x11': '4串11',
  '5x5': '5串5', '5x6': '5串6', '5x10': '5串10', '5x16': '5串16',
  '5x20': '5串20', '5x26': '5串26',
  '6x6': '6串6', '6x7': '6串7', '6x15': '6串15', '6x20': '6串20',
  '6x22': '6串22', '6x35': '6串35', '6x42': '6串42', '6x50': '6串50', '6x57': '6串57',
  '7x7': '7串7', '7x8': '7串8', '7x21': '7串21', '7x35': '7串35', '7x120': '7串120',
  '8x8': '8串8', '8x9': '8串9', '8x28': '8串28', '8x56': '8串56',
  '8x70': '8串70', '8x247': '8串247',
};

export function passTypeLabel(code: string): string {
  if (code.includes(',')) {
    return code.split(',').map((item) => PASS_TYPE_LABELS[item.trim()] || item.trim()).join(' + ');
  }
  return PASS_TYPE_LABELS[code] || code;
}

// ── SPF/RQSPF option codes ──────────────────────────────────────

export const SPF_OPTION_LABELS: Record<string, string> = {
  '3': '主胜', '1': '平', '0': '主负',
  h: '主胜', d: '平', a: '主负',
};

export const RQSPF_OPTION_LABELS: Record<string, string> = {
  '3': '主胜', '1': '平', '0': '主负',
  h: '主胜', d: '平', a: '主负',
};

export const BQC_OPTION_LABELS: Record<string, string> = {
  '33': '胜胜', '31': '胜平', '30': '胜负',
  '13': '平胜', '11': '平平', '10': '平负',
  '03': '负胜', '01': '负平', '00': '负负',
};

/** Map a play_type + option_code to a Chinese label. */
export function optionLabel(playType: string, optionCode: string): string {
  const pt = PLAY_TYPE_LABELS[playType] ? playType : playType;
  if (pt === 'spf') return SPF_OPTION_LABELS[optionCode] || optionCode;
  if (pt === 'rqspf') return RQSPF_OPTION_LABELS[optionCode] || optionCode;
  if (pt === 'bqc') return BQC_OPTION_LABELS[optionCode] || optionCode;
  if (pt === 'zjq') return optionCode === '7' || optionCode === '7+' ? '7+球' : `${optionCode}球`;
  // bf keeps the official score notation (e.g. "1:0")
  return optionCode;
}

export function normalizeWinDrawLossLabel(label: string): string {
  return label
    .replace(/让球客胜|让客胜|让负/g, '主负')
    .replace(/让球主胜|让主胜|让胜/g, '主胜')
    .replace(/让球平|让平/g, '平')
    .replace(/客胜/g, '主负');
}

// ── Status labels ───────────────────────────────────────────────

export const STATUS_LABELS: Record<string, string> = {
  // ticket statuses
  pending: '待结算',
  settled: '已结算',
  confirmed: '已确认',
  cancelled: '已取消',
  won: '已中奖',
  lost: '未中奖',
  active: '进行中',
  // match statuses
  Selling: '在售',
  Settled: '已完赛',
  Finished: '已结束',
  scheduled: '待开赛',
  Scheduled: '待开赛',
  // job statuses
  success: '成功',
  failed: '失败',
  running: '运行中',
  skipped: '已跳过',
  // agent task statuses
  completed: '已完成',
  in_progress: '进行中',
  open: '待处理',
};

export function statusLabel(code: string): string {
  return STATUS_LABELS[code] || code;
}

// ── Source type labels ──────────────────────────────────────────

export const SOURCE_TYPE_LABELS: Record<string, string> = {
  manual: '手动录入',
  simulator: '投注器',
  simulation: '投注推荐',
  agent: 'Agent',
};

export function sourceTypeLabel(code: string): string {
  return SOURCE_TYPE_LABELS[code] || code;
}

// ── Risk level labels ───────────────────────────────────────────

export const RISK_LABELS: Record<string, string> = {
  low: '低风险',
  medium: '中风险',
  high: '高风险',
  L1: 'L1-极低',
  L2: 'L2-低',
  L3: 'L3-中',
  L4: 'L4-高',
  L5: 'L5-极高',
};

export function riskLabel(code: string): string {
  return RISK_LABELS[code] || code;
}

// ── Agent action labels ─────────────────────────────────────────

export const ACTION_LABELS: Record<string, string> = {
  task_create: '创建任务',
  task_complete: '完成任务',
  code_patch: '代码修复',
  review: '审查',
  analyze: '分析',
  collect: '采集',
  predict: '预测',
  settle: '结算',
  backup: '备份',
  audit: '审计',
};

export function actionLabel(code: string): string {
  return ACTION_LABELS[code] || code;
}
