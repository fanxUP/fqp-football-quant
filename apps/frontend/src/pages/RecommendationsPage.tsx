import { useEffect, useState } from 'react';
import { api } from '../core/apiClient';
import { navigate } from '../core/router';
import type { SimulationTicket, LiveRecommendation, SportterySalesWindow } from '../core/types';
import { ApiError } from '../core/types';
import PageHeader from '../shared/components/PageHeader';
import FilterBar from '../shared/components/FilterBar';
import DataTable, { type Column } from '../shared/components/DataTable';
import ErrorState from '../shared/components/ErrorState';
import Card from '../shared/components/Card';
import ChartCard from '../shared/components/ChartCard';
import StatusBadge from '../shared/components/StatusBadge';
import TeamLogo from '../shared/components/TeamLogo';
import TeamName from '../shared/components/TeamName';
import { normalizeWinDrawLossLabel, statusLabel, riskLabel } from '../shared/constants';

export interface RecommendationMatchSelection {
  matchId: number;
  matchNum: string;
  homeTeam: string;
  awayTeam: string;
  league: string;
  kickoffTime: string | null;
  matchStatus: string;
  playType: string;
  playTypeName: string;
  scoreText: string | null;
  options: LiveRecommendation[];
}

export interface RecommendationInsightItem {
  matchId: number;
  matchNum: string;
  homeTeam: string;
  awayTeam: string;
  league: string;
  kickoffTime: string | null;
  matchStatus: string;
  bestOptionName: string;
  bestPlayTypeName: string;
  bestEv: number;
  bestEdge: number;
  bestConfidence: number;
  directionCount: number;
  options: LiveRecommendation[];
}

export interface RecommendationInsightSummary {
  strongSignals: RecommendationInsightItem[];
  conflictSignals: RecommendationInsightItem[];
}

type RecommendationOptionTone = 'home' | 'away' | 'draw';
type RecommendationOptionOutcome = 'win' | 'lose' | null;

interface RecommendationsPageProps {
  embedded?: boolean;
  onMatchSelect?: (selection: RecommendationMatchSelection) => void;
}

function RecommendationTeamStack({ homeTeam, awayTeam }: { homeTeam: string; awayTeam: string }) {
  return (
    <div className="recommendation-team-stack" aria-label={`${homeTeam} 对阵 ${awayTeam}`}>
      <div className="recommendation-team-row">
        <TeamLogo nameCn={homeTeam} size={24} showFallbackInitials={false} />
        <span>{homeTeam}</span>
      </div>
      <div className="recommendation-team-row away">
        <TeamLogo nameCn={awayTeam} size={24} showFallbackInitials={false} />
        <span>{awayTeam}</span>
      </div>
    </div>
  );
}

const DOW_MAP: Record<string, string> = { '1': '周一', '2': '周二', '3': '周三', '4': '周四', '5': '周五', '6': '周六', '7': '周日' };

function fmtMatchNum(code: string | null) {
  if (!code) return '—';
  const dow = DOW_MAP[code[0]] || code[0];
  return `${dow}${code.slice(1).padStart(3, '0')}`;
}

function recommendationDirection(option: LiveRecommendation): 'home' | 'draw' | 'away' | 'other' {
  if (option.option_code === '3' || option.option_name.includes('主胜') || option.option_name.includes('让胜')) return 'home';
  if (option.option_code === '1' || option.option_name.includes('平')) return 'draw';
  if (option.option_code === '0' || option.option_name.includes('客胜') || option.option_name.includes('主负') || option.option_name.includes('让负')) return 'away';
  return 'other';
}

function recommendationOptionTone(option: LiveRecommendation): RecommendationOptionTone {
  const direction = recommendationDirection(option);
  if (direction === 'home') return 'home';
  if (direction === 'away') return 'away';
  return 'draw';
}

export function formatRecommendationOptionDisplay(
  option: Pick<LiveRecommendation, 'option_name' | 'fair_odds'>,
  outcome: RecommendationOptionOutcome,
) {
  const base = `${normalizeWinDrawLossLabel(option.option_name)}@${option.fair_odds}`;
  if (outcome === 'win') return `${base}/胜利`;
  if (outcome === 'lose') return `${base}/失败`;
  return base;
}

