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
});
