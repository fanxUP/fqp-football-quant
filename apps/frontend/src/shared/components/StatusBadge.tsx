import { useEffect, useState } from 'react';
import { useLanguage } from '../../app/LanguageContext';

type StatusType = 'ok' | 'warning' | 'error' | 'info' | 'disabled';

interface StatusBadgeProps {
  status: StatusType;
  label: string;
  dot?: boolean;
}

export default function StatusBadge({ status, label, dot = false }: StatusBadgeProps) {
  const { translate } = useLanguage();
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    requestAnimationFrame(() => setMounted(true));
  }, []);

  const isAlert = dot && (status === 'warning' || status === 'error');

  return (
    <span
      className={`fqp-badge fqp-badge-${status}`}
      style={{
        animation: mounted ? 'fqpBadgePop 0.3s ease both' : undefined,
      }}
    >
      {dot && (
        <span
          className={`fqp-status-dot fqp-status-dot-${status}`}
          style={
            isAlert
              ? { animation: 'fqpNotificationDot 2s infinite' }
              : undefined
          }
        />
      )}
      {translate(label)}
    </span>
  );
}
