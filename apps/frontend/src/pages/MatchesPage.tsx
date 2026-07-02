import { useEffect, useState } from 'react';
import { api } from '../core/apiClient';
import { navigate } from '../core/router';
import type { FeatureSnapshot } from '../core/types';
import { ApiError } from '../core/types';
import PageHeader from '../shared/components/PageHeader';
import FilterBar from '../shared/components/FilterBar';
import DataTable, { type Column } from '../shared/components/DataTable';
import ErrorState from '../shared/components/ErrorState';
import ChartCard from '../shared/components/ChartCard';

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

  // ---- League distribution chart ----
  const leagueChartOption = (() => {
    if (matches.length === 0) return null;
    const leagueCount: Record<string, number> = {};
    for (const m of matches) {
      leagueCount[m.league] = (leagueCount[m.league] || 0) + 1;
    }
    const sorted = Object.entries(leagueCount).sort((a, b) => b[1] - a[1]);
    const names = sorted.map(([k]) => k);
    const counts = sorted.map(([, v]) => v);

    // Color palette
    const colors = ['#ef4444', '#f59e0b', '#22c55e', '#3b82f6', '#8b5cf6', '#ec4899', '#06b6d4', '#f97316', '#84cc16', '#14b8a6'];

    return {
      tooltip: {
        trigger: 'axis' as const,
        axisPointer: { type: 'shadow' as const },
      },
      grid: {
        left: '3%',
        right: '8%',
        bottom: '3%',
        containLabel: true,
      },
      xAxis: {
        type: 'value' as const,
        name: '比赛数',
        axisLabel: { fontSize: 10 },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } },
      },
      yAxis: {
        type: 'category' as const,
        data: names,
        axisLabel: { fontSize: 11 },
        inverse: true,
      },
      series: [
        {
          type: 'bar',
          data: counts.map((v, i) => ({
            value: v,
            itemStyle: {
              color: colors[i % colors.length],
              borderRadius: [0, 4, 4, 0],
            },
          })),
          barWidth: '60%',
          label: {
            show: true,
            position: 'right' as const,
            fontSize: 11,
          },
        },
      ],
    };
  })();

  // ---- Completeness histogram ----
  const completenessHistOption = (() => {
    if (matches.length === 0) return null;
    const scores = matches
      .map((m) => m.completeness)
      .filter((s): s is number => s !== null)
      .map((s) => Math.round(s * 100));
    if (scores.length === 0) return null;

    // Bucket into 10 groups
    const buckets: number[] = Array(10).fill(0);
    for (const s of scores) {
      const idx = Math.min(Math.floor(s / 10), 9);
      buckets[idx]++;
    }
    const labels = buckets.map((_, i) => `${i * 10}-${i * 10 + 9}%`);

    return {
      tooltip: {
        trigger: 'axis' as const,
        axisPointer: { type: 'shadow' as const },
      },
      grid: {
        left: '3%',
        right: '4%',
        bottom: '3%',
        top: '8px',
        containLabel: true,
      },
      xAxis: {
        type: 'category' as const,
        data: labels,
        axisLabel: { rotate: 45, fontSize: 10 },
      },
      yAxis: {
        type: 'value' as const,
        name: '比赛数',
        axisLabel: { fontSize: 10 },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } },
      },
      series: [
        {
          type: 'bar',
          data: buckets,
          itemStyle: {
            borderRadius: [4, 4, 0, 0],
            color: '#3b82f6',
          },
          barWidth: '80%',
        },
      ],
    };
  })();

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

      {/* Charts */}
      {!loading && matches.length > 0 && (
        <div className="fqp-grid-2" style={{ marginBottom: '16px' }}>
          {leagueChartOption ? (
            <ChartCard title="联赛分布" option={leagueChartOption} height={Math.max(300, leagues.length * 24)} />
          ) : (
            <div className="fqp-card" style={{ padding: '40px', textAlign: 'center', color: 'var(--fqp-text-muted)' }}>
              暂无联赛数据
            </div>
          )}
          {completenessHistOption ? (
            <ChartCard title="数据完整度分布" option={completenessHistOption} height={300} />
          ) : (
            <div className="fqp-card" style={{ padding: '40px', textAlign: 'center', color: 'var(--fqp-text-muted)' }}>
              暂无完整度数据
            </div>
          )}
        </div>
      )}

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
