import { describe, expect, it } from 'vitest';
import { buildComparisonMarkdown, buildTaskMarkdown } from './archiveHelpers';

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

  it('将模型输出和任务材料封装为安全代码块', () => {
    const markdown = buildTaskMarkdown({
      ...task,
      title: '# 伪造标题',
      prompt: '```markdown\n![外部图片](https://example.com/a.png)\n```',
      response: '[伪造链接](https://example.com)',
    });

    expect(markdown).toContain('# \\# 伪造标题');
    expect(markdown).toContain('````\n```markdown');
    expect(markdown).toContain('![外部图片](https://example.com/a.png)');
    expect(markdown).toContain('```\n[伪造链接](https://example.com)\n```');
  });
});

describe('buildComparisonMarkdown', () => {
  it('保留批次统计、人工结论和每个模型的原始输出', () => {
    const markdown = buildComparisonMarkdown({
      id: 'comparison-001', requestedAgentCodes: ['review_agent', 'doc_agent'], requestedCount: 2,
      succeededCount: 1, failedCount: 1, status: 'completed', createdAt: '2026-08-02T10:00:00+08:00',
      completedAt: '2026-08-02T10:01:00+08:00', reviewNote: '继续核对官方赛程。', reviewedAt: '2026-08-02T10:02:00+08:00',
    }, [task]);

    expect(markdown).toContain('成功 / 失败：1 / 1');
    expect(markdown).toContain('继续核对官方赛程。');
    expect(markdown).toContain('## 复盘代理 · openai · gpt\\-5');
    expect(markdown).toContain('等待人工核验。');
  });
});
