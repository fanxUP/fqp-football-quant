type StatusType = 'ok' | 'warning' | 'error' | 'info' | 'disabled';

interface StatusBadgeProps {
  status: StatusType;
  label: string;
  dot?: boolean;
}

export default function StatusBadge({ status, label, dot = false }: StatusBadgeProps) {
  return (
    <span className={`fqp-badge fqp-badge-${status}`}>
      {dot && <span className={`fqp-status-dot fqp-status-dot-${status}`} />}
      {label}
    </span>
  );
}
