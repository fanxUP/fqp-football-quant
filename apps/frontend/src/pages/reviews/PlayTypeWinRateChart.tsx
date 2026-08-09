import { useMemo } from 'react';
import type { PlayTypeWinRate } from '../../core/types';
import ChartFrame from '../../visualization/core/ChartFrame';
import LightweightLineChart from '../../visualization/timeseries/LightweightLineChart';
import { buildPlayTypeWinRateSeries } from './playTypeWinRateSeries';

const PERCENT_RANGE = [0, 100] as const;

interface PlayTypeWinRateChartProps {
  data: PlayTypeWinRate[];
  loading?: boolean;
}

/** Same chart engine and interaction model used by the model-comparison charts. */
export default function PlayTypeWinRateChart({ data, loading = false }: PlayTypeWinRateChartProps) {
  const series = useMemo(() => buildPlayTypeWinRateSeries(data), [data]);

  return (
    <ChartFrame
      title="各玩法胜率走势"
      subtitle="按结算日期统计 · 纵轴单位 %"
      height={320}
      loading={loading}
      empty={!loading && series.length === 0}
      emptyReason="暂无已结算玩法数据"
    >
      <LightweightLineChart
        series={series}
        ariaLabel="各玩法胜率对比"
        height={320}
        valuePrecision={1}
        valueSuffix="%"
        valueRange={PERCENT_RANGE}
      />
    </ChartFrame>
  );
}