export function buildRecommendationInsightSummary(recommendations: LiveRecommendation[]): RecommendationInsightSummary {
  const groups = new Map<number, LiveRecommendation[]>();
  for (const rec of recommendations) {
    if (!groups.has(rec.match_id)) groups.set(rec.match_id, []);
    groups.get(rec.match_id)!.push(rec);
  }

  const items = [...groups.values()].map((options) => {
    const sortedOptions = [...options].sort((a, b) => b.ev - a.ev);
    const best = sortedOptions[0];
    const directions = new Set(
      sortedOptions
        .map(recommendationDirection)
        .filter((direction) => direction !== 'other'),
    );

    return {
      matchId: best.match_id,
      matchNum: fmtMatchNum(best.match_num_str),
      homeTeam: best.home_team,
      awayTeam: best.away_team,
      league: best.league,
      kickoffTime: best.kickoff_time,
      matchStatus: best.match_status,
      bestOptionName: normalizeWinDrawLossLabel(best.option_name),
      bestPlayTypeName: best.play_type_name,
      bestEv: best.ev,
      bestEdge: best.edge,
      bestConfidence: best.confidence,
      directionCount: directions.size,
      options: sortedOptions,
    };
  });

  const byBestSignal = (a: RecommendationInsightItem, b: RecommendationInsightItem) =>
    b.bestEv - a.bestEv || b.bestConfidence - a.bestConfidence || b.bestEdge - a.bestEdge;

  return {
    strongSignals: items
      .filter((item) => item.bestEv >= 0.05 && item.bestEdge >= 0.05 && item.bestConfidence >= 0.55)
      .sort(byBestSignal)
      .slice(0, 4),
    conflictSignals: items
      .filter((item) => item.directionCount > 1)
      .sort(byBestSignal)
      .slice(0, 4),
  };
}

