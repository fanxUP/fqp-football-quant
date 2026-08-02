import { useEffect, useState } from 'react';
import { api } from '../core/apiClient';
import type { DailyReview, WeeklyReview, MonthlyReview, Settlement, ErrorAnalysis, ErrorSummary, PlayTypeWinRate } from '../core/types';
import { ApiError } from '../core/types';
import PageHeader from '../shared/components/PageHeader';
import Card from '../shared/components/Card';
import ChartCard from '../shared/components/ChartCard';
import DataTable, { type Column } from '../shared/components/DataTable';
import LoadingSpinner from '../shared/components/LoadingSpinner';
import EmptyState from '../shared/components/EmptyState';
import ErrorState from '../shared/components/ErrorState';
import StatusBadge from '../shared/components/StatusBadge';
import { formatTimestamp } from '../shared/utils';
import BusinessInterpretationPanel from './agent-workspace/BusinessInterpretationPanel';

type TabKey = 'daily' | 'weekly' | 'monthly' | 'settlements' | 'errors';

interface ReviewsPageProps {
  embedded?: boolean;
}

export default function ReviewsPage({ embedded = false }: ReviewsPageProps) {
  const [activeTab, setActiveTab] = useState<TabKey>('daily');

  return (
    <div>
      {!embedded && <PageHeader title="复盘中心" />}
      <div className="fqp-tabs">
        {([
          ['daily', '日报'],
          ['weekly', '周报'],
          ['monthly', '月报'],
          ['settlements', '结算记录'],
          ['errors', '错因分析'],
        ] as [TabKey, string][]).map(([key, label]) => (
          <button
            key={key}
            className={`fqp-tab${activeTab === key ? ' active' : ''}`}
            onClick={() => setActiveTab(key)}
          >
            {label}
          </button>
        ))}
      </div>

      <div key={activeTab} className="fqp-anim-fadeIn">
        {activeTab === 'daily' && <DailyReviewsTab />}
        {activeTab === 'weekly' && <WeeklyReviewsTab />}
        {activeTab === 'monthly' && <MonthlyReviewsTab />}
        {activeTab === 'settlements' && <SettlementsTab />}
        {activeTab === 'errors' && <ErrorAnalysisTab />}
      </div>
    </div>
  );
}

