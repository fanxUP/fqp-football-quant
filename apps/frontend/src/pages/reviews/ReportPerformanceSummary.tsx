import type {
  ReportPerformanceBreakdownRow,
  ReportResearchSnapshot,
} from '../../core/apiClient';
import { modelNameLabel, playTypeLabel } from '../../shared/constants';

function percent(value: number | null | undefined, signed = false): string {
  if (value == null) return '—';
  return `${signed && value > 0 ? '+' : ''}${(value * 100).toFixed(2)}%`;
}

function decimal(value: number | null | undefined): string {
  return value == null ? '—' : value.toFixed(4);
}

function breakdownLabel(kind: 'model' | 'play' | 'league', key: string): string {
  if (kind === 'model') return modelNameLabel(key);
  if (kind === 'play') return playTypeLabel(key);
  return key;
}

function PerformanceBreakdown({
  title,
  kind,
  rows,
}: {
  title: string;
  kind: 'model' | 'play' | 'league';
  rows: ReportPerformanceBreakdownRow[];
}) {
  if (!rows.length) return null;
  return <section className="automatic-report-breakdown" aria-label={title}>
    <h4>{title}</h4>
    <ul>
      {rows.slice(0, 8).map((row) => <li key={row.key}>
        <strong>{breakdownLabel(kind, row.key)}</strong>
        <span>{row.correctCount}/{row.sampleCount} 命中 · {percent(row.hitRate)}</span>
        <span>CLV {percent(row.averageClv, true)} · 等额理论 ROI {percent(row.unitStakeRoi, true)}</span>
        <span>Brier {decimal(row.brierScore)} · Log Loss {decimal(row.logLoss)}</span>
      </li>)}
    </ul>
  </section>;
}

export default function ReportPerformanceSummary({ report }: { report: ReportResearchSnapshot }) {
  const metrics = report.performanceMetrics;
  if (!metrics) {
    return <p className="automatic-report-archive-status">该历史报告未包含真实赛果评价。</p>;
  }
  const cards = [
    ['可评估选择', `${metrics.sampleCount} 个`],
    ['命中率', percent(metrics.hitRate)],
    ['Brier Score', decimal(metrics.brierScore)],
    ['Log Loss', decimal(metrics.logLoss)],
    ['概率校准 ECE', percent(metrics.calibrationError)],
    ['平均 CLV', percent(metrics.averageClv, true)],
    ['临场模型 Edge', percent(metrics.averageClosingEdge, true)],
    ['等额理论 ROI', percent(metrics.unitStakeRoi, true)],
    ['最大连续失误', `${metrics.maxLosingStreak} 次`],
  ] as const;
  const evidence = report.evidenceSummary;
  const errors = report.errorAnalysis;
  const strategy = report.strategySummary;

  return <section className="automatic-report-performance" aria-label="真实赛果评价">
    <div className="automatic-report-subheading">
      <h4>真实赛果评价</h4>
      <p>按模型最高概率选择评估 · CLV 使用推荐时市场概率与休市去水概率</p>
    </div>
    <dl className="automatic-report-research-grid">
      {cards.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
    </dl>
    {report.performanceBreakdowns && <div className="automatic-report-breakdowns">
      <PerformanceBreakdown title="模型真实表现" kind="model" rows={report.performanceBreakdowns.models} />
      <PerformanceBreakdown title="玩法真实表现" kind="play" rows={report.performanceBreakdowns.playTypes} />
      <PerformanceBreakdown title="联赛真实表现" kind="league" rows={report.performanceBreakdowns.leagues} />
    </div>}
    {evidence && <div className="automatic-report-evidence-summary" role="note">
      <strong>证据完整度</strong>
      <span>赛前 {evidence.preMatchCount} 条 · 赛后 {evidence.postMatchCount} 条</span>
      <span>可靠新闻证据：{evidence.newsEvidenceCount} 条</span>
      <span>缺少外部资料：{evidence.missingMatchCount} 场</span>
    </div>}
    {errors && errors.byType.length > 0 && <section className="automatic-report-review-list" aria-label="主要错因">
      <h4>主要错因</h4>
      <ul>{errors.byType.slice(0, 5).map((item) => <li key={item.code}>
        <strong>{item.label} · {item.count} 次</strong><span>{item.suggestedAction}</span>
      </li>)}</ul>
    </section>}
    {strategy && <section className="automatic-report-review-list" aria-label="复盘结论与后续动作">
      <h4>复盘结论与后续动作</h4>
      <ul>
        {strategy.findings.map((item) => <li key={`finding-${item}`}>{item}</li>)}
        {strategy.actions.map((item) => <li key={`action-${item}`}>{item}</li>)}
      </ul>
      <p className="automatic-report-safety-notice">{strategy.safetyNotice}</p>
    </section>}
  </section>;
}