export default function RecommendationsPage({ embedded = false, onMatchSelect }: RecommendationsPageProps) {
  const [tickets, setTickets] = useState<SimulationTicket[]>([]);
  const [liveRecs, setLiveRecs] = useState<LiveRecommendation[]>([]);
  const [salesWindow, setSalesWindow] = useState<SportterySalesWindow | null>(null);
  const [baselineOnly, setBaselineOnly] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState('');
  const [activePlayTypeTab, setActivePlayTypeTab] = useState('spf_rqspf');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    Promise.all([
      api.tickets({ limit: 100 }),
      api.liveRecommendations({ limit: 500, min_ev: 0.01 }),
    ])
      .then(async ([ticketRes, recRes]) => {
        if (!cancelled) {
          let recommendations = recRes.recommendations || [];
          let baseline = false;
          setSalesWindow(recRes.sales_window ?? null);
          if (recommendations.length === 0 && recRes.sales_window?.is_open !== false) {
            const baselineRes = await api.liveRecommendations({ limit: 500, min_ev: -1, min_confidence: 0 });
            recommendations = baselineRes.recommendations || [];
            baseline = recommendations.length > 0;
          }
          setTickets(ticketRes.tickets);
          // 休市响应为空时保留上一批推荐，避免休市后页面闪空；推荐仍会显示休市锁定提示。
          if (recommendations.length > 0 || recRes.sales_window?.is_open !== false) {
            setLiveRecs(recommendations);
          }
          setBaselineOnly(baseline);
          setLoading(false);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setError(e instanceof ApiError ? e.message : '加载失败');
          setLoading(false);
        }
      });

    return () => { cancelled = true; };
  }, []);

  const filtered = statusFilter
    ? tickets.filter((t) => t.status === statusFilter)
    : tickets;

  // ---- Play type tabs for live recommendations ----
  const PLAY_TYPE_TABS = [
    { key: 'spf_rqspf', label: '胜平负/让球',        playTypes: ['spf', 'rqspf'] },
    { key: 'bf',        label: '比分',               playTypes: ['bf'] },
    { key: 'zjq',       label: '总进球数',            playTypes: ['zjq'] },
    { key: 'bqc',       label: '半全场',              playTypes: ['bqc'] },
  ];
  const filteredLiveRecs = !activePlayTypeTab
    ? liveRecs
    : liveRecs.filter((r) => {
        const tab = PLAY_TYPE_TABS.find((t) => t.key === activePlayTypeTab);
        return tab ? tab.playTypes.includes(r.play_type) : true;
      });

  // ---- Group all play type options by match+playtype (side-by-side display) ----
  interface GroupedRecRow {
    type: 'grouped';
    key: string;
    home_team: string;
    away_team: string;
    league: string;
    play_type: string;
    play_type_name: string;
    kickoff_time: string | null;
    match_status: string;
    match_num_str: string | null;
    ht_home_goals: number | null;
    ht_away_goals: number | null;
    ft_home_goals: number | null;
    ft_away_goals: number | null;
    et_home_goals: number | null;
    et_away_goals: number | null;
    pk_home_goals: number | null;
    pk_away_goals: number | null;
    spf_result: string | null;
    rqspf_result: string | null;
    total_goals_result: string | null;
    score_result: string | null;
    half_full_result: string | null;
    options: LiveRecommendation[];
  }
  interface DateIndexRow {
    type: 'date_index';
    key: string;
    label: string;
  }
  type DisplayRow = GroupedRecRow | DateIndexRow;

  const DOW_NAMES = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
  const COMPLETED_STATUSES = new Set(['Settled', 'Finished']);

  const groupedRows: DisplayRow[] = (() => {
    const groups = new Map<string, LiveRecommendation[]>();
    for (const rec of filteredLiveRecs) {
      const k = `${rec.match_id}:${rec.play_type}`;
      if (!groups.has(k)) groups.set(k, []);
      groups.get(k)!.push(rec);
    }
    const used = new Set<string>();
    const allRows: GroupedRecRow[] = [];
    for (const rec of filteredLiveRecs) {
      const k = `${rec.match_id}:${rec.play_type}`;
      if (!used.has(k)) {
        used.add(k);
        const g = groups.get(k)!;
        g.sort((a, b) => b.ev - a.ev);
        allRows.push({ type: 'grouped', key: k, home_team: g[0].home_team, away_team: g[0].away_team, league: g[0].league, play_type: g[0].play_type, play_type_name: g[0].play_type_name, kickoff_time: g[0].kickoff_time, match_status: g[0].match_status, match_num_str: g[0].match_num_str, ht_home_goals: g[0].ht_home_goals, ht_away_goals: g[0].ht_away_goals, ft_home_goals: g[0].ft_home_goals, ft_away_goals: g[0].ft_away_goals, et_home_goals: g[0].et_home_goals, et_away_goals: g[0].et_away_goals, pk_home_goals: g[0].pk_home_goals, pk_away_goals: g[0].pk_away_goals, spf_result: g[0].spf_result, rqspf_result: g[0].rqspf_result, total_goals_result: g[0].total_goals_result, score_result: g[0].score_result, half_full_result: g[0].half_full_result, options: g });
      }
    }

    // Separate upcoming vs completed
    const upcoming: GroupedRecRow[] = [];
    const completed: GroupedRecRow[] = [];
    for (const row of allRows) {
      if (COMPLETED_STATUSES.has(row.match_status)) {
        completed.push(row);
      } else {
        upcoming.push(row);
      }
    }

    // Completed: group by kickoff date
    const dateGroups = new Map<string, GroupedRecRow[]>();
    for (const row of completed) {
      const date = row.kickoff_time ? row.kickoff_time.slice(0, 10) : 'unknown';
      if (!dateGroups.has(date)) dateGroups.set(date, []);
      dateGroups.get(date)!.push(row);
    }
    // Sort dates descending (most recent first)
    const sortedDates = [...dateGroups.keys()].sort((a, b) => b.localeCompare(a));

    // Build result: upcoming first, then completed by date index
    const result: DisplayRow[] = [...upcoming];

    for (const date of sortedDates) {
      const d = new Date(date + 'T00:00:00');
      const label = `${d.getMonth() + 1}月${d.getDate()}日（${DOW_NAMES[d.getDay()]}）`;
      result.push({ type: 'date_index', key: `date_${date}`, label });
      result.push(...dateGroups.get(date)!);
    }

    return result;
  })();

  // Map play_type to result field and check correctness
  const RESULT_KEY: Record<string, keyof GroupedRecRow> = {
    spf: 'spf_result',
    rqspf: 'rqspf_result',
    bf: 'score_result',
    zjq: 'total_goals_result',
    bqc: 'half_full_result',
  };

  const isOptionCorrect = (row: GroupedRecRow, optionCode: string): boolean | null => {
    const resultKey = RESULT_KEY[row.play_type];
    if (!resultKey) return null;
    const actual = row[resultKey] as string | null;
    if (actual == null) return null; // no result yet
    return actual === optionCode;
  };

  const renderOptionOutcome = (row: GroupedRecRow, option: LiveRecommendation): RecommendationOptionOutcome => {
    const correct = isOptionCorrect(row, option.option_code);
    if (correct === true) return 'win';
    if (correct === false) return 'lose';
    return null;
  };

  const selectGroupedRow = (row: GroupedRecRow) => {
    if (!onMatchSelect) return;
    const fullTimeScore =
      row.ft_home_goals != null && row.ft_away_goals != null
        ? `${row.ft_home_goals}:${row.ft_away_goals}`
        : null;

    onMatchSelect({
      matchId: row.options[0].match_id,
      matchNum: fmtMatchNum(row.match_num_str),
      homeTeam: row.home_team,
      awayTeam: row.away_team,
      league: row.league,
      kickoffTime: row.kickoff_time,
      matchStatus: row.match_status,
      playType: row.play_type,
      playTypeName: row.play_type_name,
      scoreText: fullTimeScore,
      options: row.options,
    });
  };

  const selectInsightItem = (item: RecommendationInsightItem) => {
    if (!onMatchSelect || item.options.length === 0) return;
    const best = item.options[0];
    const fullTimeScore =
      best.ft_home_goals != null && best.ft_away_goals != null
        ? `${best.ft_home_goals}:${best.ft_away_goals}`
        : null;

    onMatchSelect({
      matchId: item.matchId,
      matchNum: item.matchNum,
      homeTeam: item.homeTeam,
      awayTeam: item.awayTeam,
      league: item.league,
      kickoffTime: item.kickoffTime,
      matchStatus: item.matchStatus,
      playType: best.play_type,
      playTypeName: best.play_type_name,
      scoreText: fullTimeScore,
      options: item.options,
    });
  };

  const insightSummary = buildRecommendationInsightSummary(filteredLiveRecs);

  const riskBadge = (level: string) => {
    const map: Record<string, 'ok' | 'warning' | 'error'> = {
      low: 'ok',
      medium: 'warning',
      high: 'error',
    };
    return <StatusBadge status={map[level] || 'info'} label={riskLabel(level)} />;
  };

  const statusBadge = (s: string): 'ok' | 'warning' | 'error' | 'info' | 'disabled' => {
    const map: Record<string, 'ok' | 'warning' | 'error' | 'info' | 'disabled'> = {
      generated: 'info',
      activated: 'warning',
      settled: 'ok',
      invalidated: 'disabled',
    };
    return map[s] || 'disabled';
  };

  const columns: Column<SimulationTicket>[] = [
    {
      key: 'id',
      title: '票单ID',
      width: '80px',
      render: (v) => <span className="fqp-mono">#{String(v)}</span>,
    },
    { key: 'strategy_pool', title: '策略池' },
    { key: 'pass_type', title: '过关方式' },
    {
      key: 'suggested_stake',
      title: '建议金额',
      render: (v) => <span className="fqp-mono">¥{Number(v).toFixed(0)}</span>,
    },
    {
      key: 'estimated_return',
      title: '预估回报',
      render: (v) => {
        const val = v as number | null;
        return val !== null ? <span className="fqp-mono">¥{val.toFixed(0)}</span> : '—';
      },
    },
    {
      key: 'expected_value',
      title: 'EV',
      render: (v) => {
        const val = v as number | null;
        if (val === null) return '—';
        const color = val > 0 ? 'var(--fqp-success)' : 'var(--fqp-red-neon)';
        return <span style={{ color }}>{val >= 0 ? '+' : ''}{val.toFixed(4)}</span>;
      },
    },
    {
      key: 'risk_level',
      title: '风险',
      render: (v) => riskBadge(String(v)),
    },
    {
      key: 'status',
      title: '状态',
      render: (v) => <StatusBadge status={statusBadge(String(v))} label={statusLabel(String(v))} />,
    },
    {
      key: 'created_at',
      title: '创建时间',
      render: (v) => String(v).replace('T', ' ').slice(0, 19),
    },
    {
      key: 'item_count',
      title: '场次',
      width: '60px',
      render: (v) => <span className="fqp-mono">{String(v)}</span>,
    },
  ];

  // ---- Charts ----

  const riskDonutOption = (() => {
    if (tickets.length === 0) return null;
    const riskCount: Record<string, number> = {};
    for (const t of tickets) {
      riskCount[t.risk_level] = (riskCount[t.risk_level] || 0) + 1;
    }
    const colorMap: Record<string, string> = { low: '#22c55e', medium: '#f59e0b', high: '#ef4444' };
    const labelMap: Record<string, string> = { low: '低风险', medium: '中风险', high: '高风险' };

    return {
      tooltip: {
        trigger: 'item' as const,
        formatter: '{b}: {c} 张 ({d}%)',
      },
      series: [
        {
          type: 'pie',
          radius: ['50%', '75%'],
          center: ['50%', '50%'],
          avoidLabelOverlap: true,
          label: {
            show: true,
            position: 'outside',
            formatter: '{b}\n{c} 张',
            fontSize: 12,
            lineHeight: 17,
            color: '#F4F5F7',
            fontWeight: 600,
          },
          labelLine: {
            length: 20,
            length2: 32,
            lineStyle: { color: 'rgba(255,255,255,0.12)' },
          },
          data: Object.entries(riskCount).map(([level, count]) => ({
            value: count,
            name: labelMap[level] || level,
            itemStyle: { color: colorMap[level] || '#6b7280' },
          })),
        },
      ],
    };
  })();

  const strategyBarOption = (() => {
    if (tickets.length === 0) return null;
    // Aggregate by strategy_pool
    const pools: Record<string, { count: number; totalEv: number }> = {};
    for (const t of tickets) {
      const p = t.strategy_pool || '未分类';
      if (!pools[p]) pools[p] = { count: 0, totalEv: 0 };
      pools[p].count++;
      pools[p].totalEv += (t.expected_value ?? 0);
    }
    const entries = Object.entries(pools).sort((a, b) => b[1].count - a[1].count);
    const names = entries.map(([k]) => k);
    const counts = entries.map(([, v]) => v.count);
    const avgEvs = entries.map(([, v]) => v.count > 0 ? +(v.totalEv / v.count).toFixed(4) : 0);

    return {
      tooltip: {
        trigger: 'axis' as const,
        axisPointer: { type: 'shadow' as const },
      },
      legend: {
        data: ['票单数', '平均EV'],
        top: 0,
      },
      grid: {
        left: '3%',
        right: '4%',
        bottom: '10%',
        top: '40px',
        containLabel: true,
      },
      xAxis: {
        type: 'category' as const,
        data: names,
        axisLabel: { rotate: 30, fontSize: 12 },
      },
      yAxis: [
        {
          type: 'value' as const,
          name: '数量',
          nameTextStyle: { fontSize: 11 },
          axisLabel: { fontSize: 11 },
          splitLine: { lineStyle: { color: 'var(--fqp-border-subtle)' } },
        },
        {
          type: 'value' as const,
          name: 'EV',
          nameTextStyle: { fontSize: 11 },
          axisLabel: { fontSize: 11 },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: '票单数',
          type: 'bar',
          data: counts,
          itemStyle: { color: '#3b82f6', borderRadius: [4, 4, 0, 0] },
          barWidth: '50%',
        },
        {
          name: '平均EV',
          type: 'line',
          yAxisIndex: 1,
          data: avgEvs,
          lineStyle: { color: '#f59e0b', width: 2 },
          itemStyle: { color: '#f59e0b' },
          symbol: 'circle',
          symbolSize: 8,
        },
      ],
    };
  })();

  if (error) {
    return (
      <div>
        {!embedded && <PageHeader title="推荐票单" />}
        <ErrorState message={error} onRetry={() => window.location.reload()} />
      </div>
    );
  }

  return (
    <div>
      {!embedded && (
        <PageHeader
          title="推荐票单"
          lastUpdated={new Date().toLocaleString('zh-CN', { hour12: false })}
        />
      )}

      {/* Live recommendations panel */}
      {!loading && salesWindow?.is_open === false && (
        <Card style={{ marginBottom: 16, borderColor: 'rgba(245,165,36,0.45)' }}>
          <div style={{ color: 'var(--fqp-warning)', fontSize: 13 }}>
            {salesWindow.message}
          </div>
        </Card>
      )}
      {baselineOnly && (
        <Card style={{ marginBottom: 16, borderColor: 'rgba(245,165,36,0.45)' }}>
          <div style={{ color: 'var(--fqp-warning)', fontSize: 13 }}>
            当前无正 EV 投注推荐，以下比赛仅供模型分析，不代表投注建议。
          </div>
        </Card>
      )}
      {!loading && liveRecs.length > 0 && (
        <Card style={{ marginBottom: 20, borderColor: 'rgba(34,197,94,0.30)', animation: 'fqpSlideUpBounce 0.4s ease both' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
            <span style={{ fontSize: 18, animation: 'fqpNotificationDot 2s infinite', display: 'inline-block' }}>🎯</span>
            <span style={{ fontWeight: 700, fontSize: 15, color: 'var(--fqp-text)' }}>
              实时推荐（基于最新模型预测）
            </span>
            <span style={{ fontSize: 11, color: 'var(--fqp-text-muted)', marginLeft: 4 }}>
              {baselineOnly ? '模型基线分析' : 'EV > 0.01'} · 共 {liveRecs.length} 条
            </span>
          </div>

          {(insightSummary.strongSignals.length > 0 || insightSummary.conflictSignals.length > 0) && (
            <div className="recommendation-insights">
              <section className="recommendation-insight-column" aria-label="强信号队列">
                <div className="recommendation-insight-head">
                  <strong>强信号</strong>
                  <span>{insightSummary.strongSignals.length} 场</span>
                </div>
                <div className="recommendation-insight-list">
                  {insightSummary.strongSignals.map((item) => (
                    <button
                      key={`strong-${item.matchId}`}
                      type="button"
                      className="recommendation-insight-item"
                      onClick={() => selectInsightItem(item)}
                    >
                      <span className="recommendation-insight-match" style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                        <span>{item.matchNum}</span><TeamName name={item.homeTeam} size={16} /><span>vs</span><TeamName name={item.awayTeam} size={16} />
                      </span>
                      <span className="recommendation-insight-meta">
                        {item.bestPlayTypeName} · {item.bestOptionName}
                      </span>
                      <span className="recommendation-insight-stats">
                        <b>EV {item.bestEv >= 0 ? '+' : ''}{item.bestEv.toFixed(3)}</b>
                        <i>置信 {(item.bestConfidence * 100).toFixed(0)}%</i>
                      </span>
                    </button>
                  ))}
                </div>
              </section>

              <section className="recommendation-insight-column" aria-label="冲突场次">
                <div className="recommendation-insight-head">
                  <strong>冲突场次</strong>
                  <span>{insightSummary.conflictSignals.length} 场</span>
                </div>
                <div className="recommendation-insight-list">
                  {insightSummary.conflictSignals.map((item) => (
                    <button
                      key={`conflict-${item.matchId}`}
                      type="button"
                      className="recommendation-insight-item warning"
                      onClick={() => selectInsightItem(item)}
                    >
                      <span className="recommendation-insight-match" style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                        <span>{item.matchNum}</span><TeamName name={item.homeTeam} size={16} /><span>vs</span><TeamName name={item.awayTeam} size={16} />
                      </span>
                      <span className="recommendation-insight-meta">
                        {item.directionCount} 个方向 · {item.options.length} 条信号
                      </span>
                      <span className="recommendation-insight-stats">
                        <b>最高 EV {item.bestEv >= 0 ? '+' : ''}{item.bestEv.toFixed(3)}</b>
                        <i>Edge {(item.bestEdge * 100).toFixed(1)}%</i>
                      </span>
                    </button>
                  ))}
                </div>
              </section>
            </div>
          )}

          {/* 玩法导航标签 */}
          <div style={{ display: 'flex', gap: 6, marginBottom: 12, flexWrap: 'wrap' }}>
            {PLAY_TYPE_TABS.map((tab) => {
              const count = liveRecs.filter((r) => tab.playTypes.includes(r.play_type)).length;
              return (
                <button
                  key={tab.key}
                  className={activePlayTypeTab === tab.key ? 'fqp-btn fqp-btn-sm fqp-btn-primary' : 'fqp-btn fqp-btn-sm'}
                  style={{ padding: '4px 14px', fontSize: 12 }}
                  onClick={() => setActivePlayTypeTab(tab.key)}
                >
                  {tab.label}（{count}）
                </button>
              );
            })}
          </div>

          <div className="fqp-table-wrapper">
            <table className="fqp-table recommendation-table" style={{ fontSize: 13 }}>
              <colgroup>
                <col className="recommendation-table-col-code" />
                <col className="recommendation-table-col-match" />
                <col className="recommendation-table-col-league" />
                <col className="recommendation-table-col-time" />
                <col className="recommendation-table-col-score" />
                <col className="recommendation-table-col-play" />
                <col className="recommendation-table-col-pick" />
                <col className="recommendation-table-col-metric" />
                <col className="recommendation-table-col-metric" />
                <col className="recommendation-table-col-small" />
                <col className="recommendation-table-col-small" />
                <col className="recommendation-table-col-small" />
                <col className="recommendation-table-col-model" />
              </colgroup>
              <thead>
                <tr>
                  <th>编号</th>
                  <th>比赛</th>
                  <th>联赛</th>
                  <th>开赛时间</th>
                  <th>比分</th>
                  <th>玩法</th>
                  <th>推荐</th>
                  <th>模型概率</th>
                  <th>市场概率</th>
                  <th>Edge</th>
                  <th>EV</th>
                  <th>置信度</th>
                  <th>模型</th>
                </tr>
              </thead>
              <tbody>
                {groupedRows.map((row) => {
                  if (row.type === 'date_index') {
                    return (
                      <tr key={row.key} style={{ background: 'rgba(229,9,20,0.06)' }}>
                        <td colSpan={13} style={{ padding: '10px 14px', fontWeight: 700, fontSize: 13, color: 'var(--fqp-accent)', borderBottom: '1px solid var(--fqp-border)', letterSpacing: 0.5 }}>
                          📅 {row.label} 赛果
                        </td>
                      </tr>
                    );
                  }

                  const opts = row.options;
                  const best = opts[0];
                  return (
                    <tr
                      key={row.key}
                      className={onMatchSelect ? 'clickable' : undefined}
                      role={onMatchSelect ? 'button' : undefined}
                      tabIndex={onMatchSelect ? 0 : undefined}
                      onClick={() => selectGroupedRow(row)}
                      onKeyDown={(event) => {
                        if (!onMatchSelect) return;
                        if (event.key === 'Enter' || event.key === ' ') {
                          event.preventDefault();
                          selectGroupedRow(row);
                        }
                      }}
                    >
                      <td className="fqp-mono" style={{ fontSize: 12, color: 'var(--fqp-text-muted)' }}>
                        {fmtMatchNum(row.match_num_str)}
                      </td>
                      <td>
                        <RecommendationTeamStack homeTeam={row.home_team} awayTeam={row.away_team} />
                      </td>
                      <td style={{ fontSize: 12, color: 'var(--fqp-text-muted)' }}>{row.league}</td>
                      <td style={{ fontSize: 12, color: 'var(--fqp-text-muted)', whiteSpace: 'nowrap' }}>
                        {row.kickoff_time ? String(row.kickoff_time).replace('T', ' ').slice(5, 16) : '—'}
                      </td>
                      <td className="fqp-mono" style={{ fontSize: 11, lineHeight: 1.5, whiteSpace: 'nowrap' }}>
                        {row.ft_home_goals != null && row.ft_away_goals != null ? (
                          <>
                            <div style={{ color: 'var(--fqp-text-muted)' }}>
                              半场 {row.ht_home_goals ?? '?'}:{row.ht_away_goals ?? '?'}
                            </div>
                            <div style={{ fontWeight: 700, color: 'var(--fqp-accent)' }}>
                              全场 {row.ft_home_goals}:{row.ft_away_goals}
                            </div>
                            {(row.et_home_goals != null && row.et_away_goals != null) || (row.pk_home_goals != null && row.pk_away_goals != null) ? (
                              <div style={{ color: 'var(--fqp-warning)', fontSize: 10 }}>
                                120分钟[{row.et_home_goals ?? '-'}:{row.et_away_goals ?? '-'}] 点球[{row.pk_home_goals ?? '-'}:{row.pk_away_goals ?? '-'}]
                              </div>
                            ) : null}
                          </>
                        ) : (
                          <span style={{ color: 'var(--fqp-text-muted)' }}>—</span>
                        )}
                      </td>
                      <td>
                        <span style={{ padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 600, background: 'rgba(59,130,246,0.12)', color: 'var(--fqp-info)' }}>
                          {row.play_type_name}
                        </span>
                      </td>
                      <td>
                        <div className="recommendation-option-stack">
                          {opts.map((o) => {
                            const outcome = renderOptionOutcome(row, o);
                            return (
                              <div key={o.option_code} className="recommendation-option-line" title={formatRecommendationOptionDisplay(o, outcome)}>
                                <span className={`recommendation-option-name ${recommendationOptionTone(o)}`}>
                                  {normalizeWinDrawLossLabel(o.option_name)}
                                </span>
                                <span className="recommendation-option-odds">@{o.fair_odds}</span>
                                {outcome ? (
                                  <>
                                    <span className="recommendation-option-separator">/</span>
                                    <span className={`recommendation-option-result ${outcome}`}>
                                      {outcome === 'win' ? '胜利' : '失败'}
                                    </span>
                                  </>
                                ) : null}
                              </div>
                            );
                          })}
                        </div>
                      </td>
                      <td className="fqp-mono">
                        <div className="recommendation-metric-stack success">
                          {opts.map((o) => (
                            <span key={o.option_code} className="recommendation-metric-line">
                              {(o.model_probability * 100).toFixed(1)}%
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="fqp-mono">
                        <div className="recommendation-metric-stack muted">
                          {opts.map((o) => (
                            <span key={o.option_code} className="recommendation-metric-line">
                              {(o.market_probability * 100).toFixed(1)}%
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="fqp-mono">
                        <div className="recommendation-metric-stack">
                          {opts.map((o) => (
                            <span key={o.option_code} style={{ color: o.edge > 0 ? 'var(--fqp-success)' : 'var(--fqp-red-neon)' }}>
                              {o.edge >= 0 ? '+' : ''}{(o.edge * 100).toFixed(1)}%
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="fqp-mono">
                        <div className="recommendation-metric-stack">
                          {opts.map((o) => (
                            <span key={o.option_code} style={{ fontWeight: 700, color: o.ev > 0.05 ? 'var(--fqp-success)' : o.ev > 0.02 ? 'var(--fqp-warning)' : 'var(--fqp-text-muted)' }}>
                              +{o.ev.toFixed(3)}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          <div style={{ width: 40, height: 4, borderRadius: 2, background: 'var(--fqp-panel)', overflow: 'hidden' }}>
                            <div style={{ height: '100%', width: `${Math.round(best.confidence * 100)}%`, background: best.confidence > 0.6 ? 'var(--fqp-success)' : best.confidence > 0.4 ? 'var(--fqp-warning)' : 'var(--fqp-red-neon)', borderRadius: 2 }} />
                          </div>
                          <span style={{ fontSize: 11, color: 'var(--fqp-text-muted)' }}>
                            {(best.confidence * 100).toFixed(0)}%
                          </span>
                        </div>
                      </td>
                      <td style={{ fontSize: 11, color: 'var(--fqp-text-muted)', maxWidth: 100, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {best.model_name}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* Charts */}
      {!loading && tickets.length > 0 && (
        <div className="fqp-grid-2" style={{ marginBottom: '16px' }}>
          {riskDonutOption ? (
            <ChartCard title="风险等级分布" option={riskDonutOption} height={280} />
          ) : (
            <Card title="风险等级分布">
              <div style={{ padding: '40px 0', textAlign: 'center', color: 'var(--fqp-text-muted)' }}>暂无数据</div>
            </Card>
          )}
          {strategyBarOption ? (
            <ChartCard title="策略池对比" option={strategyBarOption} height={300} />
          ) : (
            <Card title="策略池对比">
              <div style={{ padding: '40px 0', textAlign: 'center', color: 'var(--fqp-text-muted)' }}>暂无数据</div>
            </Card>
          )}
        </div>
      )}

      <FilterBar>
        <select
          className="fqp-select"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          style={{ minWidth: '160px' }}
        >
          <option value="">全部状态</option>
          <option value="generated">待激活</option>
          <option value="activated">已激活</option>
          <option value="settled">已结算</option>
          <option value="invalidated">已失效</option>
        </select>
      </FilterBar>
      <Card style={{ padding: 0, overflow: 'hidden' }}>
        <DataTable
          columns={columns}
          rows={filtered}
          loading={loading}
          emptyText="暂无推荐票单，系统将在每日 16:00 从模型预测中生成推荐候选"
          onRowClick={(row) => navigate(`/recommendations/${row.id}`)}
          rowKey={(r) => String(r.id)}
        />
      </Card>
    </div>
  );
}
