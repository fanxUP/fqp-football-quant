import type { ReactNode } from 'react';
import Card from '../../shared/components/Card';
import './ChartFrame.css';

interface ChartFrameProps {
  title: string;
  subtitle?: string;
  updatedAt?: string;
  loading?: boolean;
  empty?: boolean;
  emptyReason?: string;
  error?: string | null;
  height?: number;
  controls?: ReactNode;
  children: ReactNode;
}

export default function ChartFrame({
  title,
  subtitle,
  updatedAt,
  loading = false,
  empty = false,
  emptyReason = '暂无数据',
  error,
  height = 300,
  controls,
  children,
}: ChartFrameProps) {
  let body = children;

  if (loading) {
    body = (
      <div className="chart-frame-state" style={{ minHeight: height }} role="status" aria-label="加载图表...">
        <div className="fqp-skeleton chart-frame-skeleton" />
        <span>图表数据加载中</span>
      </div>
    );
  } else if (error) {
    body = (
      <div className="chart-frame-state chart-frame-error" style={{ minHeight: height }} role="alert">
        <span aria-hidden="true">⚠️</span>
        <span>{error}</span>
      </div>
    );
  } else if (empty) {
    body = (
      <div className="chart-frame-state" style={{ minHeight: height }} role="status">
        <span className="chart-frame-empty-icon" aria-hidden="true">◌</span>
        <span>{emptyReason}</span>
      </div>
    );
  }

  return (
    <Card className="chart-frame">
      <header className="chart-frame-header">
        <div className="chart-frame-heading">
          <h3>{title}</h3>
          {subtitle && <p>{subtitle}</p>}
        </div>
        <div className="chart-frame-meta">
          {updatedAt && <span>更新 {updatedAt}</span>}
          {controls}
        </div>
      </header>
      <div className="chart-frame-body" aria-busy={loading}>
        {body}
      </div>
    </Card>
  );
}
