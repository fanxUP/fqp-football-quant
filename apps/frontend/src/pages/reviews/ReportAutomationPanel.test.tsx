import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ReportAutomationPanel from './ReportAutomationPanel';

const apiMocks = vi.hoisted(() => ({ get: vi.fn(), save: vi.fn() }));

vi.mock('../../core/apiClient', () => ({
  api: { reportAutomation: { get: apiMocks.get, save: apiMocks.save } },
}));

describe('ReportAutomationPanel', () => {
  beforeEach(() => {
    apiMocks.get.mockResolvedValue({
      automation: {
        enabled: false, agentCode: 'post_match_report_agent', agentReady: true,
        providerName: 'OpenAI', model: 'gpt-5-mini',
      },
    });
    apiMocks.save.mockResolvedValue({
      automation: {
        enabled: true, agentCode: 'post_match_report_agent', agentReady: true,
        providerName: 'OpenAI', model: 'gpt-5-mini',
      },
    });
  });

  it('shows the disabled state and enables only the dedicated ready Agent', async () => {
    render(<ReportAutomationPanel />);

    expect(await screen.findByText('自动生成已关闭')).toBeInTheDocument();
    expect(screen.getByText('OpenAI · gpt-5-mini')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '开启自动生成' }));

    await waitFor(() => expect(apiMocks.save).toHaveBeenCalledWith(true));
    expect(await screen.findByText('自动生成已开启')).toBeInTheDocument();
  });

  it('explains why an unready Agent cannot be enabled', async () => {
    apiMocks.get.mockResolvedValueOnce({
      automation: {
        enabled: false, agentCode: 'post_match_report_agent', agentReady: false,
        providerName: null, model: null,
      },
    });
    render(<ReportAutomationPanel />);

    expect(await screen.findByText('需先在模型接入中启用并测试“自动赛后报告 Agent”')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '开启自动生成' })).toBeDisabled();
  });
});
