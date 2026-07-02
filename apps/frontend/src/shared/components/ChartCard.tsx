import { useEffect, useRef } from 'react';
import * as echarts from 'echarts';
import Card from './Card';
import { useTheme } from '../../app/ThemeContext';

interface ChartCardProps {
  title: string;
  option: Record<string, unknown>;
  height?: number;
  loading?: boolean;
}

export default function ChartCard({ title, option, height = 300, loading = false }: ChartCardProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<echarts.ECharts | null>(null);
  const { theme } = useTheme();

  useEffect(() => {
    if (!chartRef.current) return;

    const textColor = theme === 'dark' ? '#A1A1AA' : '#6B7280';

    const themedOption = {
      backgroundColor: 'transparent',
      textStyle: { color: textColor },
      legend: { textStyle: { color: textColor } },
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

  return (
    <Card title={title}>
      {loading ? (
        <div
          style={{
            height,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'var(--fqp-text-muted)',
          }}
        >
          加载图表...
        </div>
      ) : (
        <div ref={chartRef} style={{ width: '100%', height }} />
      )}
    </Card>
  );
}
