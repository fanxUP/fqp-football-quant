import type { ReactNode } from 'react';

interface PageHeaderProps {
  title: string;
  lastUpdated?: string;
  actions?: ReactNode;
}

export default function PageHeader({ title, lastUpdated, actions }: PageHeaderProps) {
  return (
    <div className="fqp-page-header">
      <div>
        <h1 className="fqp-page-title">{title}</h1>
        {lastUpdated && <div className="fqp-page-subtitle">最后更新: {lastUpdated}</div>}
      </div>
      {actions && <div style={{ display: 'flex', gap: '8px' }}>{actions}</div>}
    </div>
  );
}
