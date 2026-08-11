import Card from '../../shared/components/Card';
import StatusBadge from '../../shared/components/StatusBadge';
import type { NewsIntelligenceOverview } from './types';

interface NewsScreeningStatusProps {
  overview: NewsIntelligenceOverview | null;
  formatTime: (value: string | null) => string;
}

export default function NewsScreeningStatus({ overview, formatTime }: NewsScreeningStatusProps) {
  const ready = overview?.newsAgentReady ?? false;
  return (
    <Card title="AI 筛选链路" className="news-intelligence-screening">
      <div className="news-intelligence-event-heading">
        <StatusBadge
          status={ready ? 'ok' : 'warning'}
          label={ready ? 'AI 筛选 Agent 已就绪' : 'AI 筛选 Agent 未就绪'}
          dot
        />
        <strong>{ready ? '模型失败时自动回退规则筛选' : '当前使用确定性规则筛选'}</strong>
      </div>
      <div className="news-intelligence-meta">
        已筛选 {overview?.screeningCount ?? 0} 篇 · 模型筛选 {overview?.aiScreeningCount ?? 0} 篇 ·
        待人工核验 {overview?.pendingReviewCount ?? 0} 项 · 回退 {overview?.modelFailureCount ?? 0} 次
      </div>
      <div className="news-intelligence-meta">
        最近模型调用 {formatTime(overview?.lastModelInvocationAt ?? null)}；模型不修改正式预测、推荐、投注或风控。
      </div>
    </Card>
  );
}
