import { useEffect, useState } from 'react';
import { api } from '../core/apiClient';
import { navigate } from '../core/router';
import type { FeatureSnapshot } from '../core/types';
import { ApiError } from '../core/types';
import PageHeader from '../shared/components/PageHeader';
import FilterBar from '../shared/components/FilterBar';
import DataTable, { type Column } from '../shared/components/DataTable';
import ErrorState from '../shared/components/ErrorState';

interface MatchRow {
  match_id: number;
  home_team: string;
  away_team: string;
  league: string;
  completeness: number | null;
  snapshot_count: number;
}

export default function MatchesPage() {
  const [matches, setMatches] = useState<MatchRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [leagueFilter, setLeagueFilter] = useState('');
  const [searchText, setSearchText] = useState('');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    api
      .features({ limit: 500 })
      .then((res) => {
        if (cancelled) return;
        // Deduplicate by match_id, keep latest snapshot
        const map = new Map<number, MatchRow>();
        for (const s of res.snapshots) {
          if (!map.has(s.match_id)) {
            map.set(s.match_id, {
              match_id: s.match_id,
              home_team: s.home_team_name,
              away_team: s.away_team_name,
              league: s.league_name,
              completeness: s.data_completeness_score,
              snapshot_count: 1,
            });
          } else {
            const existing = map.get(s.match_id)!;
            existing.snapshot_count++;
            if (s.data_completeness_score && (existing.completeness === null || s.data_completeness_score > existing.completeness)) {
              existing.completeness = s.data_completeness_score;
            }
          }
        }
        setMatches(Array.from(map.values()));
        setLoading(false);
      })
      .catch((e) => {
        if (!cancelled) {
          setError(e instanceof ApiError ? e.message : '加载失败');
          setLoading(false);
        }
      });

    return () => { cancelled = true; };
  }, []);

  // Unique leagues for filter
  const leagues = [...new Set(matches.map((m) => m.league))].sort();

  // Filtered rows
  const filtered = matches.filter((m) => {
    if (leagueFilter && m.league !== leagueFilter) return false;
    if (searchText) {
      const q = searchText.toLowerCase();
      if (!m.home_team.toLowerCase().includes(q) && !m.away_team.toLowerCase().includes(q)) {
        return false;
      }
    }
    return true;
  });

  const columns: Column<MatchRow>[] = [
    {
      key: 'match_id',
      title: '编号',
      width: '80px',
      render: (v) => <span className="fqp-mono">{String(v)}</span>,
    },
    { key: 'home_team', title: '主队' },
    { key: 'away_team', title: '客队' },
    { key: 'league', title: '联赛' },
    {
      key: 'completeness',
      title: '数据完整度',
      render: (v) => {
        const val = v as number | null;
        if (val === null) return <span style={{ color: 'var(--fqp-text-muted)' }}>—</span>;
        const pct = Math.round(val * 100);
        const color = pct >= 80 ? 'var(--fqp-success)' : pct >= 50 ? 'var(--fqp-warning)' : 'var(--fqp-red-neon)';
        return <span style={{ color }}>{pct}%</span>;
      },
    },
    {
      key: 'snapshot_count',
      title: '快照数',
      width: '80px',
      render: (v) => <span className="fqp-mono">{String(v)}</span>,
    },
  ];

  if (error) {
    return (
      <div>
        <PageHeader title="比赛中心" />
        <ErrorState message={error} onRetry={() => window.location.reload()} />
      </div>
    );
  }

  return (
    <div>
      <PageHeader title="比赛中心" lastUpdated={new Date().toLocaleString('zh-CN', { hour12: false })} />
      <FilterBar>
        <select
          className="fqp-select"
          value={leagueFilter}
          onChange={(e) => setLeagueFilter(e.target.value)}
          style={{ minWidth: '180px' }}
        >
          <option value="">全部联赛</option>
          {leagues.map((l) => (
            <option key={l} value={l}>{l}</option>
          ))}
        </select>
        <input
          className="fqp-input"
          placeholder="搜索球队..."
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          style={{ minWidth: '200px' }}
        />
      </FilterBar>
      <Card>
        <DataTable
          columns={columns}
          rows={filtered}
          loading={loading}
          emptyText="暂无比赛数据，等待官方赛程采集与特征快照生成"
          onRowClick={(row) => navigate(`/matches/${row.match_id}`)}
          rowKey={(row) => String(row.match_id)}
        />
      </Card>
    </div>
  );
}

// Inline Card wrapper for this page
function Card({ children }: { children: React.ReactNode }) {
  return <div className="fqp-card" style={{ padding: 0, overflow: 'hidden' }}>{children}</div>;
}
