import { useEffect, useState, type ReactNode, type MouseEvent } from 'react';

interface CardProps {
  title?: string;
  children: ReactNode;
  className?: string;
  action?: ReactNode;
  onClick?: (e: MouseEvent) => void;
  style?: Record<string, string | number>;
  /** Staggered entrance delay in milliseconds */
  entranceDelay?: number;
}

export default function Card({ title, children, className = '', action, onClick, style, entranceDelay }: CardProps) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setMounted(true), entranceDelay ?? 0);
    return () => clearTimeout(t);
  }, [entranceDelay]);

  return (
    <div
      className={`fqp-card ${className}`}
      onClick={onClick}
      style={{
        padding: '20px 24px',
        cursor: onClick ? 'pointer' : undefined,
        opacity: entranceDelay !== undefined ? (mounted ? 1 : 0) : undefined,
        transform: entranceDelay !== undefined ? (mounted ? 'translateY(0)' : 'translateY(16px)') : undefined,
        transition: entranceDelay !== undefined ? 'opacity 0.4s ease, transform 0.4s ease' : undefined,
        ...style,
      }}
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
            <h3 style={{ color: 'var(--fqp-text)', fontSize: '16px', margin: 0, fontWeight: 600 }}>
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
