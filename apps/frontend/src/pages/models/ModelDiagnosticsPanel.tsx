import { useEffect, useState } from 'react';
import { useLanguage } from '../../app/LanguageContext';
import { api } from '../../core/apiClient';
import type { CalibrationData, ConditionPerformanceData, ModelCompareData, ModelPlayTypeRecommendation } from '../../core/types';
import Card from '../../shared/components/Card';
import { modelNameLabel, playTypeLabel } from '../../shared/constants';

type DiagnosticTab = 'calibration' | 'condition' | 'comparison' | 'combos';

interface ModelDiagnosticsPanelProps { modelNames: string[] }

export default function ModelDiagnosticsPanel({ modelNames }: ModelDiagnosticsPanelProps) {
  const { language, translate } = useLanguage();
  const [tab, setTab] = useState<DiagnosticTab>('calibration');
  const [modelName, setModelName] = useState(modelNames[0] ?? '');
  const [dimension, setDimension] = useState<'league' | 'odds_range' | 'confidence'>('league');
  const [data, setData] = useState<CalibrationData | ConditionPerformanceData | ModelCompareData | { status: string; recommendations: ModelPlayTypeRecommendation[] } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!modelName && modelNames.length > 0) setModelName(modelNames[0]);
  }, [modelName, modelNames]);

  const load = () => {
    setLoading(true); setError(null);
    const request = tab === 'calibration'
      ? api.analysis.calibration({ model_name: modelName || undefined })
      : tab === 'condition'
        ? api.analysis.conditionPerformance(dimension)
        : tab === 'comparison'
          ? api.analysis.modelCompare()
          : api.analysis.recommendations({ min_samples: 30, top_n: 12 });
    request.then((result) => setData(result)).catch(() => setError('诊断数据加载失败')).finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, [tab, modelName, dimension]);

  const tabs: Array<[DiagnosticTab, string]> = [['calibration', '概率校准'], ['condition', '条件切片'], ['comparison', '模型对比'], ['combos', '玩法观察']];
  return (
    <Card title={translate('模型诊断')} className="model-diagnostics-panel" action={<a className="model-diagnostics-link" href="#/analysis?section=models">{translate('打开单场解释与特征重要性')} →</a>}>
      <div className="model-diagnostics-tabs" role="tablist" aria-label={translate('模型诊断视图')}>
        {tabs.map(([key, label]) => <button type="button" role="tab" aria-selected={tab === key} className={tab === key ? 'is-active' : ''} onClick={() => { setData(null); setLoading(true); setTab(key); }} key={key}>{translate(label)}</button>)}
      </div>
      <div className="model-diagnostics-controls">
        {tab === 'calibration' && <label>{translate('模型')}<select value={modelName} onChange={(event) => setModelName(event.target.value)}>{modelNames.map((model) => <option value={model} key={model}>{translate(modelNameLabel(model))}</option>)}</select></label>}
        {tab === 'condition' && <label>{translate('切片维度')}<select value={dimension} onChange={(event) => setDimension(event.target.value as typeof dimension)}><option value="league">{translate('联赛')}</option><option value="odds_range">{translate('赔率区间')}</option><option value="confidence">{translate('信心区间')}</option></select></label>}
      </div>
      {loading ? <div className="model-panel-state">{translate('加载中...')}</div> : error ? <div className="model-panel-error" role="alert"><span>{translate(error)}</span><button type="button" className="fqp-btn fqp-btn-secondary" onClick={load}>{translate('重试')}</button></div> : (
        <DiagnosticResult tab={tab} data={data} language={language} />
      )}
    </Card>
  );
}

function DiagnosticResult({ tab, data, language }: { tab: DiagnosticTab; data: ModelDiagnosticsPanelData; language: 'zh-CN' | 'en' }) {
  const { translate } = useLanguage();
  if (!data) return <div className="model-panel-state">{translate('暂无数据')}</div>;
  if (tab === 'calibration') {
    const calibration = data as CalibrationData;
    return <div className="model-calibration-result"><div className="model-diagnostic-kpis"><span><small>ECE</small><strong>{calibration.ece.toFixed(4)}</strong></span><span><small>MCE</small><strong>{calibration.mce.toFixed(4)}</strong></span><span><small>{translate('概率样本')}</small><strong>{calibration.n_predictions}</strong></span></div>{calibration.bins.length === 0 ? <div className="model-panel-state">{translate('样本不足，暂不能生成可靠校准曲线')}</div> : <div className="model-calibration-bars" role="img" aria-label={translate('预测概率与实际命中率校准表')}>{calibration.bins.map((bin) => <div key={bin.bin_center}><span>{(bin.pred_mean * 100).toFixed(0)}%</span><meter min={0} max={1} value={bin.actual_freq}>{bin.actual_freq}</meter><strong>{(bin.actual_freq * 100).toFixed(0)}%</strong><small>n={bin.count}</small></div>)}</div>}</div>;
  }
  if (tab === 'condition') {
    const condition = data as ConditionPerformanceData;
    if (condition.segments.length === 0) return <div className="model-panel-state">{translate('当前切片没有足够样本')}</div>;
    return <div className="model-metrics-table-wrap"><table className="model-metrics-table" aria-label={translate('条件切片表现')}><thead><tr><th>{translate('分组')}</th><th>{translate('模型')}</th><th>n</th><th>Brier ↓</th><th>Log Loss ↓</th></tr></thead><tbody>{condition.segments.map((segment, index) => <tr key={`${segment.model_name}-${index}`}><td>{segment.league_name ?? segment.odds_range ?? segment.confidence_range ?? '—'}</td><th scope="row">{translate(modelNameLabel(segment.model_name))}</th><td>{segment.n}</td><td>{segment.avg_brier.toFixed(4)}</td><td>{segment.avg_logloss?.toFixed(4) ?? '—'}</td></tr>)}</tbody></table></div>;
  }
  if (tab === 'comparison') {
    const comparison = data as ModelCompareData;
    return <div className="model-metrics-table-wrap"><table className="model-metrics-table" aria-label={translate('模型横向对比')}><thead><tr><th>{translate('模型')}</th><th>n</th><th>Brier ↓</th><th>Log Loss ↓</th><th>{translate('市场概率变化')}</th><th>{translate('模型收盘优势')}</th></tr></thead><tbody>{comparison.models.map((model) => <tr key={model.name}><th scope="row">{translate(modelNameLabel(model.name))}</th><td>{model.n_predictions}</td><td>{model.brier.toFixed(4)}</td><td>{model.log_loss.toFixed(4)}</td><td>{model.market_probability_move?.toFixed(4) ?? '—'}</td><td>{model.closing_edge?.toFixed(4) ?? '—'}</td></tr>)}</tbody></table></div>;
  }
  const combos = (data as { recommendations: ModelPlayTypeRecommendation[] }).recommendations ?? [];
  if (combos.length === 0) return <div className="model-panel-state">{translate('没有达到 30 场门槛的模型玩法组合')}</div>;
  return <div className="model-combo-grid">{combos.map((combo) => <article key={`${combo.model_name}-${combo.play_type}`}><strong>{translate(modelNameLabel(combo.model_name))}</strong><span>{translate(playTypeLabel(combo.play_type))} · {combo.wins}/{combo.total}</span><b>{(combo.hit_rate * 100).toFixed(1)}%</b><small>{language === 'en' ? 'Observation only' : '仅作观察，不作为推荐依据'}</small></article>)}</div>;
}

type ModelDiagnosticsPanelData = CalibrationData | ConditionPerformanceData | ModelCompareData | { status: string; recommendations: ModelPlayTypeRecommendation[] } | null;
