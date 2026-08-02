import { useMemo } from 'react';
import type { OddsMovementPoint } from '../../core/types';
import ChartFrame from '../core/ChartFrame';
import LightweightLineChart from '../timeseries/LightweightLineChart';
import { buildOddsLineSeries } from './oddsChartData';

interface OddsLineSeriesCardProps {
  data: OddsMovementPoint[];
  playType: string;
  title: string;
  subtitle: string;
  emptyReason?: string;
  anomalyCount?: number;
}

function latestSnapshot(data: OddsMovementPoint[]): string | undefined {
  const latest = data.reduce<string | undefined>((current, point) => (
    !current || Date.parse(point.snapshot_time) > Date.parse(current) ? point.snapshot_time : current
  ), undefined);
  if (!latest) return undefined;
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(new Date(latest));
}

export default function OddsLineSeriesCard({
  data,
  title,
  subtitle,
  emptyReason,
  anomalyCount = 0,
}: OddsLineSeriesCardProps) {
  const series = useMemo(() => buildOddsLineSeries(data), [data]);
  const context = anomalyCount ? `${subtitle} · 检出 ${anomalyCount} 次异常波动` : subtitle;

  return (
    <ChartFrame
      title={title}
      subtitle={`${context} · 点击图表后可滚轮缩放、拖动查看时间`}
      updatedAt={latestSnapshot(data)}
      empty={!series.length}
      emptyReason={emptyReason || '该玩法暂无官方赔率快照'}
      height={300}
    >
      <LightweightLineChart
        series={series}
        ariaLabel={`${title}。${context}`}
        height={300}
        valuePrecision={2}
      />
    </ChartFrame>
  );
}
