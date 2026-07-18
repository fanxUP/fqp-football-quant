import { useCallback, useEffect, useState } from 'react';
import { api } from '../core/apiClient';
import { navigate } from '../core/router';
import type { TodayMatch } from '../core/types';
import { ApiError } from '../core/types';
import PageHeader from '../shared/components/PageHeader';
import FilterBar from '../shared/components/FilterBar';
import ErrorState from '../shared/components/ErrorState';
import Card from '../shared/components/Card';
import Skeleton from '../shared/components/Skeleton';
import StatusBadge from '../shared/components/StatusBadge';
import TeamName from '../shared/components/TeamName';
import useBackgroundRefresh from '../shared/hooks/useBackgroundRefresh';
import { statusLabel } from '../shared/constants';

export default function MatchesPage() {
  const [matches, setMatches] = useState<TodayMatch[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [leagueFilter, setLeagueFilter] = useState('');
  const [lastUpdated, setLastUpdated] = useState('');

  const fetchMatches = useCallback(async (showLoading = true) => {
    if (showLoading) {
      setLoading(true);
      setError(null);
    }
    try {
      const res = await api.matches.active({ limit: 500 });
      setMatches(res.matches);
      setLastUpdated(new Date().toLocaleString('zh-CN', { hour12: false }));
      setError(null);
    } catch (e) {
      if (showLoading) setError(e instanceof ApiError ? e.message : '加载比赛失败');
    } finally {
      if (showLoading) setLoading(false);
    }
  }, []);

  useEffect(() => { void fetchMatches(); }, [fetchMatches]);
  useBackgroundRefresh(() => fetchMatches(false));

  const leagues = [...new Set(matches.map((match) => match.league_name))].sort();
  const visibleMatches = leagueFilter ? matches.filter((match) => match.league_name === leagueFilter) : matches;

  if (error) return <div><PageHeader title="比赛中心" /><ErrorState message={error} onRetry={() => fetchMatches()} /></div>;

  return (
    <div>
      <PageHeader title="比赛中心" subtitle="体彩官方未结束比赛" lastUpdated={lastUpdated} />
      <FilterBar>
        <select className="fqp-select" value={leagueFilter} onChange={(event) => setLeagueFilter(event.target.value)} style={{ minWidth: '160px' }}>
          <option value="">全部联赛</option>
          {leagues.map((league) => <option key={league} value={league}>{league}</option>)}
        </select>
        <span style={{ marginLeft: 'auto', fontSize: '12px', color: 'var(--fqp-text-muted)' }}>不包含已结束比赛；停售比赛仍保留查看</span>
      </FilterBar>

      {loading ? <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}><Skeleton variant="card" height={62} count={8} /></div>
        : visibleMatches.length === 0 ? <Card><div style={{ textAlign: 'center', padding: '40px', color: 'var(--fqp-text-muted)' }}>暂无未结束比赛</div></Card>
        : <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {visibleMatches.map((match, index) => (
            <Card key={match.match_id} style={{ cursor: 'pointer', padding: '10px 16px', animation: `fqpCardEnter 0.4s ease both`, animationDelay: `${index * 40}ms` }} onClick={() => navigate(`/matches/${match.match_id}`)}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
                <span className="fqp-mono" style={{ fontSize: '11px', color: 'var(--fqp-accent)', fontWeight: 600, minWidth: '60px' }}>{match.match_num_str || `#${match.match_id}`}</span>
                <span style={{ fontSize: '11px', color: 'var(--fqp-text-muted)', minWidth: '105px' }}>{String(match.kickoff_time).replace('T', ' ').slice(5, 16)}</span>
                <span style={{ fontSize: '12px', color: 'var(--fqp-text-muted)', minWidth: '70px' }}>{match.league_name}</span>
                <TeamName name={match.home_team_name} style={{ fontWeight: 600, fontSize: '13px' }} />
                <span style={{ color: 'var(--fqp-text-muted)', fontWeight: 700 }}>VS</span>
                <TeamName name={match.away_team_name} style={{ fontWeight: 600, fontSize: '13px' }} />
                <span style={{ marginLeft: 'auto' }}><StatusBadge status={match.match_status === 'Selling' ? 'ok' : 'info'} label={statusLabel(match.match_status)} /></span>
              </div>
            </Card>
          ))}
        </div>}

      {!loading && visibleMatches.length > 0 && <div style={{ marginTop: '12px', fontSize: '12px', color: 'var(--fqp-text-muted)', textAlign: 'center' }}>共 {visibleMatches.length} 场未结束比赛 · {leagues.length} 个联赛</div>}
    </div>
  );
}
