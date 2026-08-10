import { useEffect, useState } from 'react';
import { api, type ReportResearchBreakdownRow, type ReportResearchSnapshot } from '../../core/apiClient';
import './AutomaticReportArchivePanel.css';

type ReportSourceType = 'post_daily' | 'post_weekly' | 'post_monthly';

function percent(value: number | null | undefined): string {
  return value == null ? '—' : `${(value * 100).toFixed(2)}%`;
}

function currency(value: unknown, signed = false): string {
  const amount = Number(value);
  if (!Number.isFinite(amount)) return '—';
  return `${signed && amount > 0 ? '+' : ''}¥${amount.toFixed(2)}`;
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
        <span>{row.signalCount} 条信号 · {row.matchCount} 场比赛</span>
        <span>平均 Edge {percent(row.averageEdge)} · 平均 EV {percent(row.averageEv)}</span>
      </li>)}
    </ul>
  </section>;
}

export default function ReportResearchSummary({
  sourceType, sourceRef,
}: { sourceType: ReportSourceType; sourceRef: string }) {
  const [report, setReport] = useState<ReportResearchSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setFailed(false);
    api.reportAutomation.snapshot(sourceType, sourceRef)
      .then((response) => { if (active) setReport(response.report); })
      .catch(() => { if (active) setFailed(true); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [sourceType, sourceRef]);

  if (loading) return <p className="automatic-report-archive-status" role="status">正在读取量化复盘指标…</p>;
  if (failed) return <p className="automatic-report-archive-status" role="alert">量化复盘指标读取失败，请稍后重试。</p>;
  if (!report?.researchMetrics) return <p className="automatic-report-archive-status">该历史报告未包含量化指标。</p>;

  const metrics = report.researchMetrics;
  const finance = financeSnapshot(report);
  const stake = finance.actualStake ?? finance.total_stake;
  const prize = finance.realPrize ?? finance.total_prize;
  const profitLoss = finance.realProfitLoss ?? finance.profit_loss;
  const roi = finance.realRoi ?? finance.roi;
  const cards = [
    ['实际投入', currency(stake)],
    ['实际返还', currency(prize)],
    ['实际盈亏', currency(profitLoss, true)],
    ['实际 ROI', percent(Number(roi))],
    ['分析比赛', `${metrics.matchCount} 场`],
    ['信号覆盖率', percent(metrics.signalCoverageRate)],
    ['证据覆盖率', percent(metrics.evidenceCoverageRate)],
    ['平均 Edge', percent(metrics.averageEdge)],
    ['平均 EV', percent(metrics.averageEv)],
  ] as const;

  return <section className="automatic-report-research" aria-labelledby={`research-summary-${sourceType}-${sourceRef}`}>
    <div className="automatic-report-research-heading">
      <h3 id={`research-summary-${sourceType}-${sourceRef}`}>量化复盘指标</h3>
      <p>后端冻结数据 · 不参与预测或投注决策</p>
    </div>
    <dl className="automatic-report-research-grid">
      {cards.map(([label, value]) => <div key={label}>
        <dt>{label}</dt>
        <dd className={label === '实际盈亏' ? 'automatic-report-profit' : undefined}>{value}</dd>
      </div>)}
    </dl>
    {report.researchBreakdowns && <div className="automatic-report-breakdowns">
      <SignalBreakdown title="模型信号分布" rows={report.researchBreakdowns.models} />
      <SignalBreakdown title="玩法信号分布" rows={report.researchBreakdowns.playTypes} />
      <SignalBreakdown title="联赛信号分布" rows={report.researchBreakdowns.leagues} />
    </div>}
  </section>;
}
