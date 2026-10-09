import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ReportAutomationPanel from './ReportAutomationPanel';

const apiMocks = vi.hoisted(() => ({ get: vi.fn(), save: vi.fn() }));

vi.mock('../../core/apiClient', () => ({
  api: { reportAutomation: { get: apiMocks.get, save: apiMocks.save } },
}));

describe('ReportAutomationPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
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
  it('recovers a failed initial setting read without saving anything', async () => {
    apiMocks.get.mockRejectedValueOnce(new Error('设置读取失败'));
    render(<ReportAutomationPanel />); await screen.findByRole('alert');
    expect(screen.getByRole('button',{name:'开启自动生成'})).toBeDisabled();
    fireEvent.click(screen.getByRole('button',{name:'刷新自动报告设置'}));
    await screen.findByText('自动生成已关闭'); expect(apiMocks.save).not.toHaveBeenCalled();
  });
  it('retains settings on refresh failure and blocks an uncertain write', async () => {
    render(<ReportAutomationPanel />); await screen.findByText('自动生成已关闭');
    apiMocks.get.mockRejectedValueOnce(new Error('读取失败'));
    fireEvent.click(screen.getByRole('button',{name:'刷新自动报告设置'}));
    await screen.findByRole('alert'); expect(screen.getByText('自动生成已关闭')).toBeInTheDocument();
    expect(screen.getByRole('button',{name:'开启自动生成'})).toBeDisabled();
  });
  it('serializes saving and prevents a concurrent setting refresh', async () => {
    let resolve!: (v:unknown)=>void; apiMocks.save.mockReturnValueOnce(new Promise(r=>{resolve=r;}));
    render(<ReportAutomationPanel />); await screen.findByText('自动生成已关闭');
    fireEvent.click(screen.getByRole('button',{name:'开启自动生成'}));
    fireEvent.click(screen.getByRole('button',{name:'保存中…'}));
    expect(screen.getByRole('button',{name:'刷新自动报告设置'})).toBeDisabled();
    expect(apiMocks.save).toHaveBeenCalledTimes(1);
    resolve({automation:{enabled:true,agentReady:true,agentCode:'post_match_report_agent',providerName:'OpenAI',model:'gpt-5-mini'}});
    await screen.findByText('自动生成已开启');
  });
  it('failed save leaves settings intact and can be retried', async () => {
    apiMocks.save.mockRejectedValueOnce(new Error('保存失败'));
    render(<ReportAutomationPanel />); await screen.findByText('自动生成已关闭');
    fireEvent.click(screen.getByRole('button',{name:'开启自动生成'}));
    expect(await screen.findByRole('alert')).toHaveTextContent('保存失败'); expect(screen.getByText('自动生成已关闭')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button',{name:'开启自动生成'})); await screen.findByText('自动生成已开启');
  });

  it('invalid read cannot enable the writer and a contradictory save stays failed', async () => {
    apiMocks.get.mockResolvedValueOnce({automation:{enabled:'false',agentReady:true,agentCode:'post_match_report_agent'}});
    render(<ReportAutomationPanel />); expect(await screen.findByRole('alert')).toHaveTextContent('设置格式不正确');
    expect(screen.getByRole('button',{name:'开启自动生成'})).toBeDisabled();
    fireEvent.click(screen.getByRole('button',{name:'刷新自动报告设置'})); await screen.findByText('自动生成已关闭');
    apiMocks.save.mockResolvedValueOnce({automation:{enabled:false,agentReady:true,agentCode:'post_match_report_agent'}});
    fireEvent.click(screen.getByRole('button',{name:'开启自动生成'}));
    expect(await screen.findByRole('alert')).toHaveTextContent('保存结果与所选状态不一致'); expect(screen.getByText('自动生成已关闭')).toBeInTheDocument();
  });

});
