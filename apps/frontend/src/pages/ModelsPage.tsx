import { useCallback, useEffect, useMemo, useState } from 'react';
import { useLanguage } from '../app/LanguageContext';
import { api } from '../core/apiClient';
import type { EvalModelSummary, ModelPerformanceHistory, Prediction, PredictionSummary } from '../core/types';
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
import './ModelsPage.css';

const EMPTY_HISTORY: ModelPerformanceHistory = { status: 'ok', metric: 'rolling_hit_rate', window: 20, days: 365, points: [], samples: [] };

export default function ModelsPage() {
  const { translate } = useLanguage();
  const [predictions, setPredictions] = useState<Prediction[]>([]);
  const [summary, setSummary] = useState<PredictionSummary | null>(null);
  const [evalModels, setEvalModels] = useState<EvalModelSummary[]>([]);
  const [performanceHistory, setPerformanceHistory] = useState<ModelPerformanceHistory>(EMPTY_HISTORY);
  const [days, setDays] = useState(365);
  const [playType, setPlayType] = useState<PerformancePlayType>('spf');
  const [selectedModels, setSelectedModels] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [evalLoading, setEvalLoading] = useState(true);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [evalError, setEvalError] = useState<string | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);

  const loadPredictions = useCallback(() => {
    setLoading(true); setError(null);
    api.predictions({ limit: 200 }).then((response) => { setPredictions(response.predictions); setSummary(response.summary); }).catch((reason) => setError(reason instanceof ApiError ? reason.message : '预测数据加载失败')).finally(() => setLoading(false));
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
      <ModelStats summary={summary} loading={loading} />
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
