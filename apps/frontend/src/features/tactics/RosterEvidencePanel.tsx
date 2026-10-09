import { useEffect, useState } from 'react';
import { api } from '../../core/apiClient';
import type { MatchDetail, MatchDetailLineup } from '../../core/types';
import { formatTimestamp } from '../../shared/utils';
import useManualEvidence from '../../pages/useManualEvidence';
import ReadEvidenceStatus from '../../pages/ReadEvidenceStatus';
import '../../pages/BusinessEvidence.css';
import './RosterEvidencePanel.css';

function positive(value: unknown): value is number { return Number.isSafeInteger(value) && Number(value) > 0; }
function optionalNumber(value: unknown) { return value == null || (typeof value === 'number' && Number.isFinite(value)); }
function optionalText(value: unknown) { return value == null || typeof value === 'string'; }
export function checkedRoster(data: MatchDetail, matchId: number): MatchDetail {
  if (!data || data.match?.id !== matchId) throw new Error('阵容证据与所选比赛不一致');
  if (!data.teams?.home || !data.teams?.away || !data.lineups || !Array.isArray(data.injuries) || data.injuries.length > 40) throw new Error('阵容证据格式不正确');
  if (typeof data.match.home_team_name !== 'string' || typeof data.match.away_team_name !== 'string' || !optionalText(data.availability_scope) || (data.availability_limit_per_team !== undefined && data.availability_limit_per_team !== 20)) throw new Error('阵容证据范围格式不正确');
  for (const side of ['home', 'away'] as const) {
    if (data.teams[side].id !== null && !positive(data.teams[side].id)) throw new Error('球队标识格式不正确');
    const lineup = data.lineups[side];
    if (lineup === null) continue;
    if (!lineup || (lineup.snapshot_id !== undefined && !positive(lineup.snapshot_id)) || (lineup.match_id !== undefined && lineup.match_id !== matchId) || (lineup.team_id !== undefined && lineup.team_id !== data.teams[side].id)) throw new Error('阵容证据与所选球队不一致');
    if (!Array.isArray(lineup.players) || lineup.players.length > 80 || !optionalText(lineup.formation) || !optionalText(lineup.lineup_type) || !optionalText(lineup.source) || !optionalText(lineup.snapshot_time) || !optionalText(lineup.collected_at) || !optionalNumber(lineup.strength_score)) throw new Error('阵容快照格式不正确');
    const seen = new Set<number>();
    for (const player of lineup.players) {
      if (!player || !positive(player.player_id) || seen.has(player.player_id) || typeof player.is_starting !== 'boolean' || typeof player.is_substitute !== 'boolean' || (player.is_starting && player.is_substitute) || ![player.name_cn, player.name_en, player.position, player.primary_position, player.tactical_role].every(optionalText)) throw new Error('阵容球员格式不正确');
      seen.add(player.player_id);
    }
  }
  const seenInjuries = new Set<string>();
  for (const injury of data.injuries) {
    if (!injury) throw new Error('伤停证据格式不正确');
    const key = `${injury.team_id}:${injury.player_id}`;
    if (!injury || !positive(injury.team_id) || ![data.teams.home.id, data.teams.away.id].includes(injury.team_id) || !['injured','suspended','doubtful'].includes(injury.status) || !optionalNumber(injury.impact_score) || ![injury.player_name_cn,injury.player_name_en,injury.injury_type,injury.body_part,injury.expected_return,injury.position,injury.source,injury.snapshot_time,injury.collected_at].every(optionalText)) throw new Error('伤停证据格式不正确');
    if (data.availability_scope === 'latest_per_player_team' && (!positive(injury.player_id) || seenInjuries.has(key))) throw new Error('伤停球员重复或缺少标识');
    seenInjuries.add(key);
  }
  return data;
}
function score(value: unknown) { return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(2) : '—'; }
function source(value?: string | null) { return value?.trim() || '来源未知'; }
/** Collectors store business-clock snapshots without a zone; preserve that ambiguity. */
export function formatRosterTime(value?: string | null): string {
  if (!value || !/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?$/i.test(value)) return '—';
  if (/(?:Z|[+-]\d{2}:?\d{2})$/i.test(value)) return `${formatTimestamp(value)}（北京时间）`;
  if (formatTimestamp(value.replace(' ', 'T')) === '—') return '—';
  return `${value.replace('T', ' ')}（时区未记录）`;
}
function hasTime(value?: string | null) { return formatRosterTime(value) !== '—'; }
function lineupType(value?: string | null) {
  return value === 'confirmed' ? '来源标记为确认首发' : value === 'predicted' ? '预估名单' : value === 'historical' ? '历史阵容' : `类型未知${value ? `（${value}）` : ''}`;
}
function TeamRoster({ lineup, name, matchId, teamId }: {lineup: MatchDetailLineup | null; name: string; matchId: number; teamId: number | null}) {
  const [selectedId,setSelectedId] = useState<number | null>(null);
  useEffect(() => { if (selectedId !== null && !lineup?.players.some(player => player.player_id === selectedId)) setSelectedId(null); }, [lineup, selectedId]);
  if (!lineup) return <section className="te-team"><h3>{name}</h3><p>尚无阵容快照</p><p>可靠首发证据不足，请等待采集或核验。</p></section>;
  const starters = lineup.players.filter(player => player.is_starting);
  const verifiable = lineup.lineup_type === 'confirmed' && starters.length === 11 && !!lineup.source?.trim() && hasTime(lineup.snapshot_time) && positive(lineup.snapshot_id) && lineup.match_id === matchId && lineup.team_id === teamId;
  const selected = lineup.players.find(player => player.player_id === selectedId);
  return <section className="te-team"><h3>{name}</h3>
    <p className="te-type">{lineupType(lineup.lineup_type)} · {starters.length}/11</p>
    {!verifiable && <p className="te-warning">可靠首发证据不足，请核对来源、快照标识与 11 人名单。</p>}
    <dl className="te-provenance"><dt>来源</dt><dd>{source(lineup.source)}</dd><dt>快照时间</dt><dd>{formatRosterTime(lineup.snapshot_time)}</dd><dt>入库时间（北京时间）</dt><dd>{formatTimestamp(lineup.collected_at)}</dd><dt>阵型</dt><dd>{lineup.formation || '—'}</dd></dl>
    <p>战力 {score(lineup.strength_score)}</p>
    {(['首发','替补','其他'] as const).map(group => {
      const players=lineup.players.filter(player => group === '首发' ? player.is_starting : group === '替补' ? player.is_substitute : !player.is_starting && !player.is_substitute);
      return <div key={group}><h4>{group} · {players.length}</h4>{players.length ? <ul className="te-players">{players.map(player => {
        const playerName=player.name_cn || player.name_en || '姓名未知';
        return <li key={player.player_id}><button type="button" aria-label={`选择球员 ${playerName}`} aria-pressed={selectedId===player.player_id} onClick={()=>setSelectedId(player.player_id)}><span>{playerName}</span><small>{player.position || player.primary_position || '位置未知'}</small></button></li>;
      })}</ul> : <p>暂无记录</p>}</div>;
    })}
    {selected && <section className="te-selection" aria-label="球员详情"><h4>{selected.name_cn || selected.name_en || '姓名未知'}</h4><p>位置：{selected.position || selected.primary_position || '未知'}</p><p>战术角色：{selected.tactical_role || '未知'}</p><p>名单身份：{selected.is_starting ? '首发' : selected.is_substitute ? '替补' : '其他'}</p></section>}
  </section>;
}
function RosterQuery({matchId}:{matchId:number}) {
  const resource=useManualEvidence(async()=>checkedRoster(await api.matches.detail(matchId),matchId));
  const data=resource.data;
  return <section className="te-panel" aria-label="阵容与伤停证据"><h2>阵容与伤停证据</h2>
    <ReadEvidenceStatus resource={resource} label="刷新阵容与伤停证据" note="手动读取；接收时间与源快照时间分别展示"/>
    {data && <><p>以下为数据库中该场最新阵容快照；来源标记未经平台独立认证。当前情报不覆盖冻结的历史特征或赛前预测。</p>
      <div className="te-rosters">{(['home','away'] as const).map(side=><TeamRoster key={`${side}:${data.lineups[side]?.snapshot_id ?? 'unknown'}`} lineup={data.lineups[side]} matchId={matchId} teamId={data.teams[side].id} name={side==='home'?data.match.home_team_name:data.match.away_team_name}/>)}</div>
      <section className="te-injuries"><h3>球队伤停情报</h3>
        <p>{data.availability_scope==='latest_per_player_team' ? '球队最新状态，不代表该场比赛赛前伤停；每位球员仅保留最新记录。' : '旧接口未提供伤停去重范围，不能确认历史记录是否已恢复。'}</p>
        <p>每队最多 {data.availability_limit_per_team ?? '未知'} 条；列表受采集覆盖和读取上限限制。空列表不代表全员健康。</p>
        {data.injuries.length ? <ul className="te-injury-list">{data.injuries.map((injury,index)=><li key={`${injury.team_id}:${injury.snapshot_id ?? index}`}><h4>{injury.player_name_cn || injury.player_name_en || '姓名未知'}</h4><p>{injury.team_id===data.teams.home.id?data.match.home_team_name:data.match.away_team_name} · {({injured:'受伤',suspended:'停赛',doubtful:'出场存疑'})[injury.status] || injury.status} · {injury.position || '位置未知'}</p><p>{injury.injury_type || '伤停原因未提供'}{injury.body_part && `（${injury.body_part}）`} · 预计回归：{injury.expected_return || '未知'}</p><p>影响分 {score(injury.impact_score)}</p><dl className="te-provenance"><dt>来源</dt><dd>{source(injury.source)}</dd><dt>快照时间</dt><dd>{formatRosterTime(injury.snapshot_time)}</dd><dt>入库时间（北京时间）</dt><dd>{formatTimestamp(injury.collected_at)}</dd></dl></li>)}</ul>:<p>尚无可用伤停记录</p>}
      </section><p className="te-warning">未提供球衣号码与真实场上坐标；球员 ID 不作为号码，暂无真实跑动热图。</p>
    </>}
  </section>;
}
export default function RosterEvidencePanel({matchId}:{matchId:number}) {return <RosterQuery key={matchId} matchId={matchId}/>;}
