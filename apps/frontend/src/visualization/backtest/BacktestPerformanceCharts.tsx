import { useMemo } from 'react';
import type { BacktestResult, DashboardBacktestEquityItem } from '../../core/types';
import { useTheme } from '../../app/ThemeContext';
import ChartFrame from '../core/ChartFrame';
import { getModelLineVisual } from '../model/modelVisuals';
import LightweightLineChart, { type LightweightLineSeries } from '../timeseries/LightweightLineChart';
import BacktestMetricBarChart from './BacktestMetricBarChart';
import { buildBacktestMetricRows, buildBacktestWindowTrends } from './backtestChartData';
import './BacktestPerformanceCharts.css';

interface BacktestPerformanceChartsProps {
  results: BacktestResult[];
  windowRows: DashboardBacktestEquityItem[];
  loading?: boolean;
  error?: string | null;
}

const MIN_TREND_WINDOWS = 2;
const RECOMMENDED_TREND_WINDOWS = 8;

function decorateSeries(series: ReturnType<typeof buildBacktestWindowTrends>['roiSeries']): LightweightLineSeries[] {
  return series.map((item) => ({ ...item, ...getModelLineVisual(item.id) }));
}

function TrendChart({
  title,
  ariaLabel,
  series,
  dateCount,
  loading,
  error,
  valueRange,
}: {
  title: string;
  ariaLabel: string;
  series: LightweightLineSeries[];
  dateCount: number;
  loading: boolean;
  error?: string | null;
  valueRange?: readonly [number, number];
}) {
  const insufficient = dateCount < MIN_TREND_WINDOWS;
  const warning = dateCount >= MIN_TREND_WINDOWS && dateCount < RECOMMENDED_TREND_WINDOWS;
  const emptyReason = insufficient && dateCount > 0
    ? `当前仅 ${dateCount} 个测试窗口，无法形成时间趋势`
    : '暂无窗口指标数据';

  return (
    <ChartFrame
      title={title}
      subtitle={`按测试结束日期 · ${dateCount} 个测试窗口 · 单位 %`}
      controls={warning ? <span className="backtest-chart-warning">窗口样本偏少</span> : undefined}
      height={280}
      loading={loading}
      error={error}
      empty={!loading && !error && (insufficient || series.length === 0)}
      emptyReason={emptyReason}
    >
      <LightweightLineChart
        series={series}
        ariaLabel={ariaLabel}
        height={280}
        valuePrecision={1}
        valueSuffix="%"
        valueRange={valueRange}
      />
    </ChartFrame>
  );
}

export default function BacktestPerformanceCharts({
  results,
  windowRows,
  loading = false,
  error,
}: BacktestPerformanceChartsProps) {
  const { theme } = useTheme();
  const trends = useMemo(() => buildBacktestWindowTrends(windowRows), [windowRows]);
  const roiRows = useMemo(() => buildBacktestMetricRows(results, 'roi'), [results]);
  const drawdownRows = useMemo(() => buildBacktestMetricRows(results, 'drawdown'), [results]);
  const roiSeries = useMemo(() => decorateSeries(trends.roiSeries), [theme, trends.roiSeries]);
  const drawdownSeries = useMemo(() => decorateSeries(trends.drawdownSeries), [theme, trends.drawdownSeries]);

  return (
    <section className="backtest-performance" aria-label="回测图表分析">
      <div className="backtest-chart-grid">
        <BacktestMetricBarChart rows={roiRows} metric="roi" title="模型 ROI 对比" />
        <BacktestMetricBarChart rows={drawdownRows} metric="drawdown" title="模型最大回撤对比" />
        <TrendChart
          title="窗口 ROI 时间趋势"
          ariaLabel="各模型窗口 ROI 时间趋势"
          series={roiSeries}
          dateCount={trends.dateCount}
          loading={loading}
          error={error}
        />
        <TrendChart
          title="窗口最大回撤时间趋势"
          ariaLabel="各模型窗口最大回撤时间趋势"
          series={drawdownSeries}
          dateCount={trends.dateCount}
          loading={loading}
          error={error}
          valueRange={trends.drawdownRange}
        />
      </div>
    </section>
  );
}
