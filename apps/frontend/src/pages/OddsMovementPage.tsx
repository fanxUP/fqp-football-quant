/** Odds Movement Page — SP trend tracking and anomaly alerts. */

import { useEffect, useState, useMemo } from 'react';
import { api } from '../core/apiClient';
import type { DashboardOddsPoint, DashboardOddsAnomaly, SimulatorMatch } from '../core/types';
import { ApiError } from '../core/types';
import PageHeader from '../shared/components/PageHeader';
import Card from '../shared/components/Card';
import ErrorState from '../shared/components/ErrorState';
import LoadingSpinner from '../shared/components/LoadingSpinner';
import EmptyState from '../shared/components/EmptyState';
import { OddsMovementChart } from '../visualization';
import { applyChartTheme, CHART_COLORS } from '../visualization';
import ChartCard from '../shared/components/ChartCard';

type PlayTab = 'spf' | 'rqspf' | 'bf' | 'zjq' | 'bqc';

const PLAY_TABS: PlayTab[] = ['spf', 'rqspf', 'bf', 'zjq', 'bqc'];
const PLAY_LABELS: Record<string, string> = {
  spf: '胜平负', rqspf: '让球', bf: '比分', zjq: '总进球', bqc: '半全场',
};


export default function OddsMovementPage() {
  const [matches, setMatches] = useState<SimulatorMatch[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedMatchId, setSelectedMatchId] = useState<number | null>(null);
  const [activePlay, setActivePlay] = useState<PlayTab>('spf');
  const [selectedOptionCode, setSelectedOptionCode] = useState<string>('');

  // Odds data
  const [oddsData, setOddsData] = useState<DashboardOddsPoint[]>([]);
  const [anomalies, setAnomalies] = useState<DashboardOddsAnomaly[]>([]);
  const [oddsLoading, setOddsLoading] = useState(false);
  const [oddsError, setOddsError] = useState<string | null>(null);

  // Load match list from simulator (has odds data + match_num_str)
  useEffect(() => {
    api.simulator.matches({ limit: 100 })
      .then((res) => {
        if (res.matches.length > 0) {
          setMatches(res.matches);
          setSelectedMatchId(res.matches[0].match_id);
        }
        setLoading(false);
      })
      .catch((e) => {
        setError(e instanceof ApiError ? e.message : '加载比赛列表失败');
        setLoading(false);
      });
  }, []);

  // Load odds data when match or play type changes
  useEffect(() => {
    if (!selectedMatchId) return;
    setOddsLoading(true);
    setOddsError(null);
    // Reset option code — auto-select useEffect picks first option immediately
    setSelectedOptionCode('');
    api.dashboard.oddsMovement({ match_id: selectedMatchId, play_type: activePlay })
      .then((res) => {
        const series = res.data?.series || [];
        setOddsData(series as DashboardOddsPoint[]);
        setAnomalies(res.data?.anomalies || []);
        setOddsLoading(false);
      })
      .catch((e) => {
        setOddsError(e instanceof ApiError ? e.message : '加载赔率走势失败');
        setOddsLoading(false);
      });
  }, [selectedMatchId, activePlay]);

  const selectedMatch = matches.find((m) => m.match_id === selectedMatchId);

  // Extract available option codes from the selected match + play type
  const availableOptions = useMemo(() => {
    if (!selectedMatch?.odds?.[activePlay]?.options) return [];
    return selectedMatch.odds[activePlay].options.map((opt) => ({
      code: opt.option_code,
      name: opt.option_name,
    }));
  }, [selectedMatch, activePlay]);

  // Auto-select first option when match/play type changes and options are available
  useEffect(() => {
    if (!selectedOptionCode && availableOptions.length > 0) {
      setSelectedOptionCode(availableOptions[0].code);
    }
  }, [availableOptions, selectedOptionCode]);

  // Filter odds data by selected option
  const filteredOddsData = useMemo(() => {
    if (!selectedOptionCode) return oddsData; // fallback: show all
    return oddsData.filter((d) => d.option_code === selectedOptionCode);
  }, [oddsData, selectedOptionCode]);

  // Get the display name for the selected option
  const selectedOptionName = useMemo(() => {
    if (!selectedOptionCode) return '';
    const opt = availableOptions.find((o) => o.code === selectedOptionCode);
    return opt ? opt.name : selectedOptionCode;
  }, [selectedOptionCode, availableOptions]);

  // Get handicap info for display
  const handicapInfo = useMemo(() => {
    if (!selectedMatch?.odds?.[activePlay]?.handicap) return null;
    return selectedMatch.odds[activePlay].handicap;
  }, [selectedMatch, activePlay]);

  // Build implied probability chart (dual Y-axis)
  const impliedProbOption = (() => {
    if (!filteredOddsData.length) return null;
    const times = filteredOddsData.map((d) => String(d.snapshot_time).slice(11, 19));
    const probs = filteredOddsData.map((d) => d.implied_probability != null ? d.implied_probability * 100 : null);
    const sps = filteredOddsData.map((d) => d.sp_value);
    return applyChartTheme({
      tooltip: {
        trigger: 'axis',
        valueFormatter: (v: number, seriesIdx: number) =>
          seriesIdx === 1 ? `${v.toFixed(2)}%` : v.toFixed(2),
      },
      legend: { data: ['SP', '隐含概率%'] },
      grid: { left: '3%', right: '7%', bottom: '10%', top: '14%', containLabel: true },
      xAxis: { type: 'category', data: times, axisLabel: { rotate: 30 } },
      yAxis: [
        { type: 'value', name: 'SP' },
        {
          type: 'value', name: '概率%',
          min: 0, max: 100,
          axisLabel: { formatter: (v: number) => `${v}%` },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: 'SP',
          type: 'line',
          data: sps,
          smooth: true,
          symbol: 'none',
          lineStyle: { color: CHART_COLORS.blue, width: 2 },
          areaStyle: { color: CHART_COLORS.areaAgent },
        },
        {
          name: '隐含概率%',
          type: 'line',
          yAxisIndex: 1,
          data: probs,
          smooth: true,
          symbol: 'none',
          lineStyle: { color: CHART_COLORS.amber, width: 1.5, type: 'dashed' },
        },
      ],
    } as echarts.EChartsOption);
  })();

  if (loading) return <LoadingSpinner text="加载赛事数据..." size="lg" />;
  if (error) return <ErrorState message={error} onRetry={() => window.location.reload()} />;

  return (
    <div>
      <PageHeader
        title="赔率走势"
        subtitle="官方 SP 走势与市场隐含概率追踪"
      />

      {/* Match selector + play type tabs */}
      <Card style={{ marginBottom: '20px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px', flexWrap: 'wrap' }}>
          <select
            className="fqp-select"
            value={selectedMatchId ?? ''}
            onChange={(e) => setSelectedMatchId(Number(e.target.value))}
            style={{ minWidth: 240 }}
          >
            {matches.length === 0 && <option value="">暂无比赛</option>}
            {matches.map((m) => (
              <option key={m.match_id} value={m.match_id}>
                [{m.match_num_str || `#${m.match_id}`}] {m.home_team_name} vs {m.away_team_name}
              </option>
            ))}
          </select>

          {/* Option selector */}
          {availableOptions.length > 0 && (
            <select
              className="fqp-select"
              value={selectedOptionCode}
              onChange={(e) => setSelectedOptionCode(e.target.value)}
              style={{ minWidth: 100 }}
            >
              <option value="">全部选项</option>
              {availableOptions.map((opt) => (
                <option key={opt.code} value={opt.code}>{opt.name} ({opt.code})</option>
              ))}
            </select>
          )}

          <div style={{ display: 'flex', gap: 4, marginLeft: 'auto' }}>
            {PLAY_TABS.map((pt) => (
              <button
                key={pt}
                className={`fqp-btn${activePlay === pt ? ' fqp-btn-primary' : ''}`}
                style={{ padding: '4px 12px', fontSize: 12 }}
                onClick={() => setActivePlay(pt)}
              >
                {PLAY_LABELS[pt]}
              </button>
            ))}
          </div>
        </div>

        {selectedMatch && (
          <div style={{ marginTop: 12, fontSize: 13, color: 'var(--fqp-text-muted)' }}>
            {selectedMatch.league_name} · {selectedMatch.home_team_name} vs {selectedMatch.away_team_name}
            · {String(selectedMatch.kickoff_time).replace('T', ' ').slice(0, 16)}
          </div>
        )}
      </Card>

      {/* Odds movement chart */}
      {oddsLoading ? (
        <Card title="赔率走势">
          <div style={{ height: 320, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <div className="fqp-skeleton" style={{ width: '90%', height: '80%', borderRadius: 8 }} />
          </div>
        </Card>
      ) : oddsError ? (
        <Card title="赔率走势">
          <div style={{ height: 320, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--fqp-red-neon)' }}>
            ⚠️ {oddsError}
          </div>
        </Card>
      ) : selectedOptionCode && filteredOddsData.length > 0 ? (
        <>
          <OddsMovementChart
            data={filteredOddsData.map((d) => ({
              time: String(d.snapshot_time).slice(11, 19),
              spValue: d.sp_value,
              impliedProb: d.implied_probability ?? 0,
              anomaly: d.sp_value > 50 || (
                d.prev_sp_value != null && d.prev_sp_value > 0
                  && (d.sp_value / d.prev_sp_value > 3 || d.sp_value / d.prev_sp_value < 0.33)
              ),
            }))}
            title={`${PLAY_LABELS[activePlay] || activePlay} 赔率走势${selectedOptionName ? ` · ${selectedOptionName}` : ''}${handicapInfo != null ? ` (${handicapInfo > 0 ? '+' : ''}${handicapInfo})` : ''}`}
            height={320}
          />

          {/* Implied probability chart */}
          {impliedProbOption && (
            <ChartCard
              title="隐含概率"
              subtitle="基于 SP 倒算"
              option={impliedProbOption}
              height={260}
            />
          )}

          {/* Anomaly alerts */}
          {anomalies.length > 0 && (
            <Card title="⚠️ 异常提醒" style={{ marginTop: '16px' }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {anomalies.map((a, i) => (
                  <div
                    key={i}
                    className="fqp-anim-slideLeft"
                    style={{
                      padding: '8px 12px',
                      background: 'rgba(255,42,61,0.06)',
                      borderRadius: 6,
                      borderLeft: '3px solid var(--fqp-red-neon)',
                      animationDelay: `${i * 60}ms`,
                      fontSize: 13,
                    }}
                  >
                    <strong>{a.option_name}</strong>：
                    {a.type === 'jump' ? '跳涨' : '跳跌'}
                    {' '}{a.sp_value.toFixed(2)}（前值 {a.prev_sp_value.toFixed(2)}，倍数 {a.ratio}×）
                    <span style={{ marginLeft: 8, color: 'var(--fqp-text-muted)', fontSize: 11 }}>
                      时间: {a.time}
                    </span>
                  </div>
                ))}
              </div>
            </Card>
          )}
        </>
      ) : (
        <EmptyState icon="📉" title="暂无赔率快照" description="该比赛 / 玩法暂无赔率快照数据，请选择其他比赛或玩法" />
      )}
    </div>
  );
}
