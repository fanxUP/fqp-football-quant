import { getPlayRule } from './bettingRules';
import type { BetSlipItem, BettingMatch, TicketOcrResult } from './types';
import { optionLabel } from '../shared/constants';

export interface OcrUnmatchedItem {
  label: string;
  reason: string;
}

export interface OcrSlipMappingResult {
  mapped: BetSlipItem[];
  unmatched: OcrUnmatchedItem[];
}

function normalizeMatchCode(value?: string): string {
  return (value || '').replace(/[^\d]/g, '').replace(/^0+/, '') || (value || '').trim();
}

function itemLabel(item: TicketOcrResult['items'][number]): string {
  return [
    item.match_code || '未知场次',
    item.play_type || 'spf',
    item.option_name || item.option_code || '未知选项',
  ].join(' ');
}

function findMatch(item: TicketOcrResult['items'][number], matches: BettingMatch[]): BettingMatch | undefined {
  const code = normalizeMatchCode(item.match_code);
  if (code) {
    const byCode = matches.find((match) => normalizeMatchCode(match.match_num_str) === code);
    if (byCode) return byCode;
  }

  if (item.home_team && item.away_team) {
    return matches.find(
      (match) =>
        match.home_team_name.includes(item.home_team || '') &&
        match.away_team_name.includes(item.away_team || ''),
    );
  }
  return undefined;
}

export function mapOcrTicketToSlip(
  ocr: TicketOcrResult,
  matches: BettingMatch[],
): OcrSlipMappingResult {
  const mapped: BetSlipItem[] = [];
  const unmatched: OcrUnmatchedItem[] = [];

  for (const item of ocr.items ?? []) {
    const match = findMatch(item, matches);
    if (!match) {
      unmatched.push({ label: itemLabel(item), reason: '未找到对应在售比赛' });
      continue;
    }

    const playType = item.play_type || 'spf';
    const oddsGroup = match.odds[playType as keyof BettingMatch['odds']];
    if (!oddsGroup) {
      unmatched.push({ label: itemLabel(item), reason: '未找到对应玩法' });
      continue;
    }

    const option = oddsGroup.options.find(
      (candidate) =>
        candidate.option_code === item.option_code ||
        (item.option_name ? candidate.option_name === item.option_name : false),
    );
    if (!option) {
      unmatched.push({ label: itemLabel(item), reason: '未找到对应选项' });
      continue;
    }

    mapped.push({
      match_id: match.match_id,
      home_team: match.home_team_name,
      away_team: match.away_team_name,
      league_name: match.league_name,
      kickoff_time: match.kickoff_time,
      play_type: playType,
      play_type_label: getPlayRule(playType).label,
      option_code: option.option_code,
      option_name: optionLabel(playType, option.option_code),
      sp_value: option.sp_value,
      handicap: playType === 'rqspf' ? oddsGroup.handicap ?? null : undefined,
      is_single_allowed: oddsGroup.is_single_allowed === true,
      is_dan: false,
    });
  }

  return { mapped, unmatched };
}
