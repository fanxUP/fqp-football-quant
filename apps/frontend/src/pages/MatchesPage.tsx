import { useEffect, useState } from 'react';
import { api } from '../core/apiClient';
import { navigate } from '../core/router';
import type { BettingMatch } from '../core/types';
import { ApiError } from '../core/types';
import PageHeader from '../shared/components/PageHeader';
import FilterBar from '../shared/components/FilterBar';
import ErrorState from '../shared/components/ErrorState';
import Card from '../shared/components/Card';
import LoadingSpinner from '../shared/components/LoadingSpinner';
import Skeleton from '../shared/components/Skeleton';
import { PLAY_TYPE_LABELS } from '../shared/constants';
import TeamName from '../shared/components/TeamName';

type PlayTab = 'spf' | 'rqspf' | 'zjq' | 'bf' | 'bqc';

export default function MatchesPage() {
  const [matches, setMatches] = useState<BettingMatch[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [leagueFilter, setLeagueFilter] = useState('');
  const [activeTab, setActiveTab] = useState<PlayTab>('spf');

  const fetchMatches = (league?: string) => {
    setLoading(true);
    setError(null);
    api.bettingTerminal.matches({ league_name: league || undefined, limit: 100 })
      .then((res) => {
        setMatches(res.matches);
        setLoading(false);
      })
      .catch((e) => {
        setError(e instanceof ApiError ? e.message : '加载失败');
        setLoading(false);
      });
  };

  useEffect(() => { fetchMatches(); }, []);

  const handleLeagueChange = (val: string) => {
    setLeagueFilter(val);
    fetchMatches(val);
  };

  const leagues = [...new Set(matches.map((m) => m.league_name))].sort();
  const playTabs: PlayTab[] = ['spf', 'rqspf', 'zjq', 'bf', 'bqc'];

  if (error) return (
    <div>
      <PageHeader title="开赛盘口" />
      <ErrorState message={error} onRetry={() => fetchMatches(leagueFilter)} />
    </div>
  );

  return (
    <div>
      <PageHeader
        title="开赛盘口"
        subtitle="体彩官方实时可购买比赛"
        lastUpdated={new Date().toLocaleString('zh-CN', { hour12: false })}
      />

      <FilterBar>
        <select
          className="fqp-select"
          value={leagueFilter}
          onChange={(e) => handleLeagueChange(e.target.value)}
          style={{ minWidth: '160px' }}
        >
          <option value="">全部联赛</option>
          {leagues.map((l) => (
            <option key={l} value={l}>{l}</option>
          ))}
        </select>
        {/* Play type tabs */}
        <div style={{ display: 'flex', gap: '4px', marginLeft: 'auto' }}>
          {playTabs.map((pt) => (
            <button
              key={pt}
              className={`fqp-btn${activeTab === pt ? ' fqp-btn-primary' : ''}`}
              style={{ padding: '4px 12px', fontSize: '12px' }}
              onClick={() => setActiveTab(pt)}
            >
              {PLAY_TYPE_LABELS[pt]}
            </button>
          ))}
        </div>
      </FilterBar>

      {loading ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <Skeleton variant="card" height={62} count={8} />
        </div>
      ) : matches.length === 0 ? (
        <Card>
          <div style={{ textAlign: 'center', padding: '40px', color: 'var(--fqp-text-muted)' }}>
            暂无在售比赛
          </div>
        </Card>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {matches.map((m, idx) => {
            const oddsGroup = m.odds?.[activeTab];
            const options = oddsGroup?.options || [];
            const handicap = activeTab === 'rqspf' ? oddsGroup?.handicap : undefined;
            return (
              <Card
                key={`${m.match_id}-${activeTab}`}
                style={{ cursor: 'pointer', padding: '10px 16px', animation: `fqpCardEnter 0.4s ease both`, animationDelay: `${idx * 40}ms` }}
                onClick={() => navigate(`/matches/${m.match_id}`)}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
                  {/* Match identity */}
                  <span className="fqp-mono" style={{ fontSize: '11px', color: 'var(--fqp-accent)', fontWeight: 600, minWidth: '60px' }}>
                    {m.match_num_str || `#${m.match_id}`}
                  </span>
                  <span style={{ fontSize: '11px', color: 'var(--fqp-text-muted)', minWidth: '65px' }}>
                    {String(m.kickoff_time).replace('T', ' ').slice(5, 16)}
                  </span>
                  <span style={{ fontSize: '12px', color: 'var(--fqp-text-muted)', minWidth: '70px' }}>
                    {m.league_name}
                  </span>
                  <TeamName name={m.home_team_name} style={{ fontWeight: 600, fontSize: '13px' }} />
                  <span style={{ color: 'var(--fqp-text-muted)', fontWeight: 700 }}>VS</span>
                  <TeamName name={m.away_team_name} style={{ fontWeight: 600, fontSize: '13px' }} />

                  {/* Handicap badge for RQSPF */}
                  {handicap != null && (
                    <span style={{
                      fontSize: '11px', color: 'var(--fqp-warning)',
                      background: 'rgba(255,193,7,0.1)', padding: '2px 6px', borderRadius: '4px',
                    }}>
                      {handicap > 0 ? `+${handicap}` : handicap}
                    </span>
                  )}

                  {/* Odds buttons */}
                  <div style={{ display: 'flex', gap: '6px', marginLeft: 'auto', flexWrap: 'wrap' }}>
                    {options.length === 0 ? (
                      <span style={{ fontSize: '11px', color: 'var(--fqp-text-muted)' }}>暂无赔率</span>
                    ) : (
                      options.map((opt) => (
                        <span
                          key={opt.option_code}
                          style={{
                            display: 'inline-flex', flexDirection: 'column', alignItems: 'center',
                            padding: '4px 10px', borderRadius: '6px',
                            background: 'var(--fqp-panel-overlay)', border: '1px solid var(--fqp-border)',
                            minWidth: '52px',
                          }}
                        >
                          <span style={{ fontSize: '10px', color: 'var(--fqp-text-muted)' }}>
                            {opt.option_name}
                          </span>
                          <span style={{ fontSize: '13px', fontWeight: 700, color: 'var(--fqp-accent)' }}>
                            {opt.sp_value.toFixed(2)}
                          </span>
                        </span>
                      ))
                    )}
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      {/* Summary footer */}
      {!loading && matches.length > 0 && (
        <div style={{ marginTop: '12px', fontSize: '12px', color: 'var(--fqp-text-muted)', textAlign: 'center' }}>
          共 {matches.length} 场在售比赛 · {leagues.length} 个联赛 · 玩法切换查看不同赔率
        </div>
      )}
    </div>
  );
}
