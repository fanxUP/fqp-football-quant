import TeamName from '../../shared/components/TeamName';
import { kickoffValue, loadActiveMatches } from './activeMatches';
import { ResourceNotice } from './MatchEvidence';
import { formatTime } from './presentation';
import useReadOnlyResource from './useReadOnlyResource';

const loadUpcoming = () => loadActiveMatches({ limit: 5, upcoming_only: true, sort: 'asc' });

export default function MatchOverview() {
  const list = useReadOnlyResource(loadUpcoming);
  const matches = list.data?.matches ?? [];
  const now = Date.now();
  const started = list.data?.started_total ?? 0;
  const upcoming = matches.filter(match => kickoffValue(match.kickoff_time) > now);
  const unknown = matches.filter(match => !Number.isFinite(kickoffValue(match.kickoff_time))).length;
  return <section className="cc-overview cc-panel" aria-label="比赛概览">
    <div className="cc-panel-heading"><span className="cc-eyebrow">MATCH OVERVIEW</span><span>{list.data ? `本次获取 ${matches.length} 场` : '等待数据'}</span></div>
    <h3>比赛概览</h3>
    <p className="cc-muted">当前赛程按开球时间展示即将开球的最多 5 场；历史档案在比赛中心按日期查询。</p>
    <ResourceNotice {...list} />
    {list.loading ? <p role="status">加载赛事…</p> : list.data && <>
      {upcoming.length ? <ul className="cc-overview-list">{upcoming.map(match => <li key={match.match_id}>
        <div><span className="cc-match-meta">{match.match_num_str || `#${match.match_id}`} · {match.league_name} · {formatTime(match.kickoff_time)}</span>
          <div className="cc-overview-teams"><TeamName name={match.home_team_name} /><span className="cc-vs">VS</span><TeamName name={match.away_team_name} /></div></div>
        <a href={`#/matches?match_id=${match.match_id}`} aria-label={`查看分析 ${match.match_num_str || `#${match.match_id}`} ${match.home_team_name} VS ${match.away_team_name}`}>查看分析</a>
      </li>)}</ul> : <p className="cc-empty">暂无即将开球的比赛</p>}
      {started > 0 && <p className="cc-muted">近48小时内已到开球时间、未确认结束 {started} 场 · 实际状态以来源更新为准。</p>}
      {unknown > 0 && <p className="cc-muted">开球时间未明确 {unknown} 场，可进入比赛中心查看。</p>}
    </>}
    <a href="#/matches" className="cc-detail-link">进入比赛中心</a>
    <p className="cc-muted">最近获取时间表示本次响应时间，来源更新时间请在对应证据中核对。</p>
  </section>;
}
