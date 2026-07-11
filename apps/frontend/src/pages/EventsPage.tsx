import { useEffect, useState } from 'react';
import { api } from '../core/apiClient';
import type { EventCatalogMatch, EventSummary } from '../core/types';
import { ApiError } from '../core/types';
import PageHeader from '../shared/components/PageHeader';
import DataTable, { type Column } from '../shared/components/DataTable';
import ErrorState from '../shared/components/ErrorState';
import StatusBadge from '../shared/components/StatusBadge';
import LoadingSpinner from '../shared/components/LoadingSpinner';
import Skeleton from '../shared/components/Skeleton';
import EmptyState from '../shared/components/EmptyState';
import MatchDetailDrawer from '../shared/components/MatchDetailDrawer';
import TeamName from '../shared/components/TeamName';
import { statusLabel } from '../shared/constants';

const LEAGUE_COLORS = ['#ef4444', '#f59e0b', '#22c55e', '#3b82f6', '#8b5cf6', '#ec4899', '#06b6d4', '#f97316', '#84cc16', '#14b8a6'];

export default function EventsPage() {
  const [matches, setMatches] = useState<EventCatalogMatch[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedLeague, setSelectedLeague] = useState<string>('__all__');
  const [selectedMatchId, setSelectedMatchId] = useState<number | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    api.events.catalog({ source: 'all', limit: 5000 })
      .then((res) => {
        setMatches(res.matches);
        setLoading(false);
        setSelectedLeague('__all__');
      })
      .catch((e) => {
        setError(e instanceof ApiError ? e.message : '加载失败');
        setLoading(false);
      });
  }, []);

  const selectLeague = (leagueName: string | null) => {
    const key = leagueName || '__all__';
    if (key === selectedLeague) return;
    setSelectedLeague(key);
  };

  const isAll = selectedLeague === '__all__';
  const grouped = new Map<string, EventCatalogMatch[]>();
  matches.forEach((match) => grouped.set(match.league_name, [...(grouped.get(match.league_name) || []), match]));
  const events: EventSummary[] = Array.from(grouped, ([league_name, rows]) => ({
    league_name,
    match_count: rows.length,
    first_match: rows.reduce((first, row) => row.kickoff_time < first ? row.kickoff_time : first, rows[0].kickoff_time),
    last_match: rows.reduce((last, row) => row.kickoff_time > last ? row.kickoff_time : last, rows[0].kickoff_time),
  })).sort((a, b) => b.last_match.localeCompare(a.last_match));
  const leagueMatches = isAll ? matches : matches.filter((match) => match.league_name === selectedLeague);

  if (loading) return (
    <div>
      <PageHeader title="赛事中心" />
      <div style={{ display: 'flex', gap: '16px' }}>
        <div style={{ width: '200px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <Skeleton variant="card" height={56} count={8} />
        </div>
        <div style={{ flex: 1 }}>
          <Skeleton variant="card" height={400} />
        </div>
      </div>
    </div>
  );
  if (error) return (
    <div>
      <PageHeader title="赛事中心" />
      <ErrorState message={error} onRetry={() => window.location.reload()} />
    </div>
  );

  const matchColumns: Column<EventCatalogMatch>[] = [
    {
      key: 'source_match_code',
      title: '编号',
      width: '90px',
      render: (v) => <span className="fqp-mono" style={{ color: 'var(--fqp-accent)', fontWeight: 600 }}>{String(v)}</span>,
    },
    {
      key: 'kickoff_time',
      title: '开赛时间',
      width: '150px',
      render: (v) => <span className="fqp-mono" style={{ fontSize: '12px' }}>{String(v).replace('T', ' ').slice(0, 16)}</span>,
    },
    { key: 'home_team_name', title: '主队', render: (v) => <TeamName name={String(v)} /> },
    {
      key: 'ft_home_goals',
      title: '比分',
      width: '70px',
      render: (_v, row) => {
        if (row.ft_home_goals != null && row.ft_away_goals != null) {
          return <span className="fqp-mono" style={{ fontWeight: 700, color: 'var(--fqp-accent)' }}>{row.ft_home_goals}:{row.ft_away_goals}</span>;
        }
        return <span style={{ color: 'var(--fqp-text-muted)' }}>—</span>;
      },
    },
    { key: 'away_team_name', title: '客队', render: (v) => <TeamName name={String(v)} /> },
    ...(isAll ? [{ key: 'league_name', title: '联赛', width: '120px' as const }] : []),
    {
      key: 'source',
      title: '数据来源',
      width: '100px',
      render: (v) => <StatusBadge status={v === 'official' ? 'ok' : 'info'} label={v === 'official' ? '体彩官方' : '补充赛程'} />,
    },
    {
      key: 'match_status',
      title: '状态',
      width: '80px',
      render: (v) => {
        const s = String(v);
        const map: Record<string, 'ok' | 'warning' | 'error' | 'info' | 'disabled'> = {
          Selling: 'ok', Settled: 'info', Finished: 'info',
        };
        return <StatusBadge status={map[s] || 'disabled'} label={statusLabel(s)} />;
      },
    },
  ];

  const totalMatches = events.reduce((s, e) => s + e.match_count, 0);

  const selectedEvent = isAll ? null : events.find((e) => e.league_name === selectedLeague);

  return (
    <div>
      <PageHeader title="赛事中心" subtitle={`${events.length} 个联赛 · ${totalMatches} 场比赛 · 完整赛季档案`} />

      <div style={{ display: 'flex', gap: '16px', alignItems: 'flex-start' }}>
        {/* ── Left: league nav ── */}
        <div style={{
          width: '200px', minWidth: '200px', flexShrink: 0,
          display: 'flex', flexDirection: 'column', gap: '4px',
        }}>
          {/* "全部赛事" item */}
          <div
            onClick={() => selectLeague(null)}
            style={{
              cursor: 'pointer', padding: '10px 14px', borderRadius: '8px',
              borderLeft: `3px solid ${isAll ? 'var(--fqp-accent)' : 'transparent'}`,
              background: isAll ? 'var(--fqp-hover-bg)' : 'transparent',
              marginBottom: '6px',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontWeight: isAll ? 700 : 500, fontSize: '14px', color: isAll ? 'var(--fqp-text)' : 'var(--fqp-text-muted)' }}>
                全部赛事
              </span>
              <span style={{
                fontSize: '11px', fontWeight: 600,
                color: isAll ? 'var(--fqp-accent)' : 'var(--fqp-text-muted)',
                background: isAll ? 'var(--fqp-accent)20' : 'transparent',
                padding: '2px 8px', borderRadius: '10px',
              }}>
                {totalMatches}
              </span>
            </div>
            <div style={{ fontSize: '10px', color: 'var(--fqp-text-muted)', marginTop: '2px' }}>
              全部联赛
            </div>
          </div>

          {events.map((evt, i) => {
            const isActive = evt.league_name === selectedLeague;
            const color = LEAGUE_COLORS[i % LEAGUE_COLORS.length];
            return (
              <div
                key={evt.league_name}
                onClick={() => selectLeague(evt.league_name)}
                className="fqp-anim-slideLeft"
                style={{
                  cursor: 'pointer',
                  padding: '10px 14px',
                  borderRadius: '8px',
                  borderLeft: `3px solid ${isActive ? color : 'transparent'}`,
                  background: isActive ? 'var(--fqp-hover-bg)' : 'transparent',
                  transition: 'background 0.15s, border-color 0.2s ease',
                  animationDelay: `${i * 30}ms`,
                }}
                onMouseEnter={(e) => {
                  if (!isActive) e.currentTarget.style.background = 'var(--fqp-hover-subtle)';
                }}
                onMouseLeave={(e) => {
                  if (!isActive) e.currentTarget.style.background = 'transparent';
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{
                    fontWeight: isActive ? 700 : 500,
                    fontSize: '14px',
                    color: isActive ? 'var(--fqp-text)' : 'var(--fqp-text-muted)',
                  }}>
                    {evt.league_name}
                  </span>
                  <span style={{
                    fontSize: '11px', fontWeight: 600,
                    color: isActive ? color : 'var(--fqp-text-muted)',
                    background: isActive ? `${color}20` : 'transparent',
                    padding: '2px 8px', borderRadius: '10px',
                  }}>
                    {evt.match_count}
                  </span>
                </div>
                <div style={{ fontSize: '10px', color: 'var(--fqp-text-muted)', marginTop: '2px' }}>
                  {String(evt.first_match).slice(0, 10)} → {String(evt.last_match).slice(0, 10)}
                </div>
              </div>
            );
          })}
        </div>

        {/* ── Right: match data panel ── */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{
            marginBottom: '12px', padding: '12px 16px',
            background: 'var(--fqp-panel-overlay)', borderRadius: '8px',
            display: 'flex', alignItems: 'center', gap: '16px',
          }}>
            <span style={{ fontWeight: 700, fontSize: '16px' }}>
              {isAll ? '全部赛事' : selectedLeague}
            </span>
            <span style={{ color: 'var(--fqp-text-muted)', fontSize: '13px' }}>
              {leagueMatches.length} 场比赛 · 完整赛季档案
            </span>
            {selectedEvent && (
              <span style={{ color: 'var(--fqp-text-muted)', fontSize: '12px' }}>
                {String(selectedEvent.first_match).slice(0, 10)} → {String(selectedEvent.last_match).slice(0, 10)}
              </span>
            )}
          </div>

          {leagueMatches.length > 0 ? (
            <div style={{
              background: 'var(--fqp-panel)', borderRadius: '8px',
              padding: 0, overflow: 'hidden',
            }}>
              <DataTable
                columns={matchColumns}
                rows={leagueMatches}
                emptyText="该赛事暂无比赛"
                onRowClick={(row) => row.source === 'official' && setSelectedMatchId(row.source_row_id)}
                rowKey={(row) => `${row.source}-${row.source_row_id}`}
                selectedRowKey={selectedMatchId}
              />
            </div>
          ) : (
            <EmptyState icon="⚽" title="暂无比赛" description="该赛事下没有找到比赛数据" />
          )}
        </div>
      </div>

      <MatchDetailDrawer
        matchId={selectedMatchId}
        onClose={() => setSelectedMatchId(null)}
      />
    </div>
  );
}
