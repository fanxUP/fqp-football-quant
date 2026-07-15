import { useMemo } from 'react';
import type { EChartsOption } from 'echarts';
import type { ModelPerformancePoint } from '../core/types';
import ChartCard from '../shared/components/ChartCard';
import { modelNameLabel, playTypeLabel } from '../shared/constants';
import { applyChartTheme, CHART_COLORS } from './chartTheme';
import { useTheme } from '../app/ThemeContext';

const PLAY_TYPES = ['spf', 'rqspf', 'bf', 'zjq', 'bqc'] as const;
const OVERALL_PLAY_TYPE = 'all';

interface ModelPerformanceChartsProps {
  points: ModelPerformancePoint[];
  window: number;
  loading?: boolean;
  error?: string | null;
}

export function buildModelPerformanceOption(
  points: ModelPerformancePoint[],
  playType: string,
): EChartsOption | null {
  const playPoints = points.filter((point) => point.play_type === playType);
  if (playPoints.length === 0) return null;

  const dates = [...new Set(playPoints.map((point) => point.date))].sort();
  const models = [...new Set(playPoints.map((point) => point.model_name))].sort();
  const modelColors: Record<string, string> = {
    elo_rating: CHART_COLORS.blue,
    market_baseline: CHART_COLORS.amber,
    dixon_coles: CHART_COLORS.green,
    maher_poisson: CHART_COLORS.primary,
  };
  const values = new Map(
    playPoints.map((point) => [
      `${point.model_name}:${point.date}`,
      Math.round(point.hit_rate * 1000) / 10,
    ]),
  );

  return applyChartTheme({
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value: number) => `${Number(value).toFixed(1)}%`,
    },
    legend: {
      type: 'scroll',
      data: models.map(modelNameLabel),
    },
    grid: { left: '3%', right: '5%', bottom: '12%', top: '18%', containLabel: true },
    xAxis: {
      type: 'category',
      data: dates.map((date) => date.slice(5)),
      name: '日期',
      boundaryGap: false,
    },
    yAxis: {
      type: 'value',
      name: '命中率',
      min: 0,
      max: 100,
      axisLabel: { formatter: '{value}%' },
    },
    series: models.map((modelName) => {
      const color = modelColors[modelName];
      return {
        name: modelNameLabel(modelName),
        type: 'line',
        data: dates.map((date) => values.get(`${modelName}:${date}`) ?? null),
        connectNulls: true,
        smooth: 0.2,
        symbol: 'circle',
        symbolSize: 6,
        lineStyle: { width: 2, ...(color ? { color } : {}) },
        itemStyle: color ? { color } : undefined,
      };
    }),
  } as EChartsOption) as EChartsOption;
}

export default function ModelPerformanceCharts({
  points,
  window,
  loading = false,
  error,
}: ModelPerformanceChartsProps) {
  const { theme } = useTheme();
  const options = useMemo(
    () => new Map(
      [OVERALL_PLAY_TYPE, ...PLAY_TYPES].map((playType) => [
        playType,
        buildModelPerformanceOption(points, playType),
      ]),
    ),
    [points, theme],
  );
  const overallOption = options.get(OVERALL_PLAY_TYPE);

  return (
    <section aria-labelledby="model-performance-trend-title" style={{ marginBottom: '20px' }}>
      <div style={{ marginBottom: '12px' }}>
        <h2 id="model-performance-trend-title" style={{ margin: 0, fontSize: '18px' }}>
          模型表现曲线
        </h2>
        <p style={{ margin: '4px 0 0', color: 'var(--fqp-text-muted)', fontSize: '12px' }}>
          每场取模型概率最高的选项；分玩法按场统计，综合视图按已结算预测次数统计
        </p>
      </div>
      <div style={{ marginBottom: '16px' }}>
        <ChartCard
          title="综合表现 · 模型对比"
          subtitle={`汇总模型已覆盖玩法 · 最多最近 ${window} 次预测`}
          option={(overallOption || {}) as Record<string, unknown>}
          height={340}
          loading={loading}
          error={error}
          empty={!loading && !error && !overallOption}
          emptyReason="暂无综合模型表现数据"
        />
      </div>
      <div className="fqp-grid-2">
        {PLAY_TYPES.map((playType) => {
          const option = options.get(playType);
          return (
            <ChartCard
              key={playType}
              title={`${playTypeLabel(playType)} · 模型对比`}
              subtitle={`最多最近 ${window} 场滚动命中率`}
              option={(option || {}) as Record<string, unknown>}
              height={300}
              loading={loading}
              error={error}
              empty={!loading && !error && !option}
              emptyReason="暂无已结算模型预测"
            />
          );
        })}
      </div>
    </section>
  );
}
