import { useLanguage } from '../../app/LanguageContext';
import type { EvalModelSummary } from '../../core/types';
import Card from '../../shared/components/Card';
import { modelNameLabel } from '../../shared/constants';

interface ModelEvaluationPanelProps {
  models: EvalModelSummary[];
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}

function signed(value: number | null) {
  if (value == null) return '—';
  return `${value >= 0 ? '+' : ''}${value.toFixed(4)}`;
}

function StatusText({ model }: { model: EvalModelSummary }) {
  const { translate } = useLanguage();
  const label = model.is_publishable ? '正式评估' : model.sample_status === 'preliminary' ? '初步观察' : '仅观察';
  return <span className={`model-evaluation-status is-${model.sample_status}`}>{translate(label)}</span>;
}

function MetricsTable({ models, label }: { models: EvalModelSummary[]; label: string }) {
  const { translate } = useLanguage();
  return (
    <div className="model-metrics-table-wrap">
      <table className="model-metrics-table" aria-label={label}>
        <thead><tr>
          <th scope="col">{translate('模型')}</th>
          <th scope="col">{translate('独立比赛')}</th>
          <th scope="col">{translate('状态')}</th>
          <th scope="col">Brier ↓</th>
          <th scope="col">Log Loss ↓</th>
          <th scope="col">{translate('相对市场改善')}</th>
          <th scope="col">95% CI</th>
          <th scope="col">{translate('市场概率变化')}</th>
          <th scope="col">{translate('模型收盘优势')}</th>
          <th scope="col">{translate('赔率 CLV')}</th>
        </tr></thead>
        <tbody>{models.map((model) => (
          <tr key={model.model_name}>
            <th scope="row">{translate(modelNameLabel(model.model_name))}</th>
            <td className="fqp-mono">{model.n}</td>
            <td><StatusText model={model} /></td>
            <td className="fqp-mono">{model.avg_brier.toFixed(4)}</td>
            <td className="fqp-mono">{model.avg_logloss.toFixed(4)}</td>
            <td className="fqp-mono">{signed(model.brier_improvement_vs_market)}</td>
            <td className="fqp-mono">{model.brier_improvement_ci_low == null || model.brier_improvement_ci_high == null ? '—' : `${model.brier_improvement_ci_low.toFixed(4)} ~ ${model.brier_improvement_ci_high.toFixed(4)}`}</td>
            <td className="fqp-mono">{signed(model.avg_market_probability_move)}</td>
            <td className="fqp-mono">{signed(model.avg_closing_edge)}</td>
            <td className="fqp-mono">{model.avg_odds_clv == null ? translate('暂未采集') : signed(model.avg_odds_clv)}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

export default function ModelEvaluationPanel({ models, loading, error, onRetry }: ModelEvaluationPanelProps) {
  const { translate } = useLanguage();
  const formal = models.filter((model) => model.is_publishable)
    .sort((left, right) => (right.brier_improvement_vs_market ?? -Infinity) - (left.brier_improvement_vs_market ?? -Infinity));
  const observing = models.filter((model) => !model.is_publishable)
    .sort((left, right) => right.n - left.n || left.avg_brier - right.avg_brier);

  return (
    <Card title={translate('独立样本评估')} className="model-evaluation-panel">
      <div className="model-evaluation-note">
        <p>{translate('每个模型名称与比赛只计一次，重训版本不会重复增加样本。')}</p>
        <p>{translate('正式排名以相对市场基准的 Brier 改善为主，并同时显示 95% 置信区间。')}</p>
        <p>{translate('市场概率变化、模型收盘优势与赔率 CLV 分开呈现；当前未采集赔率 CLV。')}</p>
      </div>
      {loading ? <div className="model-panel-state">{translate('加载中...')}</div> : error ? (
        <div className="model-panel-error" role="alert"><span>{translate(error)}</span><button type="button" className="fqp-btn fqp-btn-secondary" onClick={onRetry}>{translate('重试')}</button></div>
      ) : models.length === 0 ? <div className="model-panel-state">{translate('暂无已结算评估数据')}</div> : (
        <>
          <section aria-labelledby="formal-ranking-title">
            <div className="model-section-heading"><h3 id="formal-ranking-title">{translate('正式排名')}</h3><span>{translate('至少 100 场独立已结算比赛')}</span></div>
            {formal.length > 0 ? <MetricsTable models={formal} label={translate('正式模型排名')} /> : <div className="model-panel-state">{translate('目前没有达到正式评估门槛的模型')}</div>}
          </section>
          <details className="model-observation-zone">
            <summary>{translate('观察区')} <span>{observing.length}</span></summary>
            <p>{translate('观察区不参与最佳模型结论，避免小样本偶然波动造成误导。')}</p>
            <MetricsTable models={observing} label={translate('观察区模型指标')} />
          </details>
        </>
      )}
    </Card>
  );
}
