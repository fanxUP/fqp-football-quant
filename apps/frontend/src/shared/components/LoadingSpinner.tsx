interface LoadingSpinnerProps {
  text?: string;
  size?: 'sm' | 'md' | 'lg';
}

const sizes: Record<string, { w: number; h: number }> = {
  sm: { w: 18, h: 18 },
  md: { w: 24, h: 24 },
  lg: { w: 40, h: 40 },
};

export default function LoadingSpinner({ text, size = 'md' }: LoadingSpinnerProps) {
  const dims = sizes[size];
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '40px 20px',
        gap: '12px',
      }}
    >
      <div className="fqp-spinner" style={{ width: dims.w, height: dims.h }} />
      {text && <span style={{ color: 'var(--fqp-text-muted)', fontSize: '13px' }}>{text}</span>}
    </div>
  );
}
