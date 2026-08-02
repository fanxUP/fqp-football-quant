import { describe, expect, it } from 'vitest';
import type { BettingTicket } from './types';
import {
  calculateLedgerStats,
  formatTicketDate,
  groupTicketsByDate,
  ticketOutcome,
  ticketOutcomeLabel,
  ticketOutcomeWatermark,
  ticketKindLabel,
  ticketOwnerLabel,
  ticketPrimaryMatchCode,
  ticketPrimaryMatchLabel,
  ticketSourceLabel,
} from './bettingTickets';

function ticket(partial: Partial<BettingTicket>): BettingTicket {
  return {
    ticketUid: partial.ticketUid ?? 'simulator:1',
    ticketNumber: partial.ticketNumber ?? '20260707001',
    legacyId: partial.legacyId ?? 1,
    owner: partial.owner ?? 'me',
    kind: partial.kind ?? 'simulation',
    source: partial.source ?? 'manual',
    status: partial.status ?? 'pending',
    date: partial.date ?? '2026-07-07',
    createdAt: partial.createdAt ?? '2026-07-07T10:00:00',
    title: partial.title ?? '投注票 #1',
    playType: partial.playType ?? 'spf',
    passType: partial.passType ?? 'single',
    multiple: partial.multiple ?? 1,
    betCount: partial.betCount ?? 1,
    matchCount: partial.matchCount ?? 1,
    stake: partial.stake ?? 2,
    maxPrize: partial.maxPrize ?? 4,
    settledAmount: partial.settledAmount ?? null,
    profitLoss: partial.profitLoss ?? null,
    roi: partial.roi ?? null,
    itemCount: partial.itemCount ?? 1,
    route: partial.route ?? '/simulator/history/1',
    items: partial.items,
  };
}

describe('bettingTickets', () => {
  it('formats missing dates into the ledger fallback bucket', () => {
    expect(formatTicketDate(null)).toBe('未归档');
    expect(formatTicketDate('2026-07-07T12:30:00')).toBe('2026-07-07');
  });

  it('labels owners and ticket kinds for the lottery ledger', () => {
    expect(ticketOwnerLabel('me')).toBe('我的彩票');
    expect(ticketOwnerLabel('agent')).toBe('智能代理的彩票');
    expect(ticketKindLabel(ticket({ kind: 'real' }))).toBe('彩票');
    expect(ticketKindLabel(ticket({ kind: 'simulation' }))).toBe('投注票');
    expect(ticketKindLabel(ticket({ source: 'agent_recommendation' }))).toBe('智能代理推荐票');
  });

  it('groups tickets by date newest first', () => {
    const groups = groupTicketsByDate([
      ticket({ ticketUid: 'a', date: '2026-07-06' }),
      ticket({ ticketUid: 'b', date: '2026-07-07' }),
      ticket({ ticketUid: 'c', date: '2026-07-06' }),
    ]);

    expect(groups.map(([date]) => date)).toEqual(['2026-07-07', '2026-07-06']);
    expect(groups[1][1].map((item) => item.ticketUid)).toEqual(['a', 'c']);
  });

  it('calculates ledger totals from unified tickets', () => {
    const stats = calculateLedgerStats([
      ticket({ stake: 10, status: 'pending' }),
      ticket({ stake: 20, status: 'settled', profitLoss: 12 }),
    ]);

    expect(stats).toEqual({ total: 2, stake: 30, settled: 1, pending: 1, profitLoss: 12 });
  });

  it('derives the lottery card outcome from settlement state', () => {
    const won = ticket({ status: 'settled', isWon: true, profitLoss: 18 });
    const lost = ticket({ status: 'settled', isWon: false, profitLoss: -10 });
    const pending = ticket({ status: 'pending', profitLoss: null });

    expect(ticketOutcome(won)).toBe('won');
    expect(ticketOutcome(lost)).toBe('lost');
    expect(ticketOutcome(pending)).toBe('pending');
    expect(ticketOutcomeLabel(won)).toBe('赢');
    expect(ticketOutcomeWatermark(lost)).toBe('输');
    expect(ticketOutcomeLabel(pending)).toBe('未结算');
  });

  it('labels ticket sources for card metadata', () => {
    expect(ticketSourceLabel(ticket({ source: 'ocr', kind: 'real' }))).toBe('OCR 识别');
    expect(ticketSourceLabel(ticket({ source: 'agent_recommendation' }))).toBe('智能代理推荐');
    expect(ticketSourceLabel(ticket({ source: 'manual', kind: 'real' }))).toBe('手工录入');
    expect(ticketSourceLabel(ticket({ source: 'manual', kind: 'simulation' }))).toBe('投注台');
  });

  it('summarizes the primary match for compact lottery cards', () => {
    const withItem = ticket({
      items: [
        {
          matchId: 1001,
          matchCode: '周二001',
          homeTeam: '阿森纳',
          awayTeam: '切尔西',
          playType: 'spf',
          optionCode: '3',
          optionName: '胜',
          spValue: 1.8,
        },
      ],
    });

    expect(ticketPrimaryMatchCode(withItem)).toBe('周二001');
    expect(ticketPrimaryMatchLabel(withItem)).toBe('阿森纳 VS 切尔西');
    expect(ticketPrimaryMatchCode(ticket({ items: [] }))).toBe('比赛编号待补全');
    expect(ticketPrimaryMatchLabel(ticket({ matchCount: 2, itemCount: 2, items: [] }))).toBe('2 场比赛');
  });
});
