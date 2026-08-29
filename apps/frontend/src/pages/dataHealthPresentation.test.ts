import { describe, expect, it } from 'vitest';
import { buildDataHealthRows } from './dataHealthPresentation';

describe('data health presentation', () => {
  it('renders degraded feature quality as a warning with its real detail', () => {
    const rows = buildDataHealthRows({
      sources: [],
      jobs: [{
        code: 'feature_snapshot_build',
        name: '特征快照构建',
        status: 'degraded',
        finished_at: '2026-07-16T06:00:00Z',
        error: null,
        detail: '平均特征完整度 22.5%',
        schedule: '每6小时',
        category: 'model',
      }],
    });

    expect(rows[0].status).toBe('warning');
    expect(rows[0].detail).toContain('数据降级');
    expect(rows[0].detail).toContain('平均特征完整度 22.5%');
  });

  it('renders policy-skipped recovery jobs as informational, not as an outage', () => {
    const rows = buildDataHealthRows({
      sources: [],
      jobs: [
        {
          code: 'minute_odds',
          name: '分钟赔率历史补偿',
          status: 'policy_skipped',
          finished_at: '2026-08-29T07:43:00Z',
          error: null,
          schedule: '启动恢复',
          category: 'official',
        },
        {
          code: 'future_job',
          name: '尚未到期任务',
          status: 'not_due',
          finished_at: null,
          error: null,
          schedule: '每日 16:00',
          category: 'model',
        },
      ],
    });

    expect(rows.map((row) => row.status)).toEqual(['info', 'info']);
    expect(rows[0].detail).toContain('按策略跳过');
    expect(rows[1].detail).toContain('当前周期未到期');
  });
});
