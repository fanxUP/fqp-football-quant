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
import PlayTypeWinRateChart from './reviews/PlayTypeWinRateChart';
import RealProfitLossChart from './reviews/RealProfitLossChart';
import MatchReviewCards from './reviews/MatchReviewCards';
import ReportAutomationPanel from './reviews/ReportAutomationPanel';
import AutomaticReportArchivePanel from './reviews/AutomaticReportArchivePanel';

type TabKey = 'daily' | 'weekly' | 'monthly' | 'settlements' | 'errors';

interface ReviewsPageProps {
  embedded?: boolean;
}

export default function ReviewsPage({ embedded = false }: ReviewsPageProps) {
  const [activeTab, setActiveTab] = useState<TabKey>('daily');

  return (
    <div>
      {!embedded && <PageHeader title="复盘与报告" subtitle="基于已结算彩票、官方赛果与归档预测的只读复盘" />}
      {!embedded && <ReportAutomationPanel />}
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

  if (error) return <ErrorState message={error} onRetry={() => window.location.reload()} />;

  return (
    <div>
      {/* Charts */}
      {!loading && (
        <div className="fqp-grid-2" style={{ marginBottom: '16px' }}>
          <RealProfitLossChart reviews={reviews} loading={loading} />
          {errorDistOption ? (
            <ChartCard
              title="盈亏天数分布"
              subtitle="按已结算日统计"
              option={errorDistOption}
              height={300}
              variant="trading"
            />
          ) : (
            <Card title="盈亏天数分布">
              <div style={{ padding: '40px 0', textAlign: 'center', color: 'var(--fqp-text-muted)' }}>暂无数据</div>
            </Card>
          )}
        </div>
      )}

      <PlayTypeWinRateChart data={playTypeData} loading={loading} />

      <DataTable
        columns={columns}
        rows={reviews}
        loading={loading}
        emptyText="暂无日报数据，官方赛果与相关票据结算完成后自动生成"
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
                <div style={{ marginTop: '16px', display: 'flex', gap: '24px', flexWrap: 'wrap', fontSize: '13px', color: 'var(--fqp-text-muted)' }}>
                  <div>建议投入: ¥{review.suggested_stake.toFixed(0)}</div>
                  <div>实际投入: ¥{review.actual_stake.toFixed(0)}</div>
                  <div>预算使用率: {(review.budget_usage_rate * 100).toFixed(0)}%</div>
                  <div>最大单票亏损: ¥{review.max_single_ticket_loss.toFixed(2)}</div>
                </div>
                <AutomaticReportArchivePanel sourceType="post_daily" sourceRef={review.review_date} />
                <MatchReviewCards reviewDate={review.review_date} />
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
          <AutomaticReportArchivePanel sourceType="post_weekly" sourceRef={review.week_start} />
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
          <AutomaticReportArchivePanel sourceType="post_monthly" sourceRef={review.review_month} />
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
