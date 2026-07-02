import type { ReactNode, MouseEvent } from 'react';

interface CardProps {
  title?: string;
  children: ReactNode;
  className?: string;
  action?: ReactNode;
  onClick?: (e: MouseEvent) => void;
  style?: Record<string, string | number>;
}

export default function Card({ title, children, className = '', action, onClick, style }: CardProps) {
  return (
    <div
      className={`fqp-card ${className}`}
      onClick={onClick}
      style={{ padding: '20px 24px', cursor: onClick ? 'pointer' : undefined, ...style }}
    >
      {(title || action) && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: title ? '12px' : 0,
          }}
        >
          {title && (
            <h3 style={{ color: 'var(--fqp-text)', fontSize: '14px', margin: 0, fontWeight: 600 }}>
              {title}
            </h3>
          )}
          {action}
        </div>
      )}
      {children}
    </div>
  );
}
