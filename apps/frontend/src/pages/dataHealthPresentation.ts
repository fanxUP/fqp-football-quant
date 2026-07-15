export interface PipelineSource {
  name: string;
  source_type: string;
  status: string;
  last_success: string | null;
  last_failure: string | null;
  failures: number;
  latency_ms: number;
}

export interface PipelineJob {
  code: string;
  name: string;
  status: string;
  finished_at: string | null;
  error: string | null;
  schedule: string;
  category: 'official' | 'model' | 'review';
}

export interface PipelineStatus {
  sources: PipelineSource[];
  jobs: PipelineJob[];
}

export interface DataHealthRow {
  key: string;
  name: string;
  type: 'official' | 'supplemental' | 'model' | 'review';
  status: 'ok' | 'warning' | 'error' | 'info';
  detail: string;
}

const SOURCE_NAMES: Record<string, string> = {
  'sporttery:results': '官方竞彩赛果 (sporttery.cn)',
  'sporttery:odds': '官方竞彩赔率 (sporttery.cn)',
  'sporttery:schedule': '官方竞彩赛程 (sporttery.cn)',
  'sporttery_v2:schedule': '官方竞彩赛程 (sporttery.cn)',
  'sporttery:traditional_lottery': '传统足彩 (sporttery.cn)',
  '500.com:supplemental': '500.com 赛果补充源',
};

export function formatPipelineTime(value: string | null): string {
  if (!value) return '尚无记录';
  return new Date(value).toLocaleString('zh-CN', { hour12: false });
}

function sourceRow(source: PipelineSource): DataHealthRow {
  const sourceKey = `${source.name}:${source.source_type}`;
  const isSupplemental = source.source_type === 'supplemental';
  const isHealthy = source.status === 'ok';
  const isStale = source.status === 'stale';
  const eventTime = isHealthy ? source.last_success : source.last_failure;
  return {
    key: `source:${sourceKey}`,
    name: SOURCE_NAMES[sourceKey] ?? `${source.name} · ${source.source_type}`,
    type: isSupplemental ? 'supplemental' : 'official',
    status: isHealthy ? 'ok' : (isStale || isSupplemental ? 'warning' : 'error'),
    detail: isStale
      ? `状态已过期: 最近成功 ${formatPipelineTime(source.last_success)} · 请检查调度服务`
      : isHealthy
      ? `最近成功: ${formatPipelineTime(eventTime)} · 延迟 ${source.latency_ms}ms`
      : `最近失败: ${formatPipelineTime(eventTime)} · 累计失败 ${source.failures} 次`,
  };
}

function jobRow(job: PipelineJob): DataHealthRow {
  const statusMap: Record<string, DataHealthRow['status']> = {
    success: 'ok',
    failed: 'error',
    running: 'info',
    skipped: 'warning',
    stale: 'warning',
    pending: 'info',
  };
  const statusLabel: Record<string, string> = {
    success: '最近成功',
    failed: '最近失败',
    running: '正在执行',
    skipped: '最近跳过',
    stale: '状态已过期',
    pending: '尚未运行',
  };
  return {
    key: `job:${job.code}`,
    name: job.name,
    type: job.category,
    status: statusMap[job.status] ?? 'warning',
    detail: `${statusLabel[job.status] ?? '状态未知'}: ${formatPipelineTime(job.finished_at)} · ${job.schedule}`,
  };
}

export function buildDataHealthRows(pipeline: PipelineStatus | null): DataHealthRow[] {
  if (!pipeline) return [];
  return [...pipeline.sources.map(sourceRow), ...pipeline.jobs.map(jobRow)];
}