// ---- Daily Reviews Tab ----
function DailyReviewsTab() {
  const [reviews, setReviews] = useState<DailyReview[]>([]);
  const [playTypeData, setPlayTypeData] = useState<PlayTypeWinRate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedDate, setExpandedDate] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      api.reviews.daily(30),
      api.reviews.playTypeWinRate(30),
    ])
      .then(([r, pt]) => {
        setReviews(r.reviews);
        setPlayTypeData(pt.data || []);
        setLoading(false);
      })
      .catch((e) => { setError(e instanceof ApiError ? e.message : '加载失败'); setLoading(false); });
  }, []);

  const columns: Column<DailyReview>[] = [
    { key: 'review_date', title: '日期' },
    { key: 'official_match_count', title: '官方场次', render: (v) => <span className="fqp-mono">{String(v)}</span> },
    { key: 'analyzable_match_count', title: '可分析', render: (v) => <span className="fqp-mono">{String(v)}</span> },
    { key: 'simulation_ticket_count', title: '投注票', render: (v) => <span className="fqp-mono">{String(v)}</span> },
    { key: 'real_ticket_count', title: '彩票', render: (v) => <span className="fqp-mono">{String(v)}</span> },
    {
      key: 'real_profit_loss',
      title: '实盘盈亏',
      render: (v) => {
        const val = Number(v);
        const color = val > 0 ? 'var(--fqp-success)' : val < 0 ? 'var(--fqp-red-neon)' : 'var(--fqp-text-muted)';
        return <span className="fqp-mono" style={{ color }}>{val >= 0 ? '+' : ''}{val.toFixed(2)}</span>;
      },
    },
  ];

  // ---- P&L bar chart ----
  const plChartOption = (() => {
    if (reviews.length === 0) return null;
    const sorted = [...reviews].sort((a, b) => a.review_date.localeCompare(b.review_date));
    const dates = sorted.map((r) => r.review_date.slice(5));
    const profits = sorted.map((r) => r.real_profit_loss);
    let cum = 0;
    const cumulative = sorted.map((r) => {
      cum += r.real_profit_loss;
      return cum;
    });

    return {
      tooltip: {
        trigger: 'axis' as const,
        axisPointer: { type: 'shadow' as const },
      },
      legend: {
        data: ['日盈亏', '累计盈亏'],
        top: 0,
      },
      grid: {
        left: '3%',
        right: '4%',
        bottom: '12%',
        top: '40px',
        containLabel: true,
      },
      xAxis: {
        type: 'category' as const,
        data: dates,
        axisLabel: { rotate: 45, fontSize: 11 },
      },
      yAxis: [
        {
          type: 'value' as const,
          name: '日盈亏 (¥)',
          nameTextStyle: { fontSize: 11 },
          axisLabel: { fontSize: 11 },
          splitLine: { lineStyle: { color: 'var(--fqp-border-subtle)' } },
        },
        {
          type: 'value' as const,
          name: '累计 (¥)',
          nameTextStyle: { fontSize: 11 },
          axisLabel: { fontSize: 11 },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: '日盈亏',
          type: 'bar',
          data: profits,
          itemStyle: {
            color: (params: { value: number }) =>
              (params.value >= 0 ? '#22c55e' : '#ef4444'),
          },
        },
        {
          name: '累计盈亏',
          type: 'line',
          yAxisIndex: 1,
          data: cumulative,
          lineStyle: { color: '#3b82f6', width: 2 },
          itemStyle: { color: '#3b82f6' },
          symbol: 'none',
          smooth: true,
        },
      ],
    };
  })();

  // ---- Error distribution treemap ----
  const errorDistOption = (() => {
    // Count matches with losses (negative profit) vs wins
    const lossDays = reviews.filter((r) => r.real_profit_loss < 0).length;
    const winDays = reviews.filter((r) => r.real_profit_loss > 0).length;
    const flatDays = reviews.filter((r) => r.real_profit_loss === 0).length;
    if (lossDays + winDays + flatDays === 0) return null;

    return {
      tooltip: {
        trigger: 'item' as const,
        formatter: '{b}: {c} 天 ({d}%)',
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
            formatter: '{b}\n{d}%',
            fontSize: 12,
            lineHeight: 17,
            color: '#F4F5F7',
            fontWeight: 600,
          },
          labelLine: {
            length: 22,
            length2: 36,
            lineStyle: { color: 'rgba(255,255,255,0.12)' },
          },
          data: [
            { value: winDays, name: '盈利日', itemStyle: { color: '#22c55e' } },
            { value: flatDays, name: '持平', itemStyle: { color: '#6b7280' } },
            { value: lossDays, name: '亏损日', itemStyle: { color: '#ef4444' } },
          ],
        },
      ],
    };
  })();

  // ---- Play-type win-rate line chart ----
  const playTypeWinRateOption = (() => {
    if (playTypeData.length === 0) return null;

    // Unique play types and dates
    const playTypes = [...new Set(playTypeData.map((r) => r.play_type))].sort();
    const dates = [...new Set(playTypeData.map((r) => r.settle_date))].sort();

    // Color palette for play types
    const colors = ['#22c55e', '#3b82f6', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#06b6d4', '#f97316'];

    // Build series: one line per play type
    const series = playTypes.map((pt, i) => {
      const data = dates.map((d) => {
        const row = playTypeData.find((r) => r.settle_date === d && r.play_type === pt);
        return row ? +(row.win_rate * 100).toFixed(1) : null;
      });
      return {
        name: pt,
        type: 'line' as const,
        data,
        smooth: true,
        symbol: 'circle',
        symbolSize: 5,
        lineStyle: { width: 2, color: colors[i % colors.length] },
        itemStyle: { color: colors[i % colors.length] },
        connectNulls: true,
      };
    });

    return {
      tooltip: {
        trigger: 'axis' as const,
        formatter: (params: { seriesName: string; value: number | null; marker: string }[]) => {
          const lines = params
            .filter((p) => p.value !== null)
            .map((p) => `${p.marker} ${p.seriesName}: ${p.value}%`);
          return lines.length ? lines.join('<br/>') : '';
        },
      },
      legend: {
        data: playTypes,
        bottom: 0,
        textStyle: { fontSize: 11 },
      },
      grid: {
        left: '3%',
        right: '4%',
        bottom: '14%',
        top: '10px',
        containLabel: true,
      },
      xAxis: {
        type: 'category' as const,
        data: dates.map((d) => d.slice(5)),
        axisLabel: { rotate: 45, fontSize: 11 },
      },
      yAxis: {
        type: 'value' as const,
        name: '胜率 (%)',
        nameTextStyle: { fontSize: 11 },
        axisLabel: { fontSize: 11, formatter: '{value}%' },
        min: 0,
        max: 100,
        splitLine: { lineStyle: { color: 'var(--fqp-border-subtle)' } },
      },
      series,
    };
  })();

  if (error) return <ErrorState message={error} onRetry={() => window.location.reload()} />;

  return (
    <div>
      {/* Charts */}
      {!loading && (
        <div className="fqp-grid-2" style={{ marginBottom: '16px' }}>
          {plChartOption ? (
            <ChartCard title="实盘盈亏走势" option={plChartOption} height={300} />
          ) : (
            <Card title="实盘盈亏走势">
              <div style={{ padding: '40px 0', textAlign: 'center', color: 'var(--fqp-text-muted)' }}>暂无数据</div>
            </Card>
          )}
          {errorDistOption ? (
            <ChartCard title="盈亏天数分布" option={errorDistOption} height={300} />
          ) : (
            <Card title="盈亏天数分布">
              <div style={{ padding: '40px 0', textAlign: 'center', color: 'var(--fqp-text-muted)' }}>暂无数据</div>
            </Card>
          )}
        </div>
      )}

      {/* Play-type win-rate line chart */}
      {!loading && playTypeWinRateOption && (
        <ChartCard
          title="各玩法胜率走势"
          option={playTypeWinRateOption}
          height={320}
        />
      )}

      <DataTable
        columns={columns}
        rows={reviews}
        loading={loading}
        emptyText="暂无日报数据，每日 23:30 自动生成"
        onRowClick={(row) => setExpandedDate(expandedDate === row.review_date ? null : row.review_date)}
        rowKey={(r) => r.review_date}
      />
      {expandedDate && (
        <Card title={`📅 ${expandedDate} 日报详情`} style={{ marginTop: '16px', animation: 'fqpSlideUpBounce 0.4s ease both' }}>
          {(() => {
            const review = reviews.find((r) => r.review_date === expandedDate);
            if (!review) return null;
            return (
              <div style={{ fontSize: '14px', lineHeight: '2', whiteSpace: 'pre-wrap' }}>
                {review.summary_text || '暂无摘要文本'}
                <div style={{ marginTop: '16px', display: 'flex', gap: '24px', flexWrap: 'wrap', fontSize: '13px', color: 'var(--fqp-text-muted)' }}>
                  <div>建议投入: ¥{review.suggested_stake.toFixed(0)}</div>
                  <div>实际投入: ¥{review.actual_stake.toFixed(0)}</div>
                  <div>预算使用率: {(review.budget_usage_rate * 100).toFixed(0)}%</div>
                  <div>最大单票亏损: ¥{review.max_single_ticket_loss.toFixed(2)}</div>
                </div>
                <BusinessInterpretationPanel title="赛后复盘解读" onRun={(focusQuestion) =>
                  api.agentInterpretations.postMatch('post_daily', review.review_date, focusQuestion)
                } />
              </div>
            );
          })()}
        </Card>
      )}
    </div>
  );
}

