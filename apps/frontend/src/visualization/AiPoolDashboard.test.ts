import { createElement } from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import AiPoolDashboard, { calculateSettledProfitRate } from './AiPoolDashboard';

describe('Agent pool financial metrics', () => {
  it('uses settled stake instead of newly committed stake for realized profit rate', () => {
    expect(calculateSettledProfitRate(20, 40)).toBe(0.5);
    expect(calculateSettledProfitRate(20, 0)).toBe(0);
  });
});

describe('Agent pool independent reads', () => {
  const base = {
    kpis: [{ key: 'ai_stake_today', label: 'AI 模拟投入', value: 120 }],
    models: [],
    extras: { current_round_label: null, business_date: '2026-10-16' },
  };

  it('keeps unknown counts as missing while rendering model status', () => {
    render(createElement(AiPoolDashboard, {
      ...base,
      kpis: [],
      pageStats: { matchCount: null, predictionCount: null, activeTicketCount: null, ticketLedgerCount: null },
    }));
    expect(screen.getByText('预测累计 — 条')).toBeInTheDocument();
    expect(screen.getByText('模型运行')).toBeInTheDocument();
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(3);
    expect(screen.getByText('今日资金及 KPI 数据尚未获取')).toBeInTheDocument();
    expect(screen.queryByText('AI 当日盈亏')).not.toBeInTheDocument();
  });

  it.each([true, false])('keeps KPIs visible when model loading=%s or fails', (loading) => {
    render(createElement(AiPoolDashboard, { ...base, loading, error: loading ? null : '请求失败' }));
    expect(screen.getByText('策略投入')).toBeInTheDocument();
    expect(screen.getByRole(loading ? 'status' : 'alert')).toHaveTextContent(loading ? '模型表现加载中' : '请求失败');
  });
});
