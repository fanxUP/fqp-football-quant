import { useMemo } from 'react';
import type { ModelPerformancePoint, ModelPerformanceSample } from '../core/types';
import { playTypeLabel } from '../shared/constants';
import { useTheme } from '../app/ThemeContext';
import ChartFrame from './core/ChartFrame';
import LightweightLineChart, {
  type LightweightLineSeries,
} from './timeseries/LightweightLineChart';
import {
  buildModelPerformanceOverview,
  buildModelPerformanceSeries,
  type ModelPerformanceOverviewItem,
  type ModelPerformanceSeriesData,
} from './model/modelPerformanceData';
import { getModelLineVisual } from './model/modelVisuals';
import ModelSampleSufficiency from './model/ModelSampleSufficiency';
import './ModelPerformanceCharts.css';

const PLAY_TYPES = ['spf', 'rqspf', 'bf', 'zjq', 'bqc'] as const;
const MIN_TREND_DATES = 8;
const PERCENT_RANGE = [0, 100] as const;

interface ModelPerformanceChartsProps {
  points: ModelPerformancePoint[];
  samples: ModelPerformanceSample[];
  days: number;
  modelNames: string[];
  window: number;
  loading?: boolean;
  error?: string | null;
}

function addModelVisuals(series: ModelPerformanceSeriesData[]): LightweightLineSeries[] {
  return series.map((item) => ({
    id: item.id,
    name: item.name,
    data: item.data,
    ...getModelLineVisual(item.id),
  }));
}

function TrendSufficiency({ dateCount }: { dateCount: number }) {
  if (dateCount === 0 || dateCount >= MIN_TREND_DATES) return null;
  return (
    <span className="model-performance-sample-warning" title={`建议至少 ${MIN_TREND_DATES} 个结算日期`}>
      样本日期不足
    </span>
  );
}

function OverviewRanking({ rows }: { rows: ModelPerformanceOverviewItem[] }) {
  return (
    <div className="model-performance-ranking" aria-label="模型综合表现排名">
      {rows.map((row) => {
        const change = row.changePercentagePoints;
        const changeText = change == null ? '暂无环比' : `${change >= 0 ? '+' : ''}${change.toFixed(1)} 个百分点`;
        return (
          <article className="model-performance-rank-item" key={row.modelName}>
            <span className="model-performance-rank-number" aria-label={`第 ${row.rank} 名`}>{row.rank}</span>
            <div className="model-performance-rank-copy">
              <strong>{row.label}</strong>
              <span>滚动样本 {row.latestSampleSize} 次 · {row.dateCount} 个结算日期</span>
            </div>
            <div className="model-performance-rank-value">
              <strong>{row.latestHitRate.toFixed(1)}%</strong>
              <span className={change != null && change < 0 ? 'is-down' : undefined}>{changeText}</span>
            </div>
          </article>
        );
      })}
    </div>
  );
}

interface PerformanceChartProps {
  title: string;
  ariaLabel: string;
  series: LightweightLineSeries[];
  dateCount: number;
  window: number;
  height: number;
  loading: boolean;
  error?: string | null;
  overview?: ModelPerformanceOverviewItem[];
}

function PerformanceChart({
  title,
  ariaLabel,
  series,
  dateCount,
  window,
  height,
  loading,
  error,
  overview,
}: PerformanceChartProps) {
  return (
    <ChartFrame
      title={title}
      subtitle={`最近 ${window} 次预测的滚动命中率 · ${dateCount} 个结算日期 · 纵轴单位 %`}
      controls={<TrendSufficiency dateCount={dateCount} />}
      height={height}
      loading={loading}
      error={error}
      empty={!loading && !error && series.length === 0}
      emptyReason="暂无已结算模型预测"
    >
      {overview && overview.length > 0 && <OverviewRanking rows={overview} />}
      <LightweightLineChart
        series={series}
        ariaLabel={ariaLabel}
        height={height}
        valuePrecision={1}
        valueSuffix="%"
        valueRange={PERCENT_RANGE}
      />
    </ChartFrame>
  );
}

export default function ModelPerformanceCharts({
  points,
  samples,
  days,
  modelNames,
  window,
  loading = false,
  error,
}: ModelPerformanceChartsProps) {
  const { theme } = useTheme();
  const chartData = useMemo(() => {
    const result = new Map<string, ModelPerformanceSeriesData[]>();
    for (const playType of ['all', ...PLAY_TYPES]) {
      result.set(playType, buildModelPerformanceSeries(points, playType));
    }
    return result;
  }, [points]);
  const overview = useMemo(() => buildModelPerformanceOverview(points), [points]);

  const renderData = useMemo(() => {
    const result = new Map<string, LightweightLineSeries[]>();
    chartData.forEach((series, playType) => result.set(playType, addModelVisuals(series)));
    return result;
  }, [chartData, theme]);

  const dateCount = (playType: string) => Math.max(
    0,
    ...(chartData.get(playType) ?? []).map((item) => item.dateCount),
  );

  return (
    <section aria-labelledby="model-performance-trend-title" className="model-performance-section">
      <header className="model-performance-heading">
        <h2 id="model-performance-trend-title">模型表现曲线</h2>
        <p>按结算日期比较各模型滚动命中率；颜色和线型共同区分模型，点击图例可隐藏或显示曲线。</p>
      </header>

      <ModelSampleSufficiency samples={samples} modelNames={modelNames} days={days} />

      <div className="model-performance-overall">
        <PerformanceChart
          title="综合表现 · 模型对比"
          ariaLabel="综合模型滚动命中率对比"
          series={renderData.get('all') ?? []}
          dateCount={dateCount('all')}
          window={window}
          height={340}
          loading={loading}
          error={error}
          overview={overview}
        />
      </div>

      <div className="model-performance-grid">
        {PLAY_TYPES.map((playType) => (
          <PerformanceChart
            key={playType}
            title={`${playTypeLabel(playType)} · 模型对比`}
            ariaLabel={`${playTypeLabel(playType)}模型滚动命中率对比`}
            series={renderData.get(playType) ?? []}
            dateCount={dateCount(playType)}
            window={window}
            height={280}
            loading={loading}
            error={error}
          />
        ))}
      </div>
    </section>
  );
}
