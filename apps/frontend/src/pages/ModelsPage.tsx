import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLanguage } from '../app/LanguageContext';
import { api } from '../core/apiClient';
import type { EvalModelSummary, ModelPerformanceHistory, Prediction, PredictionSummary, PredictionSummaryMeta } from '../core/types';
import { ApiError } from '../core/types';
import PageHeader from '../shared/components/PageHeader';
import Card from '../shared/components/Card';
import DataTable, { type Column } from '../shared/components/DataTable';
import ErrorState from '../shared/components/ErrorState';
import { modelNameLabel, optionLabel, playTypeLabel } from '../shared/constants';
import TeamName from '../shared/components/TeamName';
import ModelPerformanceCharts from '../visualization/ModelPerformanceCharts';
import PredictionModelOverviewPanel from './PredictionModelOverviewPanel';
import ModelPredictionGroups from './ModelPredictionGroups';
import ModelDiagnosticsPanel from './models/ModelDiagnosticsPanel';
import ModelEvaluationPanel from './models/ModelEvaluationPanel';
import ModelPerformanceToolbar from './models/ModelPerformanceToolbar';
import ModelStats from './models/ModelStats';
import type { PerformancePlayType } from './models/modelPerformanceViews';
import ModelResearchPanel from '../features/model-research/ModelResearchPanel';
import './ModelsPage.css';

const EMPTY_HISTORY: ModelPerformanceHistory = { status: 'ok', metric: 'rolling_hit_rate', window: 20, days: 365, points: [], samples: [] };

function summaryStatusText(meta: PredictionSummaryMeta | null, summary: PredictionSummary | null): string {
  if (meta === null) return '全量统计尚未读取；独立于最近 200 条研究记录。';
  if (meta.status === 'pending') return '全量统计尚未生成；暂不显示估算值。';
  if (meta.status === 'unavailable' || summary === null) return '暂无可用的全量预测统计快照；暂不显示估算值。';
  if (meta.status === 'live') return '当前为单场实时统计。';

  const dataTime = meta.data_as_of
    ? new Date(meta.data_as_of).toLocaleString('zh-CN', { hour12: false })
    : '时间未知';
  const ageMinutes = meta.age_seconds === null ? null : Math.floor(meta.age_seconds / 60);
  const ageText = ageMinutes === null ? '' : `，约 ${ageMinutes} 分钟前生成`;
  const staleText = meta.is_stale ? '，已过期' : '';
  if (meta.status === 'refresh_failed') {
    return `上次刷新失败，当前保留上次成功数据；数据截至 ${dataTime}${ageText}${staleText}。`;
  }
  if (meta.status === 'stale') return `数据截至 ${dataTime}${ageText}，已过期。`;
  return `数据截至 ${dataTime}${ageText}。`;
}

