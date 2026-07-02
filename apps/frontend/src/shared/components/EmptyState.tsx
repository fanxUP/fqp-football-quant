import type { ReactNode } from 'react';

interface EmptyStateProps {
  icon?: string;
  title: string;
  description?: string;
  action?: ReactNode;
}

export default function EmptyState({ icon = '📭', title, description, action }: EmptyStateProps) {
  return (
    <div className="fqp-empty-state">
      <div className="fqp-empty-icon">{icon}</div>
      <div className="fqp-empty-title">{title}</div>
      {description && <div className="fqp-empty-desc">{description}</div>}
      {action && <div style={{ marginTop: '20px' }}>{action}</div>}
    </div>
  );
}
