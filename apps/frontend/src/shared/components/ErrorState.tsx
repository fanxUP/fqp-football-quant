interface ErrorStateProps {
  message: string;
  onRetry?: () => void;
}

export default function ErrorState({ message, onRetry }: ErrorStateProps) {
  return (
    <div className="fqp-empty-state">
      <div className="fqp-empty-icon">⚠️</div>
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
