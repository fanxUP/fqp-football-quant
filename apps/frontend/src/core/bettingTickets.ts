import type { BettingTicket, BettingTicketOwner } from './types';

export type TicketOutcome = 'won' | 'lost' | 'pending';

export interface TicketLedgerStats {
  total: number;
  stake: number;
  settled: number;
  pending: number;
  profitLoss: number;
}

export function formatTicketDate(value: string | null | undefined): string {
  if (!value) return '未归档';
  return value.slice(0, 10);
}

export function ticketOwnerLabel(owner: BettingTicketOwner): string {
  return owner === 'agent' ? 'Agent 的彩票' : '我的彩票';
}

export function ticketKindLabel(ticket: BettingTicket): string {
  if (ticket.source === 'agent_recommendation') return 'Agent 推荐票';
  return ticket.kind === 'real' ? '彩票' : '投注票';
}

export function ticketOutcome(ticket: BettingTicket): TicketOutcome {
  if (ticket.status !== 'settled') return 'pending';
  if (ticket.isWon === true) return 'won';
  if (ticket.isWon === false) return 'lost';
  return Number(ticket.profitLoss || 0) > 0 ? 'won' : 'lost';
}

export function ticketOutcomeLabel(ticket: BettingTicket): string {
  const outcome = ticketOutcome(ticket);
  if (outcome === 'won') return '赢';
  if (outcome === 'lost') return '输';
  return '未结算';
}

export function ticketOutcomeWatermark(ticket: BettingTicket): string {
  return ticketOutcomeLabel(ticket);
}

export function ticketSourceLabel(ticket: BettingTicket): string {
  if (ticket.source === 'ocr') return 'OCR 识别';
  if (ticket.source === 'agent_recommendation') return 'Agent 推荐';
  return ticket.kind === 'real' ? '手工录入' : '投注台';
}

export function ticketPrimaryMatchLabel(ticket: BettingTicket): string {
  const first = ticket.items?.[0];
  if (!first) return `${ticket.matchCount || ticket.itemCount || 0} 场比赛`;
  return `${first.homeTeam} vs ${first.awayTeam}`;
}

export function ticketPrimaryMatchCode(ticket: BettingTicket): string {
  const first = ticket.items?.[0];
  if (!first) return '比赛编号待补全';
  return first.matchCode || (first.matchId ? String(first.matchId) : '比赛编号待补全');
}

export function calculateLedgerStats(tickets: BettingTicket[]): TicketLedgerStats {
  return tickets.reduce<TicketLedgerStats>(
    (stats, ticket) => {
      stats.total += 1;
      stats.stake += Number(ticket.stake || 0);
      if (ticket.status === 'settled') stats.settled += 1;
      if (ticket.status === 'pending') stats.pending += 1;
      stats.profitLoss += Number(ticket.profitLoss || 0);
      return stats;
    },
    { total: 0, stake: 0, settled: 0, pending: 0, profitLoss: 0 },
  );
}

export function groupTicketsByDate(tickets: BettingTicket[]): Array<[string, BettingTicket[]]> {
  const grouped = new Map<string, BettingTicket[]>();
  for (const ticket of tickets) {
    const key = formatTicketDate(ticket.date || ticket.createdAt);
    grouped.set(key, [...(grouped.get(key) ?? []), ticket]);
  }
  return [...grouped.entries()].sort(([a], [b]) => b.localeCompare(a));
}
