import { useEffect, useState } from 'react';

interface ErrorStateProps {
  message: string;
  onRetry?: () => void;
}

export default function ErrorState({ message, onRetry }: ErrorStateProps) {
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
        加载失败
      </div>
      <div className="fqp-empty-desc">{message}</div>
      {onRetry && (
        <button className="fqp-btn fqp-btn-danger" onClick={onRetry} style={{ marginTop: '20px' }}>
          重试
        </button>
      )}
    </div>
  );
}
