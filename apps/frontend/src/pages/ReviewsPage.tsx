import { useCallback, useState } from 'react';
import { api } from '../core/apiClient';
import type { WeeklyReview, MonthlyReview, Settlement, ErrorAnalysis } from '../core/types';
import PageHeader from '../shared/components/PageHeader';
import Card from '../shared/components/Card';
import ChartCard from '../shared/components/ChartCard';
import DataTable, { type Column } from '../shared/components/DataTable';
import EmptyState from '../shared/components/EmptyState';
import StatusBadge from '../shared/components/StatusBadge';
import { formatTimestamp } from '../shared/utils';
import PlayTypeWinRateChart from './reviews/PlayTypeWinRateChart';
import RealProfitLossChart from './reviews/RealProfitLossChart';
import ReportAutomationPanel from './reviews/ReportAutomationPanel';
import AutomaticReportArchivePanel from './reviews/AutomaticReportArchivePanel';
import ReportResearchSummary from './reviews/ReportResearchSummary';
import useReadOnlyResource from '../features/command-center/useReadOnlyResource';
import ReadEvidenceStatus from './ReadEvidenceStatus';
import './BusinessEvidence.css';
import ReviewDateIndex from './reviews/ReviewDateIndex';

type TabKey = 'daily' | 'weekly' | 'monthly' | 'settlements' | 'errors';

interface ReviewsPageProps {
  embedded?: boolean;
}

export default function ReviewsPage({ embedded = false }: ReviewsPageProps) {
  const [activeTab, setActiveTab] = useState<TabKey>('daily');

  return (
    <div className="be-page">
      {!embedded && <PageHeader title="复盘与报告" subtitle="基于已结算彩票、官方赛果与归档预测的只读复盘" />}
      {!embedded && <ReportAutomationPanel />}
      <div className="fqp-tabs" aria-label="报告类型">
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
            aria-pressed={activeTab === key}
            onClick={() => setActiveTab(key)}
          >
            {label}
          </button>
        ))}
      </div>

      <div key={activeTab} >
        {activeTab === 'daily' && <DailyReviewsTab />}
        {activeTab === 'weekly' && <WeeklyReviewsTab />}
        {activeTab === 'monthly' && <MonthlyReviewsTab />}
        {activeTab === 'settlements' && <SettlementsTab />}
        {activeTab === 'errors' && <ErrorAnalysisTab />}
      </div>
    </div>
  );
}

function checkedRows<T>(rows: T[], limit: number, key: (row: T) => string | number): T[] {
  if (!Array.isArray(rows) || rows.length > limit || rows.some(row => !row || key(row) == null)
    || new Set(rows.map(key)).size !== rows.length) throw new Error('复盘数据格式不正确');
  return rows;
}

function shanghaiToday(): string {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date());
  return ['year', 'month', 'day'].map(type => parts.find(part => part.type === type)?.value).join('-');
}

