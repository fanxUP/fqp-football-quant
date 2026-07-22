import type { AgentDailyDecision } from '../../core/types';
import EmptyState from '../../shared/components/EmptyState';

const STATUS_META = {
  purchased: { label: '正式推荐已购买', color: 'var(--fqp-success, #16a34a)' },
  abstained: { label: '已放弃', color: 'var(--fqp-warning, #d97706)' },
  failed: { label: '执行失败', color: 'var(--fqp-danger, #dc2626)' },
};

const OBSERVATION_META = {
  label: '竞赛观察票',
  color: 'var(--fqp-warning, #d97706)',
};

function money(value: number): string {
  return `¥${value.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export default function AgentDecisionTimeline({ decisions }: { decisions: AgentDailyDecision[] }) {
  if (decisions.length === 0) {
    return (
      <EmptyState
        icon="决策"
        title="暂无 Agent 每日决策"
        description="北京时间 16:00 执行后，会记录购买或放弃原因"
      />
    );
  }

  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="fqp-table" style={{ width: '100%', fontSize: 13 }}>
        <thead>
          <tr>
            <th>日期</th>
            <th>决策</th>
            <th style={{ textAlign: 'right' }}>虚拟投入</th>
            <th style={{ textAlign: 'right' }}>未用额度</th>
            <th>依据</th>
          </tr>
        </thead>
        <tbody>
          {decisions.map((decision) => {
            const meta = decision.status === 'purchased' && decision.decisionType === 'observation'
              ? OBSERVATION_META
              : STATUS_META[decision.status];
            return (
              <tr key={decision.decisionDate}>
                <td className="fqp-mono">{decision.decisionDate}</td>
                <td style={{ color: meta.color, fontWeight: 700 }}>{meta.label}</td>
                <td className="fqp-mono" style={{ textAlign: 'right' }}>{money(decision.totalStake)}</td>
                <td className="fqp-mono" style={{ textAlign: 'right' }}>{money(decision.unusedBudget)}</td>
                <td>{decision.reason}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
