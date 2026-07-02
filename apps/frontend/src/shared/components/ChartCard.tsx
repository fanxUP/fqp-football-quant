import { useEffect, useRef } from 'react';
import * as echarts from 'echarts';
import Card from './Card';

interface ChartCardProps {
  title: string;
  option: Record<string, unknown>;
  height?: number;
  loading?: boolean;
}

export default function ChartCard({ title, option, height = 300, loading = false }: ChartCardProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!chartRef.current) return;

    const darkOption = {
      backgroundColor: 'transparent',
      textStyle: { color: '#A1A1AA' },
      legend: { textStyle: { color: '#A1A1AA' } },
      ...option,
    };

    const inst = echarts.init(chartRef.current, undefined, { renderer: 'canvas' });
    inst.setOption(darkOption);
    instanceRef.current = inst;

    const handleResize = () => inst.resize();
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      inst.dispose();
    };
  }, [option]);

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
