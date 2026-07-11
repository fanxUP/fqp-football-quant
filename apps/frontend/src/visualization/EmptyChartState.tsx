/** Empty / no-data placeholder for chart panels. */

interface EmptyChartStateProps {
  icon?: string;
  title?: string;
  description?: string;
  height?: number;
}

export default function EmptyChartState({
  icon = '📊',
  title = '暂无数据',
  description,
  height = 260,
}: EmptyChartStateProps) {
  return (
    <div
      style={{
        height,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        color: 'var(--fqp-text-muted)',
        gap: 8,
      }}
    >
      <span style={{ fontSize: 32, opacity: 0.5 }}>{icon}</span>
      <div style={{ fontSize: 14, fontWeight: 600 }}>{title}</div>
      {description && (
        <div style={{ fontSize: 12, opacity: 0.7, textAlign: 'center', maxWidth: 280 }}>
          {description}
        </div>
      )}
    </div>
  );
}
