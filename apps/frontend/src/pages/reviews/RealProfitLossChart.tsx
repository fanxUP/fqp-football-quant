import { useMemo } from 'react';
import type { DailyReview } from '../../core/types';
import ChartFrame from '../../visualization/core/ChartFrame';
import LightweightLineChart from '../../visualization/timeseries/LightweightLineChart';
import { buildProfitLossSeries } from './profitLossSeries';

interface RealProfitLossChartProps {
  reviews: DailyReview[];
  loading?: boolean;
}

/** Reuses the model-comparison time-series engine for real-ticket P&L. */
export default function RealProfitLossChart({ reviews, loading = false }: RealProfitLossChartProps) {
  const series = useMemo(() => buildProfitLossSeries(reviews), [reviews]);

  return (
    <ChartFrame
      title="实盘盈亏走势"
      subtitle="日盈亏 · 累计盈亏 · 纵轴单位 元"
      height={300}
      loading={loading}
      empty={!loading && series.length === 0}
      emptyReason="暂无已结算实盘数据"
    >
      <LightweightLineChart
        series={series}
        ariaLabel="实盘日盈亏与累计盈亏对比"
        height={300}
        valuePrecision={2}
        valueSuffix=" 元"
      />
    </ChartFrame>
  );
}
