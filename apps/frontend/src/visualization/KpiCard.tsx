/** KPI card with trend indicators and optional entrance animation. */

import { useEffect, useState } from 'react';
import type { KpiData } from './chartTypes';

const STATUS_COLORS: Record<string, string> = {
  success: 'var(--fqp-success)',
  danger: 'var(--fqp-red-neon)',
  warning: 'var(--fqp-warning)',
  neutral: 'var(--fqp-text-muted)',
};

const TREND_ICONS: Record<string, string> = {
  up: '↑',
  down: '↓',
  flat: '→',
};

const TREND_COLORS: Record<string, string> = {
  up: 'var(--fqp-success)',
  down: 'var(--fqp-red-neon)',
  flat: 'var(--fqp-text-muted)',
};

interface KpiCardProps extends KpiData {
  entranceDelay?: number;
  /** Display value with count-up animation from 0 */
  animate?: boolean;
}

function CountUp({ value, duration = 600 }: { value: number; duration?: number }) {
  const [display, setDisplay] = useState(0);
  useEffect(() => {
    if (value <= 0) { setDisplay(0); return; }
    const start = performance.now();
    let raf: number;
    const animate = (now: number) => {
      const p = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - p, 3);
      setDisplay(Math.round(value * eased));
      if (p < 1) raf = requestAnimationFrame(animate);
    };
    raf = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(raf);
  }, [value, duration]);
  return <span>{display.toLocaleString()}</span>;
}

export default function KpiCard({
  title,
  value,
  unit,
  trend,
  trendValue,
  status = 'neutral',
  icon,
  loading,
  entranceDelay = 0,
  animate = false,
}: KpiCardProps) {
  const statusColor = STATUS_COLORS[status] || STATUS_COLORS.neutral;

  const content = (
    <div className="fqp-stat-card" style={{ padding: 0 }}>
      <div
        className="fqp-stat-value"
        style={{ color: status !== 'neutral' ? statusColor : undefined }}
      >
        {loading ? (
          <div
            className="fqp-skeleton"
            style={{ width: '60%', height: 32, borderRadius: 6, display: 'inline-block' }}
          />
        ) : animate && typeof value === 'number' ? (
          <><CountUp value={value} />{unit || ''}</>
        ) : (
          <>{typeof value === 'number' ? value.toLocaleString() : value}{unit || ''}</>
        )}
      </div>
      <div className="fqp-stat-sub">
        {icon && <span style={{ marginRight: 4 }}>{icon}</span>}
        {title}
        {trend && !loading && (
          <span
            style={{
              marginLeft: 8,
              color: TREND_COLORS[trend],
              fontSize: 12,
              fontWeight: 600,
            }}
          >
            {TREND_ICONS[trend]}
            {trendValue != null && `${Math.abs(trendValue).toFixed(1)}%`}
          </span>
        )}
      </div>
    </div>
  );

  if (entranceDelay > 0) {
    return (
      <div
        style={{
          animation: 'fqpCardEnter 0.4s ease both',
          animationDelay: `${entranceDelay}ms`,
        }}
      >
        {content}
      </div>
    );
  }
  return content;
}
