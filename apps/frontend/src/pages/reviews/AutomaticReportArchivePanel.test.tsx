import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import AutomaticReportArchivePanel from './AutomaticReportArchivePanel';

const apiMocks = vi.hoisted(() => ({ archive: vi.fn() }));

vi.mock('../../core/apiClient', () => ({
  api: { reportAutomation: { archive: apiMocks.archive } },
}));

describe('AutomaticReportArchivePanel', () => {
  beforeEach(() => {
    apiMocks.archive.mockResolvedValue({
      task: { id: 21, providerCode: 'openai', model: 'gpt-5-mini', response: '复盘结论', reviewedAt: null },
    });
  });

  it('shows only the archived automatic report and its manual-verification boundary', async () => {
    render(<AutomaticReportArchivePanel sourceType="post_daily" sourceRef="2026-08-09" />);

    expect(await screen.findByText('自动赛后报告')).toBeInTheDocument();
    expect(screen.getByText('复盘结论')).toBeInTheDocument();
    expect(screen.getByText('模型输出仅供人工核验')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '前往智能工作台核验' })).toHaveAttribute('href', '#/agent-workspace');
    expect(apiMocks.archive).toHaveBeenCalledWith('post_daily', '2026-08-09');
  });

  it('keeps a quiet pending state when this report has no automatic archive', async () => {
    apiMocks.archive.mockResolvedValueOnce({ task: null });
    render(<AutomaticReportArchivePanel sourceType="post_monthly" sourceRef="2026-08" />);

    await waitFor(() => expect(apiMocks.archive).toHaveBeenCalled());
    expect(screen.getByText('本期暂无自动赛后报告')).toBeInTheDocument();
  });

  it('shows an explicit error when the archive request fails', async () => {
    apiMocks.archive.mockRejectedValueOnce(new Error('network'));
    render(<AutomaticReportArchivePanel sourceType="post_daily" sourceRef="2026-08-09" />);

    expect(await screen.findByRole('alert')).toHaveTextContent('自动赛后报告读取失败，请稍后重试。');
    expect(screen.queryByText('本期暂无自动赛后报告')).not.toBeInTheDocument();
  });
});