// ---- Daily Reviews Tab ----
function DailyReviewsTab() {
  const fetchReviews = useCallback(async () => {
    const response = await api.reviews.daily(30);
    const rows = checkedRows(response.reviews, 30, row => row.review_date);
    if (rows.some(row => !/^\d{4}-\d{2}-\d{2}$/.test(row.review_date)
      || [row.real_profit_loss, row.suggested_stake, row.actual_stake, row.budget_usage_rate, row.max_single_ticket_loss].some(value => !Number.isFinite(value)))) throw new Error('日报金额或日期格式不正确');
    return rows;
  }, []);
  const fetchPlayTypes = useCallback(async () => {
    const response = await api.reviews.playTypeWinRate(30);
    if (!Array.isArray(response.data) || response.data.some(row => !row || typeof row.play_type !== 'string' || typeof row.settle_date !== 'string'
      || !Number.isFinite(row.win_rate) || row.win_rate < 0 || row.win_rate > 1
      || !Number.isSafeInteger(row.total) || row.total < 0 || !Number.isSafeInteger(row.wins) || row.wins < 0 || row.wins > row.total)) throw new Error('玩法统计格式不正确');
    return response.data;
  }, []);
  const reviewResource = useReadOnlyResource(fetchReviews, 30_000, false);
  const playResource = useReadOnlyResource(fetchPlayTypes, 30_000, false);
  const reviews = reviewResource.data ?? [];
  const playTypeData = playResource.data ?? [];
  const loading = reviewResource.loading;
  const [expandedDate, setExpandedDate] = useState<string | null>(null);

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
            fontWeight: 600,
          },
          labelLine: {
            length: 22,
            length2: 36,
            lineStyle: { opacity: 0.4 },
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


  return (
    <div>
      <ReadEvidenceStatus resource={reviewResource} label="刷新日报" note="最近最多30份归档日报；手动刷新" />
      {/* Charts */}
      {reviewResource.data !== null && (
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

      <ReadEvidenceStatus resource={playResource} label="刷新玩法统计" note="最近30天玩法统计，独立于日报归档" />
      {playResource.data !== null && <PlayTypeWinRateChart data={playTypeData} loading={playResource.loading} />}

      {reviewResource.data !== null && (reviews.length ? (
        <Card style={{ marginTop: '16px' }}>
          <ReviewDateIndex
            dates={reviews.map((review) => review.review_date)}
            selectedDate={expandedDate}
            onSelect={setExpandedDate}
          />
        </Card>
      ) : (
        <EmptyState title="暂无日报数据" description="官方赛果与相关票据结算完成后将自动生成。" />
      ))}
      {expandedDate && reviews.some(review => review.review_date === expandedDate) && (
        <Card key={expandedDate} title={`${expandedDate} 日报详情`} style={{ marginTop: '16px' }}>
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
                <ReportResearchSummary sourceType="post_daily" sourceRef={review.review_date} />
                <AutomaticReportArchivePanel sourceType="post_daily" sourceRef={review.review_date} />
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
  const fetchReviews = useCallback(async () => {
    const response = await api.reviews.weekly(12);
    const rows = checkedRows(response.reviews, 12, row => row.id);
    if (rows.some(row => !Number.isSafeInteger(row.id) || row.id <= 0 || typeof row.week_start !== 'string')) throw new Error('周报日期格式不正确');
    return rows;
  }, []);
  const resource = useReadOnlyResource(fetchReviews, 30_000, false);
  const reviews = resource.data ?? [];
  const loading = resource.loading;
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const columns: Column<WeeklyReview>[] = [
    { key: 'week_start', title: '周开始' },
    { key: 'week_end', title: '周结束' },
    { key: 'created_at', title: '生成时间', render: (v) => formatTimestamp(v) },
    { key: 'actions', title: '查看', render: (_value, row) => <button type="button" aria-label={`查看周报 ${row.week_start}`} aria-expanded={expandedId === row.id} onClick={() => setExpandedId(expandedId === row.id ? null : row.id)}>查看周报</button> },
  ];

  return (
    <>
      <ReadEvidenceStatus resource={resource} label="刷新周报" note="最近最多12份归档；手动刷新" />
      <DataTable columns={columns} rows={reviews} loading={loading} emptyText={resource.error && !resource.data ? "周报读取失败，请刷新" : "暂无周报数据"}
        rowKey={(r) => String(r.id)} />
      {expandedId != null && (() => {
        const review = reviews.find((item) => item.id === expandedId);
        return review ? <Card key={review.id} title={`${review.week_start} 至 ${review.week_end} 周报详情`} style={{ marginTop: '16px' }}>
          <ReportResearchSummary sourceType="post_weekly" sourceRef={review.week_start} />
          <AutomaticReportArchivePanel sourceType="post_weekly" sourceRef={review.week_start} />
        </Card> : null;
      })()}
    </>
  );
}

// ---- Monthly Reviews Tab ----
function MonthlyReviewsTab() {
  const fetchReviews = useCallback(async () => {
    const response = await api.reviews.monthly(12);
    const rows = checkedRows(response.reviews, 12, row => row.id);
    if (rows.some(row => !Number.isSafeInteger(row.id) || row.id <= 0 || typeof row.review_month !== 'string')) throw new Error('月报日期格式不正确');
    return rows;
  }, []);
  const resource = useReadOnlyResource(fetchReviews, 30_000, false);
  const reviews = resource.data ?? [];
  const loading = resource.loading;
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const columns: Column<MonthlyReview>[] = [
    { key: 'review_month', title: '月份' },
    { key: 'created_at', title: '生成时间', render: (v) => formatTimestamp(v) },
    { key: 'actions', title: '查看', render: (_value, row) => <button type="button" aria-label={`查看月报 ${row.review_month}`} aria-expanded={expandedId === row.id} onClick={() => setExpandedId(expandedId === row.id ? null : row.id)}>查看月报</button> },
  ];

  return (
    <>
      <ReadEvidenceStatus resource={resource} label="刷新月报" note="最近最多12份归档；手动刷新" />
      <DataTable columns={columns} rows={reviews} loading={loading} emptyText={resource.error && !resource.data ? "月报读取失败，请刷新" : "暂无月报数据"}
        rowKey={(r) => String(r.id)} />
      {expandedId != null && (() => {
        const review = reviews.find((item) => item.id === expandedId);
        return review ? <Card key={review.id} title={`${String(review.review_month ?? review.month ?? review.id)} 月报详情`} style={{ marginTop: '16px' }}>
          <ReportResearchSummary sourceType="post_monthly" sourceRef={review.review_month} />
          <AutomaticReportArchivePanel sourceType="post_monthly" sourceRef={review.review_month} />
        </Card> : null;
      })()}
    </>
  );
}

// ---- Settlements Tab ----
function SettlementsTab() {
  const [date, setDate] = useState(shanghaiToday);
  return <div>
    <div className="be-toolbar">
      <label>结算日期<input type="date" value={date} onChange={e => setDate(e.target.value)} /></label>
    </div>
    <SettlementQuery key={date} date={date} />
  </div>;
}

function SettlementQuery({ date }: { date: string }) {
  const fetchSettlements = useCallback(async () => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) throw new Error('请选择有效结算日期');
    const response = await api.settlements.list({ date, limit: 100 });
    const rows = checkedRows(response.settlements, 100, row => row.id);
    if (rows.some(row => !Number.isSafeInteger(row.id) || row.id <= 0 || [row.stake_amount, row.prize_amount, row.profit_loss].some(value => !Number.isFinite(value)))) throw new Error('结算金额格式不正确');
    return rows;
  }, [date]);
  const resource = useReadOnlyResource(fetchSettlements, 30_000, false);
  const settlements = resource.data ?? [];
  const loading = resource.loading;

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


  return (
    <div>
      <ReadEvidenceStatus resource={resource} label="刷新结算记录" note={`${date} · 当前返回 ${settlements.length} 笔 / 最多 100 笔；非全日汇总，金额仅合计当前返回记录`} />
      {settlements.length > 0 && (
        <Card style={{ marginBottom: '16px', display: 'flex', gap: '32px' }}>
          <div>
            <div className="fqp-label">当前记录投入</div>
            <div className="fqp-mono" style={{ fontSize: '18px', fontWeight: 700 }}>¥{totalStake.toFixed(2)}</div>
          </div>
          <div>
            <div className="fqp-label">当前记录净盈亏</div>
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
          emptyText={resource.error && !resource.data ? `${date} 结算读取失败，请刷新` : `${date} 暂无结算记录`}
          rowKey={(r) => String(r.id)}
        />
      </Card>
    </div>
  );
}

// ---- Error Analysis Tab ----
function ErrorAnalysisTab() {
  const fetchErrors = useCallback(async () => {
    const response = await api.errorAnalysis.list({ limit: 100 });
    return checkedRows(response.errors, 100, row => row.id);
  }, []);
  const fetchSummary = useCallback(async () => {
    const response = await api.errorAnalysis.summary(7);
    if (response.errors != null && (!Array.isArray(response.errors) || response.errors.some(row => !Number.isSafeInteger(row.count) || row.count < 0))) throw new Error('错因摘要格式不正确');
    return response;
  }, []);
  const listResource = useReadOnlyResource(fetchErrors, 30_000, false);
  const summaryResource = useReadOnlyResource(fetchSummary, 30_000, false);
  const errors = listResource.data ?? [];
  const summary = summaryResource.data;
  const loading = listResource.loading;

  const columns: Column<ErrorAnalysis>[] = [
    { key: 'match_id', title: '比赛', render: (v) => <a className="fqp-mono" href={`#/matches/${String(v)}`}>#{String(v)}</a> },
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


  return (
    <div>
      <ReadEvidenceStatus resource={listResource} label="刷新错因列表" note="最近最多100条记录；可从比赛编号查看证据" />
      <ReadEvidenceStatus resource={summaryResource} label="刷新错因摘要" note="近7天摘要，独立于有限列表" />
      {/* Summary */}
      {summary?.errors && summary.errors.length > 0 && (
        <Card title="近7天错因分布" style={{ marginBottom: '16px' }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px' }}>
            {summary.errors.map((e) => (
              <div
                key={e.error_type}
                style={{
                  padding: '8px 16px',
                  background: 'var(--fqp-panel)',
                  borderRadius: 'var(--fqp-radius-sm)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
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
          emptyText={listResource.error && !listResource.data ? "错因列表读取失败，请刷新" : "暂无错因分析数据"}
          rowKey={(r) => String(r.id)}
        />
      </Card>
    </div>
  );
}
