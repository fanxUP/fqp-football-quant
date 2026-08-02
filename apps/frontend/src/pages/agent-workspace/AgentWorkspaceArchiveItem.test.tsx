import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import AgentWorkspaceArchiveItem from './AgentWorkspaceArchiveItem';

const apiMocks = vi.hoisted(() => ({ reviewHistory: vi.fn() }));
const toastMocks = vi.hoisted(() => ({ error: vi.fn() }));
const helperMocks = vi.hoisted(() => ({ downloadTaskMarkdown: vi.fn() }));

vi.mock('../../core/apiClient', () => ({
  api: { agentWorkspace: { reviewHistory: apiMocks.reviewHistory } },
}));

vi.mock('../../shared/components/Toast', () => ({ toast: toastMocks }));

vi.mock('./archiveHelpers', () => ({
  downloadTaskMarkdown: helperMocks.downloadTaskMarkdown,
  formatTime: (value: string | null) => value ?? '时间未知',
}));

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

describe('AgentWorkspaceArchiveItem', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('按需加载并显示确认与撤销确认的核验历史', async () => {
    apiMocks.reviewHistory.mockResolvedValue({
      events: [
        { id: 2, action: 'revoked', reviewNote: null, createdAt: '2026-08-02T11:00:00+08:00' },
        { id: 1, action: 'confirmed', reviewNote: '已人工比对官方页面。', createdAt: '2026-08-02T10:30:00+08:00' },
      ],
    });
    render(<AgentWorkspaceArchiveItem task={task} busy={false} onSetReviewed={vi.fn()} onRemove={vi.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: '核验历史' }));

    await waitFor(() => expect(apiMocks.reviewHistory).toHaveBeenCalledWith(24));
    expect(await screen.findByRole('list', { name: '核验历史' })).toBeInTheDocument();
    expect(screen.getByText('已撤销确认')).toBeInTheDocument();
    expect(screen.getByText('已确认')).toBeInTheDocument();
    expect(screen.getAllByText(/已人工比对官方页面/)).toHaveLength(2);
  });

  it('为空时明确提示，并在加载失败时反馈错误', async () => {
    apiMocks.reviewHistory.mockResolvedValueOnce({ events: [] }).mockRejectedValueOnce(new Error('服务暂不可用'));
    render(<AgentWorkspaceArchiveItem task={task} busy={false} onSetReviewed={vi.fn()} onRemove={vi.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: '核验历史' }));
    expect(await screen.findByText('尚无核验历史。')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '核验历史' }));
    await waitFor(() => expect(toastMocks.error).toHaveBeenCalledWith('服务暂不可用'));
  });

  it('待确认任务保留人工备注并提交给上层处理', () => {
    const onSetReviewed = vi.fn();
    render(<AgentWorkspaceArchiveItem task={{ ...task, reviewedAt: null, reviewNote: null }} busy={false} onSetReviewed={onSetReviewed} onRemove={vi.fn()} />);

    fireEvent.change(screen.getByLabelText('核验备注（可选）'), { target: { value: '来源已复核。' } });
    fireEvent.click(screen.getByRole('button', { name: '确认并归档' }));

    expect(onSetReviewed).toHaveBeenCalledWith(expect.objectContaining({ id: 24 }), '来源已复核。');
  });

  it('撤销确认后的服务端状态会清空旧核验备注', () => {
    const { rerender } = render(
      <AgentWorkspaceArchiveItem task={task} busy={false} onSetReviewed={vi.fn()} onRemove={vi.fn()} />,
    );

    rerender(
      <AgentWorkspaceArchiveItem
        task={{ ...task, reviewedAt: null, reviewNote: null }}
        busy={false}
        onSetReviewed={vi.fn()}
        onRemove={vi.fn()}
      />,
    );

    expect(screen.getByLabelText('核验备注（可选）')).toHaveValue('');
  });

  it('导出时附带核验历史，且只在未加载时读取一次', async () => {
    const events = [{ id: 1, action: 'confirmed' as const, reviewNote: '已复核。', createdAt: '2026-08-02T10:30:00+08:00' }];
    apiMocks.reviewHistory.mockResolvedValue({ events });
    render(<AgentWorkspaceArchiveItem task={task} busy={false} onSetReviewed={vi.fn()} onRemove={vi.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: '导出 Markdown' }));

    await waitFor(() => expect(helperMocks.downloadTaskMarkdown).toHaveBeenCalledWith(task, events));
    expect(apiMocks.reviewHistory).toHaveBeenCalledWith(24);
  });
});
