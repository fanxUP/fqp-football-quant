import { getPlayRule, type SportteryPlayType } from '../../core/bettingRules';
import type { BetSlipItem, BettingMatch, BettingOddsOption, CalculateItem } from '../../core/types';
import { optionLabel } from '../../shared/constants';

export const PLAY_TYPES: SportteryPlayType[] = ['spf', 'rqspf', 'bf', 'zjq', 'bqc'];

export const PLAY_LABELS: Record<SportteryPlayType, string> = {
  spf: '胜平负',
  rqspf: '让球胜平负',
  bf: '比分',
  zjq: '总进球',
  bqc: '半全场',
};

export function displayOption(playType: SportteryPlayType, option: BettingOddsOption): string {
  if (playType === 'spf' || playType === 'rqspf') {
    return optionLabel(playType, option.option_code);
  }
  return option.option_name;
}

export function optionAriaLabel(playType: SportteryPlayType, option: BettingOddsOption): string {
  return `${PLAY_LABELS[playType]} ${displayOption(playType, option)} ${option.sp_value.toFixed(2)}`;
}

export function selectionKey(matchId: number, playType: string, optionCode: string): string {
  return `${matchId}:${playType}:${optionCode}`;
}

function canonicalWinDrawLossCode(optionCode: string): string {
  return { h: '3', d: '1', a: '0' }[optionCode.toLowerCase()] ?? optionCode;
}

export function findMatchingOption(
  playType: SportteryPlayType,
  options: BettingOddsOption[],
  recommendationOptionCode: string,
): BettingOddsOption | undefined {
  if (playType !== 'spf' && playType !== 'rqspf') {
    return options.find((option) => option.option_code === recommendationOptionCode);
  }
  const target = canonicalWinDrawLossCode(recommendationOptionCode);
  return options.find((option) => canonicalWinDrawLossCode(option.option_code) === target);
}

export function createSlipItem(
  match: BettingMatch,
  playType: SportteryPlayType,
  option: BettingOddsOption,
): BetSlipItem {
  const market = match.odds[playType];
  return {
    match_id: match.match_id,
    home_team: match.home_team_name,
    away_team: match.away_team_name,
    league_name: match.league_name,
    kickoff_time: match.kickoff_time,
    play_type: playType,
    play_type_label: getPlayRule(playType).label,
    option_code: option.option_code,
    option_name: displayOption(playType, option),
    sp_value: option.sp_value,
    handicap: playType === 'rqspf' ? market.handicap : undefined,
    is_single_allowed: market.is_single_allowed === true,
    is_pass_allowed: market.is_pass_allowed !== false,
    is_dan: false,
    basis: { source: 'manual', summary: `${getPlayRule(playType).label}手工选号` },
  };
}

export function toCalculateItems(items: BetSlipItem[]): CalculateItem[] {
  return items.map((item) => ({
    match_id: item.match_id,
    play_type: item.play_type,
    option_code: item.option_code,
    option_name: item.option_name,
    sp_value: item.sp_value,
    handicap: item.handicap,
    is_dan: item.is_dan,
    is_single_allowed: item.is_single_allowed,
    is_pass_allowed: item.is_pass_allowed,
  }));
}

export function selectedMatchCount(items: BetSlipItem[]): number {
  return new Set(items.map((item) => item.match_id)).size;
}

export function selectedForMatch(items: BetSlipItem[], matchId: number): number {
  return items.filter((item) => item.match_id === matchId).length;
}

export function formatPassTypes(passTypes: string[]): string {
  if (passTypes.length === 0) return '待选择';
  return passTypes
    .map((passType) => passType === 'single' ? '单场' : `${passType.split('x')[0]}关`)
    .join(' + ');
}

export function formatHandicap(value: number | null | undefined): string {
  if (value === undefined || value === null || value === 0) return '-';
  return value > 0 ? `+${value}` : String(value);
}

export function matchTime(match: BettingMatch): string {
  const date = new Date(match.kickoff_time);
  if (Number.isNaN(date.getTime())) return match.kickoff_time;
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false });
}

export function matchDateTime(match: BettingMatch): string {
  const date = new Date(match.kickoff_time);
  if (Number.isNaN(date.getTime())) return match.kickoff_time;
  return `${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')} ${matchTime(match)}`;
}

export function isStartingSoon(match: BettingMatch): boolean {
  const kickoff = new Date(match.kickoff_time).getTime();
  if (Number.isNaN(kickoff)) return false;
  const minutes = (kickoff - Date.now()) / 60_000;
  return minutes >= 0 && minutes <= 120;
}
