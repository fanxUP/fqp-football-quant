import { useEffect, useState } from 'react';
import { useLanguage } from '../../app/LanguageContext';

interface ErrorStateProps {
  message: string;
  onRetry?: () => void;
}

export default function ErrorState({ message, onRetry }: ErrorStateProps) {
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
          animation: mounted ? 'fqpShake 0.5s ease both' : undefined,
        }}
      >
        ⚠️
      </div>
      <div className="fqp-empty-title" style={{ color: 'var(--fqp-red-neon)' }}>
        {translate('加载失败')}
      </div>
      <div className="fqp-empty-desc">{translate(message)}</div>
      {onRetry && (
        <button className="fqp-btn fqp-btn-danger" onClick={onRetry} style={{ marginTop: '20px' }}>
          {translate('重试')}
        </button>
      )}
    </div>
  );
}
