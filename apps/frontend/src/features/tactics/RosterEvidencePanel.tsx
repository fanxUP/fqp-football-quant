import { lazy, Suspense, useEffect, useState } from 'react';
import { api } from '../../core/apiClient';
import type { MatchDetail, MatchDetailLineup } from '../../core/types';
import { formatTimestamp } from '../../shared/utils';
import useManualEvidence from '../../pages/useManualEvidence';
import ReadEvidenceStatus from '../../pages/ReadEvidenceStatus';
import '../../pages/BusinessEvidence.css';
import './RosterEvidencePanel.css';
import SceneViewport from '../command-center/SceneViewport';
import { schematic } from './schematic';
const TacticsScene = lazy(() => import('./TacticsScene'));
type Side = 'home' | 'away';
type Selection = { side: Side; playerId: number } | null;

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
function TeamRoster({ lineup, name, matchId, teamId, selectedId, onSelect }: {lineup: MatchDetailLineup | null; name: string; matchId: number; teamId: number | null; selectedId: number | null; onSelect: (id: number) => void}) {
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
        return <li key={player.player_id}><button type="button" aria-label={`选择球员 ${playerName}`} aria-pressed={selectedId===player.player_id} onClick={()=>onSelect(player.player_id)}><span>{playerName}</span><small>{player.position || player.primary_position || '位置未知'}</small></button></li>;
      })}</ul> : <p>暂无记录</p>}</div>;
    })}
    {selected && <section className="te-selection" aria-label="球员详情"><h4>{selected.name_cn || selected.name_en || '姓名未知'}</h4><p>位置：{selected.position || selected.primary_position || '未知'}</p><p>战术角色：{selected.tactical_role || '未知'}</p><p>名单身份：{selected.is_starting ? '首发' : selected.is_substitute ? '替补' : '其他'}</p></section>}
  </section>;
}
function RosterQuery({matchId}:{matchId:number}) {
  const resource=useManualEvidence(async()=>checkedRoster(await api.matches.detail(matchId),matchId));
  const data=resource.data;
  const [viewSide,setViewSide]=useState<Side>('home');
  const [selection,setSelection]=useState<Selection>(null);
  const selected=selection && data?.lineups[selection.side]?.players.some(p=>p.player_id===selection.playerId) ? selection : null;
  useEffect(()=>{setSelection(previous => previous && data?.lineups[previous.side]?.players.some(p=>p.player_id===previous.playerId) ? previous : null);},[data]);
  const choose=(side:Side,id:number)=>{setViewSide(side);setSelection({side,playerId:id});};
  const current=data?.lineups[viewSide] ?? null;
  const layout=data ? schematic(current,matchId,data.teams[viewSide].id) : null;
  const teamName=data ? viewSide==='home'?data.match.home_team_name:data.match.away_team_name : '';
  const selectedPlayer=selected ? data?.lineups[selected.side]?.players.find(p=>p.player_id===selected.playerId) : null;
  const sceneFallback=<p>使用下方二维球员名单选择与查看详情。</p>;
  return <section className="te-panel" aria-label="阵容与伤停证据"><h2>阵容与伤停证据</h2>
    <ReadEvidenceStatus resource={resource} label="刷新阵容与伤停证据" note="手动读取；接收时间与源快照时间分别展示"/>
    {data && <><p>以下为数据库中该场最新阵容快照；来源标记未经平台独立认证。当前情报不覆盖冻结的历史特征或赛前预测。</p>
      <section className="te-schematic" aria-label="战术阵型示意"><h3>战术阵型示意</h3>
        <p>按位置类别分区，组内顺序仅用于稳定导航；不是实际左右站位、比赛坐标或阵型还原。</p>
        <div className="te-scene-controls" aria-label="示意球队选择">{(['home','away'] as const).map(side=><button type="button" key={side} aria-pressed={viewSide===side} onClick={()=>{setViewSide(side);setSelection(null);}}>{side==='home'?'主队示意':'客队示意'}</button>)}</div>
        <p>{teamName} · {lineupType(current?.lineup_type)} · 来源：{source(current?.source)} · 快照：{formatRosterTime(current?.snapshot_time)}</p>
        {current && current.lineup_type!=='confirmed' && <p className="te-warning">{current.lineup_type==='predicted'?'预估名单示意，不代表已确认首发。':current.lineup_type==='historical'?'历史名单示意，不代表本场已确认首发。':'名单类型未知。'}</p>}
        <p>来源报告阵型：{current?.formation || '—'}；示意仅按位置类别分区，不据此推断精确站位。</p>
        {layout && !layout.reason && <p>示意分区：门将 {layout.nodes.filter(n=>n.band==='GK').length} · 后卫 {layout.nodes.filter(n=>n.band==='DF').length} · 中场 {layout.nodes.filter(n=>n.band==='MF').length} · 前锋 {layout.nodes.filter(n=>n.band==='FW').length}；选中节点增加外圈。</p>}
        {layout?.reason ? <p role="status" className="te-warning">{layout.reason}</p> : layout && <SceneViewport subject="球员名单" fallback={sceneFallback}>{(active,onFailure)=><Suspense fallback={<p role="status">正在加载战术示意；二维名单可继续使用。</p>}><TacticsScene nodes={layout.nodes} selectedId={selected?.side===viewSide?selected.playerId:null} onSelect={id=>{if(layout.nodes.some(node=>node.player.player_id===id))choose(viewSide,id);}} active={active} onFailure={onFailure}/></Suspense>}</SceneViewport>}
        <p role="status">{selected ? `已选择${selected.side==='home'?'主队':'客队'}球员：${selectedPlayer?.name_cn || selectedPlayer?.name_en || '姓名未知'}` : '尚未选择球员'}</p>
        {selectedPlayer && <dl className="te-provenance" aria-label="场景球员摘要"><dt>所选位置</dt><dd>{selectedPlayer.position || selectedPlayer.primary_position || '未知'}</dd><dt>所选角色</dt><dd>{selectedPlayer.tactical_role || '未知'}</dd><dt>名单身份</dt><dd>{selectedPlayer.is_starting?'首发':selectedPlayer.is_substitute?'替补（仅二维名单）':'其他（仅二维名单）'}</dd></dl>}
      </section>
      <div className="te-rosters">{(['home','away'] as const).map(side=><TeamRoster key={side} lineup={data.lineups[side]} matchId={matchId} teamId={data.teams[side].id} name={side==='home'?data.match.home_team_name:data.match.away_team_name} selectedId={selected?.side===side?selected.playerId:null} onSelect={id=>choose(side,id)}/>)}</div>
      <section className="te-injuries"><h3>球队伤停情报</h3>
        <p>{data.availability_scope==='latest_per_player_team' ? '球队最新状态，不代表该场比赛赛前伤停；每位球员仅保留最新记录。' : '旧接口未提供伤停去重范围，不能确认历史记录是否已恢复。'}</p>
        <p>每队最多 {data.availability_limit_per_team ?? '未知'} 条；列表受采集覆盖和读取上限限制。空列表不代表全员健康。</p>
        {data.injuries.length ? <ul className="te-injury-list">{data.injuries.map((injury,index)=><li key={`${injury.team_id}:${injury.snapshot_id ?? index}`}><h4>{injury.player_name_cn || injury.player_name_en || '姓名未知'}</h4><p>{injury.team_id===data.teams.home.id?data.match.home_team_name:data.match.away_team_name} · {({injured:'受伤',suspended:'停赛',doubtful:'出场存疑'})[injury.status] || injury.status} · {injury.position || '位置未知'}</p><p>{injury.injury_type || '伤停原因未提供'}{injury.body_part && `（${injury.body_part}）`} · 预计回归：{injury.expected_return || '未知'}</p><p>影响分 {score(injury.impact_score)}</p><dl className="te-provenance"><dt>来源</dt><dd>{source(injury.source)}</dd><dt>快照时间</dt><dd>{formatRosterTime(injury.snapshot_time)}</dd><dt>入库时间（北京时间）</dt><dd>{formatTimestamp(injury.collected_at)}</dd></dl></li>)}</ul>:<p>尚无可用伤停记录</p>}
      </section><p className="te-warning">未提供球衣号码与真实场上坐标；球员 ID 不作为号码，暂无真实跑动热图。</p>
    </>}
  </section>;
}
export default function RosterEvidencePanel({matchId}:{matchId:number}) {return <RosterQuery key={matchId} matchId={matchId}/>;}
