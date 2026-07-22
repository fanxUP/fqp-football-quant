import { useEffect, useState, type ReactNode } from 'react';

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  lastUpdated?: string;
  actions?: ReactNode;
}

export default function PageHeader({ title, subtitle, lastUpdated, actions }: PageHeaderProps) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    requestAnimationFrame(() => setMounted(true));
  }, []);

  return (
    <div className="fqp-page-header">
      <div>
        <h1
          className="fqp-page-title"
          style={{
            opacity: mounted ? 1 : 0,
            transform: mounted ? 'translateY(0)' : 'translateY(8px)',
            transition: 'opacity 0.4s ease, transform 0.4s ease',
          }}
        >
          {title}
        </h1>
        {(subtitle || lastUpdated) && (
          <div
            className="fqp-page-subtitle"
            style={{
              opacity: mounted ? 1 : 0,
              transform: mounted ? 'translateY(0)' : 'translateY(6px)',
              transition: 'opacity 0.4s ease 0.1s, transform 0.4s ease 0.1s',
            }}
          >
            {subtitle}
            {subtitle && lastUpdated ? ' · ' : ''}
            {lastUpdated ? `最后更新: ${lastUpdated}` : ''}
          </div>
        )}
      </div>
      {actions && (
        <div
          style={{
            display: 'flex',
            gap: '8px',
            opacity: mounted ? 1 : 0,
            transform: mounted ? 'translateX(0)' : 'translateX(24px)',
            transition: 'opacity 0.3s ease 0.2s, transform 0.3s ease 0.2s',
          }}
        >
          {actions}
        </div>
      )}
    </div>
  );
}