// ---- Weekly Reviews Tab ----
function WeeklyReviewsTab() {
  const [reviews, setReviews] = useState<WeeklyReview[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  useEffect(() => {
    api.reviews.weekly(12)
      .then((r) => { setReviews(r.reviews); setLoading(false); })
      .catch((e) => { setError(e instanceof ApiError ? e.message : '加载失败'); setLoading(false); });
  }, []);

  const columns: Column<WeeklyReview>[] = [
    { key: 'week_start', title: '周开始' },
    { key: 'week_end', title: '周结束' },
    {
      key: 'summary_text',
      title: '摘要',
      render: (v) => {
        const s = String(v || '');
        return s.length > 80 ? s.slice(0, 80) + '...' : s;
      },
    },
    { key: 'created_at', title: '生成时间', render: (v) => formatTimestamp(v) },
  ];

  if (error) return <ErrorState message={error} onRetry={() => window.location.reload()} />;
  return (
    <>
      <DataTable columns={columns} rows={reviews} loading={loading} emptyText="暂无周报数据"
        onRowClick={(row) => setExpandedId(expandedId === row.id ? null : row.id)} rowKey={(r) => String(r.id)} />
      {expandedId != null && (() => {
        const review = reviews.find((item) => item.id === expandedId);
        return review ? <Card title={`📅 ${review.week_start} 至 ${review.week_end} 周报详情`} style={{ marginTop: '16px' }}>
          <div style={{ whiteSpace: 'pre-wrap' }}>{review.summary_text || '暂无摘要文本'}</div>
          <BusinessInterpretationPanel title="赛后复盘解读" onRun={(focusQuestion) =>
            api.agentInterpretations.postMatch('post_weekly', String(review.id), focusQuestion)
          } />
        </Card> : null;
      })()}
    </>
  );
}

// ---- Monthly Reviews Tab ----
function MonthlyReviewsTab() {
  const [reviews, setReviews] = useState<MonthlyReview[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  useEffect(() => {
    api.reviews.monthly(12)
      .then((r) => { setReviews(r.reviews); setLoading(false); })
      .catch((e) => { setError(e instanceof ApiError ? e.message : '加载失败'); setLoading(false); });
  }, []);

  const columns: Column<MonthlyReview>[] = [
    { key: 'review_month', title: '月份' },
    {
      key: 'summary_text',
      title: '摘要',
      render: (v) => {
        const s = String(v || '');
        return s.length > 100 ? s.slice(0, 100) + '...' : s;
      },
    },
    { key: 'created_at', title: '生成时间', render: (v) => formatTimestamp(v) },
  ];

  if (error) return <ErrorState message={error} onRetry={() => window.location.reload()} />;
  return (
    <>
      <DataTable columns={columns} rows={reviews} loading={loading} emptyText="暂无月报数据"
        onRowClick={(row) => setExpandedId(expandedId === row.id ? null : row.id)} rowKey={(r) => String(r.id)} />
      {expandedId != null && (() => {
        const review = reviews.find((item) => item.id === expandedId);
        return review ? <Card title={`📅 ${String(review.review_month ?? review.month ?? review.id)} 月报详情`} style={{ marginTop: '16px' }}>
          <div style={{ whiteSpace: 'pre-wrap' }}>{review.summary_text || '暂无摘要文本'}</div>
          <BusinessInterpretationPanel title="赛后复盘解读" onRun={(focusQuestion) =>
            api.agentInterpretations.postMatch('post_monthly', String(review.id), focusQuestion)
          } />
        </Card> : null;
      })()}
    </>
  );
}

// ---- Settlements Tab ----
function SettlementsTab() {
  const [settlements, setSettlements] = useState<Settlement[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));

  useEffect(() => {
    setLoading(true);
    api.settlements.list({ date, limit: 100 })
      .then((r) => { setSettlements(r.settlements); setLoading(false); })
      .catch((e) => { setError(e instanceof ApiError ? e.message : '加载失败'); setLoading(false); });
  }, [date]);

  const totalStake = settlements.reduce((s, x) => s + x.stake_amount, 0);
  const totalPL = settlements.reduce((s, x) => s + x.profit_loss, 0);

  const columns: Column<Settlement>[] = [
    { key: 'ticket_source', title: '来源' },
    { key: 'ticket_id', title: '票单ID', render: (v) => <span className="fqp-mono">#{String(v)}</span> },
    {
      key: 'is_won',
      title: '结果',
      render: (v) => <StatusBadge status={v ? 'ok' : 'error'} label={v ? '中奖' : '未中'} />,
    },
    { key: 'stake_amount', title: '投注', render: (v) => <span className="fqp-mono">¥{Number(v).toFixed(2)}</span> },
    { key: 'prize_amount', title: '奖金', render: (v) => <span className="fqp-mono">¥{Number(v).toFixed(2)}</span> },
    {
      key: 'profit_loss',
      title: '盈亏',
      render: (v) => {
        const val = Number(v);
        const color = val > 0 ? 'var(--fqp-success)' : val < 0 ? 'var(--fqp-red-neon)' : 'var(--fqp-text-muted)';
        return <span className="fqp-mono" style={{ color }}>{val >= 0 ? '+' : ''}{val.toFixed(2)}</span>;
      },
    },
    { key: 'settle_time', title: '结算时间', render: (v) => formatTimestamp(v) },
  ];

  if (error) return <ErrorState message={error} onRetry={() => window.location.reload()} />;

  return (
    <div>
      <div className="fqp-filter-bar" style={{ marginBottom: '16px' }}>
        <input
          className="fqp-input"
          type="date"
          value={date}
          onChange={(e) => setDate(e.target.value)}
          style={{ minWidth: '180px' }}
        />
      </div>
      {settlements.length > 0 && (
        <Card style={{ marginBottom: '16px', display: 'flex', gap: '32px' }}>
          <div>
            <div className="fqp-label">总投注</div>
            <div className="fqp-mono" style={{ fontSize: '18px', fontWeight: 700 }}>¥{totalStake.toFixed(2)}</div>
          </div>
          <div>
            <div className="fqp-label">净盈亏</div>
            <div
              className="fqp-mono"
              style={{
                fontSize: '18px',
                fontWeight: 700,
                color: totalPL > 0 ? 'var(--fqp-success)' : totalPL < 0 ? 'var(--fqp-red-neon)' : 'var(--fqp-text-muted)',
              }}
            >
              {totalPL >= 0 ? '+' : ''}{totalPL.toFixed(2)}
            </div>
          </div>
          <div>
            <div className="fqp-label">结算笔数</div>
            <div className="fqp-mono" style={{ fontSize: '18px', fontWeight: 700 }}>{settlements.length}</div>
          </div>
        </Card>
      )}
      <Card style={{ padding: 0, overflow: 'hidden' }}>
        <DataTable
          columns={columns}
          rows={settlements}
          loading={loading}
          emptyText={`${date} 暂无结算记录`}
          rowKey={(r) => String(r.id)}
        />
      </Card>
    </div>
  );
}

// ---- Error Analysis Tab ----
function ErrorAnalysisTab() {
  const [errors, setErrors] = useState<ErrorAnalysis[]>([]);
  const [summary, setSummary] = useState<ErrorSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      api.errorAnalysis.list({ limit: 100 }),
      api.errorAnalysis.summary(7),
    ])
      .then(([e, s]) => {
        setErrors(e.errors);
        setSummary(s);
        setLoading(false);
      })
      .catch((e) => { setErr(e instanceof ApiError ? e.message : '加载失败'); setLoading(false); });
  }, []);

  const columns: Column<ErrorAnalysis>[] = [
    { key: 'match_id', title: '比赛', render: (v) => <span className="fqp-mono">#{String(v)}</span> },
    {
      key: 'error_type',
      title: '错因类型',
      render: (v) => <StatusBadge status="warning" label={String(v)} />,
    },
    { key: 'error_level', title: '严重度', render: (v) => <StatusBadge status={v === 'high' ? 'error' : v === 'medium' ? 'warning' : 'info'} label={String(v)} /> },
    { key: 'root_cause', title: '根因', render: (v) => <span style={{ maxWidth: '300px', display: 'inline-block', overflow: 'hidden', textOverflow: 'ellipsis' }}>{String(v)}</span> },
    { key: 'actual_result', title: '实际赛果', width: '80px', render: (v) => <span className="fqp-mono">{String(v)}</span> },
    { key: 'created_at', title: '时间', render: (v) => formatTimestamp(v) },
  ];

  if (err) return <ErrorState message={err} onRetry={() => window.location.reload()} />;

  return (
    <div>
      {/* Summary */}
      {summary?.errors && summary.errors.length > 0 && (
        <Card title="近7天错因分布" style={{ marginBottom: '16px' }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px' }}>
            {summary.errors.map((e, i) => (
              <div
                key={e.error_type}
                style={{
                  padding: '8px 16px',
                  background: 'var(--fqp-panel)',
                  borderRadius: 'var(--fqp-radius-sm)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  animation: `fqpBadgePop 0.3s ease both`,
                  animationDelay: `${i * 80}ms`,
                }}
              >
                <StatusBadge status="warning" label={e.error_type} />
                <span className="fqp-mono" style={{ fontSize: '16px', fontWeight: 700 }}>×{e.count}</span>
              </div>
            ))}
          </div>
        </Card>
      )}

      <Card style={{ padding: 0, overflow: 'hidden' }}>
        <DataTable
          columns={columns}
          rows={errors}
          loading={loading}
          emptyText="暂无错因分析数据，每日 23:45 自动生成"
          rowKey={(r) => String(r.id)}
        />
      </Card>
    </div>
  );
}
