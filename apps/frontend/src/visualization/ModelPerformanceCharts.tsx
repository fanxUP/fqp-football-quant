import { useMemo } from 'react';
import { useLanguage } from '../app/LanguageContext';
import type { ModelPerformancePoint, ModelPerformanceSample } from '../core/types';
import { playTypeLabel } from '../shared/constants';
import { modelNameLabel } from '../shared/constants';
import { useTheme } from '../app/ThemeContext';
import ChartFrame from './core/ChartFrame';
import LightweightLineChart, { type LightweightLineSeries } from './timeseries/LightweightLineChart';
import { buildModelPerformanceSeries, type ModelPerformanceSeriesData } from './model/modelPerformanceData';
import { getModelLineVisual } from './model/modelVisuals';
import ModelSampleSufficiency from './model/ModelSampleSufficiency';
import type { PerformancePlayType } from '../pages/models/ModelPerformanceToolbar';
import './ModelPerformanceCharts.css';

const MIN_TREND_DATES = 8;
const PERCENT_RANGE = [0, 100] as const;

interface ModelPerformanceChartsProps {
  points: ModelPerformancePoint[];
  samples: ModelPerformanceSample[];
  days: number;
  modelNames: string[];
  selectedModels: string[];
  playType: PerformancePlayType;
  window: number;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
}

function addModelVisuals(series: ModelPerformanceSeriesData[]): LightweightLineSeries[] {
  return series.map((item) => ({ id: item.id, name: item.name, data: item.data, ...getModelLineVisual(item.id) }));
}

function downloadCsv(series: ModelPerformanceSeriesData[], playType: string) {
  const lines = ['date,model,hit_rate_percent,sample_size'];
  for (const item of series) for (const point of item.data) lines.push(`${point.time},${item.id},${point.value},${item.latestSampleSize}`);
  const url = URL.createObjectURL(new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' }));
  const anchor = document.createElement('a'); anchor.href = url; anchor.download = `model-performance-${playType}.csv`; anchor.click(); URL.revokeObjectURL(url);
}

function AccessibleSeriesTable({ series }: { series: ModelPerformanceSeriesData[] }) {
  const { translate } = useLanguage();
  return (
    <details className="model-chart-data">
      <summary>{translate('查看图表数据')}</summary>
      <div className="model-metrics-table-wrap"><table className="model-metrics-table"><thead><tr><th>{translate('模型')}</th><th>{translate('日期')}</th><th>{translate('滚动命中率')}</th><th>{translate('滚动样本')}</th></tr></thead><tbody>{series.flatMap((item) => item.data.map((point) => <tr key={`${item.id}-${point.time}`}><th scope="row">{item.name}</th><td>{point.time}</td><td>{point.value.toFixed(1)}%</td><td>{item.latestSampleSize}</td></tr>))}</tbody></table></div>
    </details>
  );
}

export default function ModelPerformanceCharts({ points, samples, days, modelNames, selectedModels, playType, window, loading = false, error, onRetry }: ModelPerformanceChartsProps) {
  const { theme } = useTheme();
  const { language, translate } = useLanguage();
  const selected = useMemo(() => new Set(selectedModels), [selectedModels]);
  const chartData = useMemo(() => buildModelPerformanceSeries(points.filter((point) => selected.has(point.model_name)), playType).map((item) => ({ ...item, name: translate(modelNameLabel(item.id)) })), [points, playType, selected, translate]);
  const renderSeries = useMemo(() => addModelVisuals(chartData), [chartData, theme]);
  const dateCount = Math.max(0, ...chartData.map((item) => item.dateCount));
  const title = playType === 'all' ? translate('跨玩法概览') : `${playTypeLabel(playType)} · ${translate('模型对比')}`;
  const ariaLabel = language === 'en' ? `${title} rolling hit-rate comparison` : `${title}滚动命中率对比`;

  return (
    <section aria-labelledby="model-performance-trend-title" className="model-performance-section">
      <header className="model-performance-heading">
        <div><h2 id="model-performance-trend-title">{translate('模型表现曲线')}</h2><p>{translate('命中率仅作辅助趋势；正式结论以 Brier、Log Loss 与校准表现为主。')}</p></div>
        {chartData.length > 0 && <button type="button" className="fqp-btn fqp-btn-secondary" onClick={() => downloadCsv(chartData, playType)}>{translate('导出 CSV')}</button>}
      </header>
      <ModelSampleSufficiency samples={samples} modelNames={modelNames.filter((model) => selected.has(model))} days={days} />
      {error ? <div className="model-panel-error fqp-card" role="alert"><span>{translate(error)}</span>{onRetry && <button type="button" className="fqp-btn fqp-btn-secondary" onClick={onRetry}>{translate('重试')}</button>}</div> : (
        <ChartFrame title={title} subtitle={`${translate('最近')} ${window} ${translate('次预测的滚动命中率')} · ${dateCount} ${translate('个结算日期')} · %`} controls={dateCount > 0 && dateCount < MIN_TREND_DATES ? <span className="model-performance-sample-warning">{translate('样本日期不足')}</span> : undefined} height={340} loading={loading} empty={!loading && renderSeries.length === 0} emptyReason={translate('暂无已结算模型预测')}>
          <LightweightLineChart series={renderSeries} ariaLabel={ariaLabel} height={340} valuePrecision={1} valueSuffix="%" valueRange={PERCENT_RANGE} />
          <AccessibleSeriesTable series={chartData} />
        </ChartFrame>
      )}
    </section>
  );
}
