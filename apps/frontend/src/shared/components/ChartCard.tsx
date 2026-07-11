import { useEffect, useRef } from 'react';
import * as echarts from 'echarts';
import Card from './Card';
import { useTheme } from '../../app/ThemeContext';

interface ChartCardProps {
  title: string;
  subtitle?: string;
  option: Record<string, unknown>;
  height?: number;
  loading?: boolean;
  empty?: boolean;
  emptyReason?: string;
  error?: string | null;
  updatedAt?: string;
}

export default function ChartCard({
  title,
  subtitle,
  option,
  height = 300,
  loading = false,
  empty = false,
  emptyReason,
  error,
  updatedAt,
}: ChartCardProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<echarts.ECharts | null>(null);
  const { theme } = useTheme();

  useEffect(() => {
    if (!chartRef.current) return;

    const textColor = theme === 'dark' ? '#C4C4CC' : '#4B5563';

    const themedOption = {
      backgroundColor: 'transparent',
      textStyle: { color: textColor, fontSize: 14 },
      legend: { textStyle: { color: textColor, fontSize: 14 } },
      ...option,
    };

    const inst = echarts.init(chartRef.current, undefined, { renderer: 'canvas' });
    inst.setOption(themedOption);
    instanceRef.current = inst;

    const handleResize = () => inst.resize();
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      inst.dispose();
    };
  }, [option, theme]);

  // Determine what to render inside the card
  const renderBody = () => {
    if (loading) {
      return (
        <div
          role="status"
          aria-label="加载图表..."
          style={{
            height,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'var(--fqp-text-muted)',
          }}
        >
          <div
            className="fqp-skeleton"
            style={{ width: '90%', height: '70%', borderRadius: 'var(--fqp-radius-sm)' }}
          />
        </div>
      );
    }
    if (error) {
      return (
        <div
          style={{
            height,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'var(--fqp-red-neon)',
            gap: 8,
          }}
        >
          <span style={{ fontSize: 28 }}>⚠️</span>
          <span style={{ fontSize: 13 }}>{error}</span>
        </div>
      );
    }
    if (empty) {
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
          <span style={{ fontSize: 28, opacity: 0.5 }}>📊</span>
          <span style={{ fontSize: 13 }}>{emptyReason || '暂无数据'}</span>
        </div>
      );
    }
    return (
      <div
        ref={chartRef}
        className="fqp-anim-chartReveal"
        style={{ width: '100%', height }}
      />
    );
  };

  return (
    <Card>
      {/* Header: title + subtitle + updatedAt */}
      {(title || subtitle || updatedAt) && (
        <div
          style={{
            display: 'flex',
            alignItems: 'baseline',
            justifyContent: 'space-between',
            marginBottom: '12px',
            gap: 8,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
            {title && (
              <h3 style={{ color: 'var(--fqp-text)', fontSize: '16px', margin: 0, fontWeight: 600 }}>
                {title}
              </h3>
            )}
            {subtitle && (
              <span style={{ fontSize: '12px', color: 'var(--fqp-text-muted)' }}>
                {subtitle}
              </span>
            )}
          </div>
          {updatedAt && (
            <span style={{ fontSize: '11px', color: 'var(--fqp-text-muted)', whiteSpace: 'nowrap' }}>
              更新: {updatedAt}
            </span>
          )}
        </div>
      )}
      {renderBody()}
    </Card>
  );
}
