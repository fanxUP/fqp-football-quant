import { api, type ReportResearchBreakdownRow, type ReportResearchSnapshot } from '../../core/apiClient';
import useManualEvidence from '../useManualEvidence';
import ReadEvidenceStatus from '../ReadEvidenceStatus';
import '../BusinessEvidence.css';
import ReportPerformanceSummary from './ReportPerformanceSummary';
import './AutomaticReportArchivePanel.css';

type ReportSourceType = 'post_daily' | 'post_weekly' | 'post_monthly';

function numeric(value: unknown): number | null {
  if (value == null || (typeof value !== 'number' && typeof value !== 'string') || (typeof value === 'string' && !value.trim())) return null;
  const amount = Number(value);
  return Number.isFinite(amount) ? amount : null;
}
function count(value: number | undefined): string {
  return Number.isSafeInteger(value) && value! >= 0 ? String(value) : '—';
}
function percent(value: unknown): string {
  const amount = numeric(value);
  return amount === null ? '—' : `${(amount * 100).toFixed(2)}%`;
}
function currency(value: unknown, signed = false): string {
  const amount = numeric(value);
  return amount === null ? '—' : `${signed && amount > 0 ? '+' : ''}¥${amount.toFixed(2)}`;
}

function checkedReport(report: ReportResearchSnapshot | null, sourceType: ReportSourceType, sourceRef: string) {
  if (report === null) return { report };
  if (!report || report.sourceType !== sourceType || report.sourceRef !== sourceRef) throw new Error('复盘快照与所选期间不一致');
  for (const breakdown of [report.researchBreakdowns, report.performanceBreakdowns]) {
    if (breakdown && (!Array.isArray(breakdown.models) || !Array.isArray(breakdown.playTypes) || !Array.isArray(breakdown.leagues))) throw new Error('复盘分组格式不正确');
  }
  if ((report.errorAnalysis && !Array.isArray(report.errorAnalysis.byType)) || (report.strategySummary && (!Array.isArray(report.strategySummary.findings) || !Array.isArray(report.strategySummary.actions)))) throw new Error('复盘说明格式不正确');
  return { report };
}

function financeSnapshot(report: ReportResearchSnapshot): Record<string, number | string | null> {
  return report.dailyReview ?? report.aggregate ?? {};
}

function SignalBreakdown({ title, rows }: { title: string; rows: ReportResearchBreakdownRow[] }) {
  if (!rows.length) return null;
  return <section className="automatic-report-breakdown" aria-label={title}>
    <h4>{title}</h4>
    <ul>
      {rows.map((row) => <li key={row.key}>
        <strong>{row.key}</strong>
        <span>{count(row.signalCount)} 条信号 · {count(row.matchCount)} 场比赛</span>
        <span>平均 Edge {percent(row.averageEdge)} · 平均 EV {percent(row.averageEv)}</span>
      </li>)}
    </ul>
  </section>;
}

export default function ReportResearchSummary(props: { sourceType: ReportSourceType; sourceRef: string }) {
  return <ResearchQuery key={`${props.sourceType}:${props.sourceRef}`} {...props} />;
}

function ResearchQuery({ sourceType, sourceRef }: { sourceType: ReportSourceType; sourceRef: string }) {
  const resource = useManualEvidence(async () => checkedReport((await api.reportAutomation.snapshot(sourceType, sourceRef)).report, sourceType, sourceRef));
  const report = resource.data?.report;
  const status = <ReadEvidenceStatus resource={resource} label="刷新量化复盘指标" note={`${{ post_daily: '日报', post_weekly: '周报', post_monthly: '月报' }[sourceType]} · ${sourceRef} · 冻结快照，仅手动读取`} />;
  if (!resource.data) return <div className="be-page">{status}</div>;
  if (!report) return <div className="be-page">{status}<p className="automatic-report-archive-status">本期暂无冻结复盘快照</p></div>;
  if (!report.researchMetrics) return <div className="be-page">{status}<p className="automatic-report-archive-status">该历史报告未包含量化指标。</p></div>;

  const metrics = report.researchMetrics;
  const finance = financeSnapshot(report);
  const stake = finance.actualStake ?? finance.total_stake;
  const prize = finance.realPrize ?? finance.total_prize;
  const profitLoss = finance.realProfitLoss ?? finance.profit_loss;
  const roi = finance.realRoi ?? finance.roi;
  const profitAmount = numeric(profitLoss);
  const profitClass = profitAmount === null || profitAmount === 0 ? undefined : profitAmount < 0 ? 'automatic-report-profit-negative' : 'automatic-report-profit-positive';
  const cards = [
    ['实际投入', currency(stake)],
    ['实际返还', currency(prize)],
    ['实际盈亏', currency(profitLoss, true)],
    ['实际 ROI', percent(roi)],
    ['分析比赛', `${count(metrics.matchCount)} 场`],
    ['信号覆盖率', percent(metrics.signalCoverageRate)],
    ['证据覆盖率', percent(metrics.evidenceCoverageRate)],
    ['平均 Edge', percent(metrics.averageEdge)],
    ['平均 EV', percent(metrics.averageEv)],
  ] as const;

  return <section className="automatic-report-research be-page" aria-labelledby={`research-summary-${sourceType}-${sourceRef}`}>
    {status}
    <div className="automatic-report-research-heading">
      <h3 id={`research-summary-${sourceType}-${sourceRef}`}>量化复盘指标</h3>
      <p>后端冻结数据 · 不参与预测或投注决策</p>
    </div>
    {report.interpretationRequiresRefresh && Number(report.snapshotRevision) > 0 && (
      <p className="automatic-report-revision-note" role="note">
        该报告已完成第 {report.snapshotRevision} 次可追溯补跑；已归档的模型文字可能基于旧快照。
      </p>
    )}
    <dl className="automatic-report-research-grid">
      {cards.map(([label, value]) => <div key={label}>
        <dt>{label}</dt>
        <dd className={label === '实际盈亏' ? profitClass : undefined}>{value}</dd>
      </div>)}
    </dl>
    <ReportPerformanceSummary report={report} />
    {report.researchBreakdowns && <div className="automatic-report-breakdowns">
      <SignalBreakdown title="模型信号分布" rows={report.researchBreakdowns.models} />
      <SignalBreakdown title="玩法信号分布" rows={report.researchBreakdowns.playTypes} />
      <SignalBreakdown title="联赛信号分布" rows={report.researchBreakdowns.leagues} />
    </div>}
  </section>;
}
