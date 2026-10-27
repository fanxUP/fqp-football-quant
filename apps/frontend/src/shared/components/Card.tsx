import type { ReactNode, MouseEvent, CSSProperties } from 'react';

interface CardProps {
  title?: string;
  subtitle?: string;
  children: ReactNode;
  className?: string;
  action?: ReactNode;
  onClick?: (e: MouseEvent) => void;
  style?: CSSProperties;
  /** Optional short fade, capped to avoid hiding data behind long delays. */
  entranceDelay?: number;
}

export default function Card({ title, subtitle, children, className = '', action, onClick, style, entranceDelay }: CardProps) {
  return (
    <div
      className={`fqp-card ${className}`}
      onClick={onClick}
      data-interactive={onClick ? 'true' : undefined}
      style={{
        padding: 'var(--fqp-card-padding)',
        cursor: onClick ? 'pointer' : undefined,
        animation: entranceDelay !== undefined ? `fqpSurfaceEnter .18s ease ${Math.min(Math.max(entranceDelay, 0), 180)}ms backwards` : undefined,
        ...style,
      }}
    >
      {(title || subtitle || action) && (
        <div className="fqp-card-heading">
          {(title || subtitle) && <div>
            {title && <h3>{title}</h3>}
            {subtitle && <p>{subtitle}</p>}
          </div>}
          {action}
        </div>
      )}
      {children}
    </div>
  );
}
