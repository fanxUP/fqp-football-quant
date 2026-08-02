import { describe, expect, it } from 'vitest';
import { buildTaskMarkdown } from './archiveHelpers';

const task = {
  id: 24,
  title: '核对官方赔率来源',
  agentCode: 'review_agent',
  providerCode: 'openai',
  model: 'gpt-5',
  reviewNote: '已人工比对官方页面。',
  prompt: '整理本场比赛的官方赔率。',
  response: '等待人工核验。',
  reviewedAt: '2026-08-02T10:30:00+08:00',
  createdAt: '2026-08-02T10:00:00+08:00',
};

describe('buildTaskMarkdown', () => {
  it('保留当前核验状态与完整的人工核验历史', () => {
    const markdown = buildTaskMarkdown(task, [
      { id: 2, action: 'revoked', reviewNote: null, createdAt: '2026-08-02T11:00:00+08:00' },
      { id: 1, action: 'confirmed', reviewNote: '已人工比对官方页面。', createdAt: '2026-08-02T10:30:00+08:00' },
    ]);

    expect(markdown).toContain('## 核验历史');
    expect(markdown).toContain('已撤销确认');
    expect(markdown).toContain('已确认');
    expect(markdown).toContain('已人工比对官方页面。');
    expect(markdown).toContain('模型输出为非可信内容，请人工核验后使用。');
  });
});
