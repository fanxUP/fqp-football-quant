/** Risk level badge with optional progress bar. */

import type { RiskBadgeData, RiskLevel } from './chartTypes';

const LEVEL_CONFIG: Record<RiskLevel, { label: string; color: string; bg: string }> = {
  low:         { label: '低风险',    color: '#16C784', bg: 'rgba(22,199,132,0.12)' },
  medium:      { label: '中风险',    color: '#FFB020', bg: 'rgba(255,176,32,0.12)' },
  high:        { label: '高风险',    color: '#F7931A', bg: 'rgba(247,147,26,0.12)' },
  critical:    { label: '严重风险',  color: '#FF3B3B', bg: 'rgba(255,59,59,0.12)' },
};

interface RiskBadgeProps extends RiskBadgeData {
  size?: 'sm' | 'md';
}

export default function RiskBadge({ level, score, showBar, label, size = 'sm' }: RiskBadgeProps) {
  const cfg = LEVEL_CONFIG[level] || LEVEL_CONFIG.low;
  const displayLabel = label || cfg.label;

  return (
    <div style={{ display: 'inline-flex', flexDirection: 'column', gap: 4 }}>
      <span
        className="fqp-anim-popIn"
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 5,
          padding: size === 'sm' ? '2px 10px' : '4px 14px',
          borderRadius: 20,
          fontSize: size === 'sm' ? 11 : 13,
          fontWeight: 600,
          color: cfg.color,
          background: cfg.bg,
          border: `1px solid ${cfg.color}33`,
        }}
      >
        <span style={{
          width: 6, height: 6,
          borderRadius: '50%',
          background: cfg.color,
          display: 'inline-block',
        }} />
        {displayLabel}
        {score != null && ` (${score})`}
      </span>
      {showBar && score != null && (
        <div style={{
          width: '100%',
          height: 4,
          background: 'var(--fqp-hover-bg)',
          borderRadius: 2,
          overflow: 'hidden',
        }}>
          <div style={{
            width: `${Math.min(score, 100)}%`,
            height: '100%',
            background: cfg.color,
            borderRadius: 2,
            transition: 'width 0.6s ease',
          }} />
        </div>
      )}
    </div>
  );
}
