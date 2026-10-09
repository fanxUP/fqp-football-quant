import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import AutomaticReportArchivePanel from './AutomaticReportArchivePanel';

const apiMocks = vi.hoisted(() => ({ archive: vi.fn() }));

vi.mock('../../core/apiClient', () => ({
  api: { reportAutomation: { archive: apiMocks.archive } },
}));

describe('AutomaticReportArchivePanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
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

    expect(await screen.findByRole('alert')).toHaveTextContent('network');
    expect(screen.queryByText('本期暂无自动赛后报告')).not.toBeInTheDocument();
  });
  it('retries and keeps this period text on refresh failure', async () => {
    apiMocks.archive.mockRejectedValueOnce(new Error('归档读取失败'));
    render(<AutomaticReportArchivePanel sourceType="post_daily" sourceRef="2026-08-09" />);
    await screen.findByRole('alert'); fireEvent.click(screen.getByRole('button',{name:'刷新自动报告归档'}));
    await screen.findByText('复盘结论'); apiMocks.archive.mockRejectedValueOnce(new Error('网络失败'));
    fireEvent.click(screen.getByRole('button',{name:'刷新自动报告归档'}));
    expect(await screen.findByRole('alert')).toHaveTextContent('保留本查询上次成功数据');
    expect(screen.getByText('复盘结论')).toBeInTheDocument();
  });
  it('clears old-period text when new period fails', async () => {
    const {rerender}=render(<AutomaticReportArchivePanel sourceType="post_daily" sourceRef="2026-08-09" />);
    await screen.findByText('复盘结论'); apiMocks.archive.mockRejectedValueOnce(new Error('新报告失败'));
    rerender(<AutomaticReportArchivePanel sourceType="post_monthly" sourceRef="2026-09" />);
    await screen.findByRole('alert'); expect(screen.queryByText('复盘结论')).not.toBeInTheDocument();
  });
  it('rejects mismatched source identity and marks legacy missing references', async () => {
    apiMocks.archive.mockResolvedValueOnce({task:{id:21,response:'错误期间',sourceType:'post_daily',sourceRef:'2026-08-08'}});
    const {rerender}=render(<AutomaticReportArchivePanel sourceType="post_daily" sourceRef="2026-08-09" />);
    expect(await screen.findByRole('alert')).toHaveTextContent('报告归档与所选期间不一致');
    expect(screen.queryByText('错误期间')).not.toBeInTheDocument();
    rerender(<AutomaticReportArchivePanel sourceType="post_monthly" sourceRef="2026-09" />);
    expect(await screen.findByText(/历史归档缺少来源字段/)).toBeInTheDocument();
  });
  it('successful empty clears the last archive without scheduling generation', async () => {
    render(<AutomaticReportArchivePanel sourceType="post_daily" sourceRef="2026-08-09" />);
    await screen.findByText('复盘结论'); apiMocks.archive.mockResolvedValueOnce({task:null});
    fireEvent.click(screen.getByRole('button',{name:'刷新自动报告归档'}));
    await screen.findByText('本期暂无自动赛后报告'); expect(screen.queryByText('复盘结论')).not.toBeInTheDocument();
  });

  it('ignores late text from an unmounted previous-period query', async () => {
    let resolve!: (v:unknown)=>void; apiMocks.archive.mockReturnValueOnce(new Promise(r=>{resolve=r;}));
    const {rerender}=render(<AutomaticReportArchivePanel sourceType="post_daily" sourceRef="2026-08-08" />);
    rerender(<AutomaticReportArchivePanel sourceType="post_daily" sourceRef="2026-08-09" />);
    await screen.findByText('复盘结论'); resolve({task:{id:1,response:'迟到的旧报告'}});
    await waitFor(()=>expect(screen.queryByText('迟到的旧报告')).not.toBeInTheDocument());
    expect(screen.getByText('复盘结论')).toBeInTheDocument();
  });

});
