import TeamName from '../../shared/components/TeamName';
import { compareKickoff, kickoffValue, loadActiveMatches } from './activeMatches';
import { ResourceNotice } from './MatchEvidence';
import { formatTime } from './presentation';
import useReadOnlyResource from './useReadOnlyResource';

export default function MatchOverview() {
  const list = useReadOnlyResource(loadActiveMatches);
  const matches = list.data?.matches ?? [];
  const now = Date.now();
  const awaiting = matches.filter(match => match.match_status === 'awaiting_result' || kickoffValue(match.kickoff_time) <= now);
  const upcoming = matches.filter(match => match.match_status !== 'awaiting_result' && kickoffValue(match.kickoff_time) > now)
    .sort(compareKickoff).slice(0, 5);
  const unknown = matches.filter(match => !Number.isFinite(kickoffValue(match.kickoff_time))).length;
  return <section className="cc-overview cc-panel" aria-label="比赛概览">
    <div className="cc-panel-heading"><span className="cc-eyebrow">MATCH OVERVIEW</span><span>{list.data ? `本次获取 ${matches.length} 场` : '等待数据'}</span></div>
    <h3>比赛概览</h3>
    <p className="cc-muted">官方未结束比赛，每次最多获取 500 场；下方展示已获取范围内即将开球的最多 5 场。</p>
    <ResourceNotice {...list} />
    {list.loading ? <p role="status">加载赛事…</p> : list.data && <>
      {upcoming.length ? <ul className="cc-overview-list">{upcoming.map(match => <li key={match.match_id}>
        <div><span className="cc-match-meta">{match.match_num_str || `#${match.match_id}`} · {match.league_name} · {formatTime(match.kickoff_time)}</span>
          <div className="cc-overview-teams"><TeamName name={match.home_team_name} /><span className="cc-vs">VS</span><TeamName name={match.away_team_name} /></div></div>
        <a href={`#/matches?match_id=${match.match_id}`} aria-label={`查看分析 ${match.match_num_str || `#${match.match_id}`} ${match.home_team_name} VS ${match.away_team_name}`}>查看分析</a>
      </li>)}</ul> : <p className="cc-empty">{matches.length ? '本次获取范围内暂无即将开球的比赛' : '暂无未结束比赛'}</p>}
      {awaiting.length > 0 && <p className="cc-muted">等待赛果 {awaiting.length} 场 · 仅指本次获取记录，具体状态以最近响应为准。</p>}
      {unknown > 0 && <p className="cc-muted">开球时间未明确 {unknown} 场，可进入比赛中心查看。</p>}
    </>}
    <a href="#/matches" className="cc-detail-link">进入比赛中心</a>
    <p className="cc-muted">最近获取时间表示本次响应时间，来源更新时间请在对应证据中核对。</p>
  </section>;
}
