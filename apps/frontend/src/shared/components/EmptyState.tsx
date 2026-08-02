import { useEffect, useState, type ReactNode } from 'react';
import { useLanguage } from '../../app/LanguageContext';

interface EmptyStateProps {
  icon?: string;
  title: string;
  description?: string;
  action?: ReactNode;
}

export default function EmptyState({ icon = '📭', title, description, action }: EmptyStateProps) {
  const { translate } = useLanguage();
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    requestAnimationFrame(() => setMounted(true));
  }, []);

  return (
    <div className="fqp-empty-state">
      <div
        className="fqp-empty-icon"
        style={{
          opacity: mounted ? 0.3 : 0,
          transform: mounted ? 'scale(1)' : 'scale(0)',
          transition: 'opacity 0.4s cubic-bezier(0.34,1.56,0.64,1), transform 0.4s cubic-bezier(0.34,1.56,0.64,1)',
        }}
      >
        {icon}
      </div>
      <div
        className="fqp-empty-title"
        style={{
          opacity: mounted ? 1 : 0,
          transform: mounted ? 'translateY(0)' : 'translateY(8px)',
          transition: 'opacity 0.3s ease 0.1s, transform 0.3s ease 0.1s',
        }}
      >
        {translate(title)}
      </div>
      {description && (
        <div
          className="fqp-empty-desc"
          style={{
            opacity: mounted ? 1 : 0,
            transform: mounted ? 'translateY(0)' : 'translateY(8px)',
            transition: 'opacity 0.3s ease 0.2s, transform 0.3s ease 0.2s',
          }}
        >
          {translate(description)}
        </div>
      )}
      {action && <div style={{ marginTop: '20px' }}>{action}</div>}
    </div>
  );
}