export default function ModelsPage() {
  const { translate } = useLanguage();
  const [predictions, setPredictions] = useState<Prediction[]>([]);
  const [summary, setSummary] = useState<PredictionSummary | null>(null);
  const [summaryMeta, setSummaryMeta] = useState<PredictionSummaryMeta | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const summaryPending = useRef(false);
  const [evalModels, setEvalModels] = useState<EvalModelSummary[]>([]);
  const [performanceHistory, setPerformanceHistory] = useState<ModelPerformanceHistory>(EMPTY_HISTORY);
  const [days, setDays] = useState(365);
  const [playType, setPlayType] = useState<PerformancePlayType>('spf');
  const [selectedModels, setSelectedModels] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [evalLoading, setEvalLoading] = useState(true);
  const [historyLoading, setHistoryLoading] = useState(true);
  const predictionPending = useRef(false);
  const [predictionReceivedAt, setPredictionReceivedAt] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [evalError, setEvalError] = useState<string | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);

  const loadPredictions = useCallback(() => {
    if (predictionPending.current) return;
    predictionPending.current = true;
    setLoading(true); setError(null);
    api.predictions({ limit: 200, include_summary: false }).then((response) => { if (!Array.isArray(response.predictions) || response.predictions.length > 200 || new Set(response.predictions.map(row => row?.id)).size !== response.predictions.length || response.predictions.some(row => !row || !Number.isSafeInteger(row.id) || row.id <= 0 || !Number.isSafeInteger(row.match_id) || row.match_id <= 0 || [row.model_name, row.play_type, row.option_code, row.predict_time, row.home_team, row.away_team].some(value => typeof value !== 'string') || [row.raw_model_probability, row.model_probability, row.market_probability, row.fair_odds, row.ev, row.confidence].some(value => value !== null && (typeof value !== 'number' || !Number.isFinite(value))))) throw new ApiError(502, '预测记录身份、范围或指标格式不正确');
      setPredictions(response.predictions); setPredictionReceivedAt(Date.now()); }).catch((reason) => setError(reason instanceof ApiError ? reason.message : '预测数据加载失败')).finally(() => { predictionPending.current = false; setLoading(false); });
  }, []);
  const loadSummary = useCallback(() => {
    if (summaryPending.current) return;
    summaryPending.current = true;
    setSummaryLoading(true); setSummaryError(null);
    api.predictions({ summary_only: true }).then((response) => {
      const value = response.summary;
      const meta = response.summary_meta;
      const validStatuses = ['ok', 'stale', 'refresh_failed', 'unavailable', 'pending', 'live'];
      if (!meta || !validStatuses.includes(meta.status)
        || typeof meta.is_stale !== 'boolean'
        || (meta.age_seconds !== null && (!Number.isSafeInteger(meta.age_seconds) || meta.age_seconds < 0))
        || (meta.stale_after_seconds !== null && (!Number.isSafeInteger(meta.stale_after_seconds) || meta.stale_after_seconds < 0))
        || (meta.data_as_of !== null && typeof meta.data_as_of !== 'string')
        || (meta.last_success_at !== null && typeof meta.last_success_at !== 'string')
        || (meta.last_attempt_at !== null && typeof meta.last_attempt_at !== 'string')) {
        throw new ApiError(502, '全量统计状态格式不正确');
      }
      if (value === null) {
        if (response.total !== null || !['unavailable', 'pending'].includes(meta.status)) {
          throw new ApiError(502, '全量统计格式或口径不正确');
        }
        setSummary(null);
        setSummaryMeta(meta);
        return;
      }
      if ([value.total, value.positive_ev_count, value.model_count].some(count => !Number.isSafeInteger(count) || count < 0)
        || response.total !== value.total || value.positive_ev_count > value.total || value.model_count > value.total
        || (value.avg_confidence !== null && (!Number.isFinite(value.avg_confidence) || value.avg_confidence < 0 || value.avg_confidence > 1))
        || (value.latest_predict_time !== null && typeof value.latest_predict_time !== 'string')
        || ['unavailable', 'pending'].includes(meta.status)) throw new ApiError(502, '全量统计格式或口径不正确');
      setSummary(value); setSummaryMeta(meta);
    }).catch(reason => setSummaryError(reason instanceof ApiError ? reason.message : '全量预测统计读取失败，请稍后重试'))
      .finally(() => { summaryPending.current = false; setSummaryLoading(false); });
  }, []);
  const loadEvaluation = useCallback(() => {
    setEvalLoading(true); setEvalError(null);
    api.analysis.evaluationSummary().then((response) => setEvalModels(response.status === 'ok' ? response.models : [])).catch(() => setEvalError('评估指标加载失败，请稍后重试')).finally(() => setEvalLoading(false));
  }, []);
  const loadHistory = useCallback(() => {
    setHistoryLoading(true); setHistoryError(null);
    api.analysis.performanceHistory({ window: 20, days }).then(setPerformanceHistory).catch((reason) => setHistoryError(reason instanceof ApiError ? reason.message : '模型曲线加载失败')).finally(() => setHistoryLoading(false));
  }, [days]);

  useEffect(() => { loadPredictions(); loadEvaluation(); }, [loadEvaluation, loadPredictions]);
  useEffect(() => { loadHistory(); }, [loadHistory]);

  const modelNames = useMemo(() => [...new Set([
    ...evalModels.map((model) => model.model_name),
    ...performanceHistory.samples.map((sample) => sample.model_name),
    ...predictions.map((prediction) => prediction.model_name),
  ])], [evalModels, performanceHistory.samples, predictions]);

  useEffect(() => {
    if (selectedModels.length > 0 || modelNames.length === 0) return;
    const ranked = performanceHistory.samples.filter((sample) => sample.play_type === 'spf').sort((left, right) => right.total_samples - left.total_samples).map((sample) => sample.model_name);
    const defaults = [...new Set(['market_baseline', ...ranked])].filter((model) => modelNames.includes(model)).slice(0, 5);
    setSelectedModels(defaults.length > 0 ? defaults : modelNames.slice(0, 5));
  }, [modelNames, performanceHistory.samples, selectedModels.length]);

  const columns: Column<Prediction>[] = [
    { key: 'model_name', title: translate('模型'), render: (value) => modelNameLabel(String(value)) },
    { key: 'home_team', title: translate('主队'), width: '120px', render: (value) => <TeamName name={String(value)} /> },
    { key: 'away_team', title: translate('客队'), width: '120px', render: (value) => <TeamName name={String(value)} /> },
    { key: 'play_type', title: translate('玩法'), width: '80px', render: (value) => playTypeLabel(String(value)) },
    { key: 'option_code', title: translate('选项'), width: '60px', render: (value, row) => optionLabel(row.play_type, String(value)) },
    { key: 'raw_model_probability', title: translate('原始概率'), render: (value) => value == null ? '—' : `${(Number(value) * 100).toFixed(1)}%` },
    { key: 'model_probability', title: translate('最终概率'), render: (value, row) => value == null ? '—' : <span>{(Number(value) * 100).toFixed(1)}%{row.feature_adjusted && <small className="model-feature-adjusted">{translate('特征已修正')}</small>}</span> },
    { key: 'market_probability', title: translate('市场概率'), render: (value) => value == null ? '—' : `${(Number(value) * 100).toFixed(1)}%` },
    { key: 'ev', title: 'EV', render: (value) => value == null ? '—' : <span className={`fqp-mono model-ev ${Number(value) >= 0 ? 'is-positive' : 'is-negative'}`}>{Number(value) >= 0 ? '+' : ''}{Number(value).toFixed(4)}</span> },
    { key: 'confidence', title: translate('置信度'), render: (value) => value == null ? '—' : `${(Number(value) * 100).toFixed(0)}%` },
    { key: 'predict_time', title: translate('预测时间'), render: (value) => String(value).replace('T', ' ').slice(0, 19) },
  ];

  return (
    <div className="models-page">
      <PageHeader title="模型表现" subtitle="按独立比赛评估模型，正式结论与小样本观察严格分区" />
      <ModelResearchPanel predictions={predictions} loading={loading} error={error} receivedAt={predictionReceivedAt} total={summary?.total ?? null} onRefresh={loadPredictions} />
      <section aria-label="全量预测统计">
        <button type="button" className="fqp-btn fqp-btn-secondary" onClick={loadSummary} disabled={summaryLoading}>加载全量预测统计</button>
        <p role="status" aria-atomic="true">{summaryStatusText(summaryMeta, summary)} 刷新最近研究记录不会更新此统计。</p>
        {summaryError && <p role="alert">{summaryError}{summary ? '；保留上次成功的全量统计。' : '；尚无成功统计，指标显示未知。'}</p>}
        <ModelStats summary={summary} loading={summaryLoading && summary === null} />
      </section>
      <ModelPerformanceToolbar days={days} modelNames={modelNames} selectedModels={selectedModels} onDaysChange={setDays} onSelectedModelsChange={setSelectedModels} />
      <ModelEvaluationPanel models={evalModels} loading={evalLoading} error={evalError} onRetry={loadEvaluation} />
      {performanceHistory.stale && <p role="status">模型曲线显示上次完成的数据，正在等待更新。{performanceHistory.refreshedAt ? `摘要更新时间：${new Date(performanceHistory.refreshedAt).toLocaleString('zh-CN', { hour12: false })}` : ''}</p>}
      <ModelPerformanceCharts points={performanceHistory.points} samples={performanceHistory.samples} days={performanceHistory.days} modelNames={modelNames} selectedModels={selectedModels} playType={playType} window={performanceHistory.window} loading={historyLoading} error={historyError} onRetry={loadHistory} onPlayTypeChange={setPlayType} />
      <ModelDiagnosticsPanel modelNames={modelNames} />
      <PredictionModelOverviewPanel />
      <section aria-labelledby="model-prediction-details-title">
        <h2 id="model-prediction-details-title" className="models-page-section-title">{translate('预测明细')}</h2>
        {error ? <ErrorState message={error} onRetry={loadPredictions} /> : <Card className="model-prediction-table-card">{loading ? <DataTable columns={columns} rows={[]} loading /> : <ModelPredictionGroups columns={columns} predictions={predictions} />}</Card>}
      </section>
    </div>
  );
}
