import type { BetSlipItem, CalculationResult, LiveRecommendation } from '../../core/types';
import { formatPassTypes } from './model';

interface RecommendationPanelProps {
  recommendations: LiveRecommendation[];
  loading: boolean;
  error: string;
  availableRecommendationIds: Set<number>;
  onAdd: (recommendation: LiveRecommendation) => void;
}

interface TicketPreviewProps {
  selections: BetSlipItem[];
  selectedMatchCount: number;
  selectedPassTypes: string[];
  multiple: number;
  calculation: CalculationResult | null;
  calculating: boolean;
  submitting: boolean;
  warning: string;
  onRemove: (item: BetSlipItem) => void;
  onConfirm: () => void;
}

function percent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

export function RecommendationPanel(props: RecommendationPanelProps) {
  return (
    <aside className="betting-recommendations" aria-label="推荐投注">
      <div className="betting-slip-head">
        <div><h3>推荐投注</h3><span>今日决策分析产生的正 EV 方案</span></div>
      </div>
      {props.error ? (
        <div className="betting-slip-empty"><strong>推荐加载失败</strong><span>{props.error}</span></div>
      ) : props.loading ? (
        <div className="betting-slip-empty"><strong>正在读取推荐</strong><span>正在同步模型与官方在售赔率…</span></div>
      ) : props.recommendations.length === 0 ? (
        <div className="betting-slip-empty"><strong>暂无推荐</strong><span>产生满足阈值的正 EV 信号后会显示在这里。</span></div>
      ) : (
        <div className="betting-recommendation-list">
          {props.recommendations.map((recommendation) => {
            const available = props.availableRecommendationIds.has(recommendation.prediction_id);
            return (
              <article key={recommendation.prediction_id} className="betting-recommendation-card">
                <div className="betting-recommendation-head">
                  <span>{recommendation.match_num_str || recommendation.league}</span>
                  <strong>{recommendation.home_team} vs {recommendation.away_team}</strong>
                </div>
                <div className="betting-recommendation-pick">
                  <span>{recommendation.play_type_name}</span>
                  <strong>{recommendation.option_name} @{recommendation.sp_value.toFixed(2)}</strong>
                </div>
                <div className="betting-recommendation-metrics">
                  <span>模型 {percent(recommendation.model_probability)}</span>
                  <span>市场 {percent(recommendation.market_probability)}</span>
                  <span>保本 {percent(recommendation.break_even_probability)}</span>
                  <span>市场 Edge {percent(recommendation.market_edge)}</span>
                  <span>EV {percent(recommendation.ev)}</span>
                  <span>完整度 {recommendation.data_completeness == null ? '—' : `${recommendation.data_completeness.toFixed(0)}%`}</span>
                </div>
                <button
                  type="button"
                  className="fqp-btn fqp-btn-primary"
                  disabled={!available}
                  title={available ? '使用当前官方固定奖金加入投注器' : '当前官方投注器没有对应的可售选项'}
                  onClick={() => props.onAdd(recommendation)}
                >
                  {available ? `加入 ${recommendation.option_name}` : '当前不可投'}
                </button>
              </article>
            );
          })}
        </div>
      )}
    </aside>
  );
}

export function TicketPreview(props: TicketPreviewProps) {
  const source = props.selections.some((item) => item.basis?.source === 'recommendation') ? '推荐投注' : '手工选号';
  const canConfirm = Boolean(
    props.selections.length > 0 &&
    props.selectedPassTypes.length > 0 &&
    props.calculation &&
    !props.calculating &&
    !props.submitting &&
    !props.warning &&
    (props.calculation?.total_cost ?? 0) <= 20_000,
  );
  return (
    <aside className={`betting-slip ${props.selections.length > 0 ? 'has-selections' : 'is-empty'}`} aria-label="票面预览">
      <div className="betting-slip-head">
        <div><h3>票面预览</h3><span>{props.selectedMatchCount} 场 / {props.selections.length} 项</span></div>
      </div>
      {props.selections.length === 0 ? (
        <div className="betting-slip-empty"><strong>等待投注器生成票面</strong><span>从左侧加入推荐，或在中间投注器手工选号。</span></div>
      ) : (
        <div className="betting-slip-items">
          {props.selections.map((item) => (
            <article key={`${item.match_id}:${item.play_type}:${item.option_code}`} className="betting-slip-item">
              <span>{item.play_type_label}</span>
              <strong>{item.home_team} vs {item.away_team}</strong>
              <div className="betting-slip-pick"><span>{item.option_name}</span><strong>@ {item.sp_value.toFixed(2)}</strong></div>
              <div className="betting-slip-basis">
                <div><span>来源</span><strong>{item.basis?.source === 'recommendation' ? '推荐投注' : '手工选号'}</strong></div>
                <button type="button" className="fqp-btn fqp-btn-sm" onClick={() => props.onRemove(item)}>移除</button>
              </div>
            </article>
          ))}
        </div>
      )}
      <div className="betting-summary">
        <h4>投注确认</h4>
        <div><span>来源</span><strong>{source}</strong></div>
        <div><span>过关方式</span><strong>{formatPassTypes(props.selectedPassTypes)}</strong></div>
        <div><span>倍数</span><strong>{props.multiple} 倍</strong></div>
        <div><span>注数</span><strong>{props.calculation?.bet_count ?? 0} 注</strong></div>
        <div><span>投注金额</span><strong>¥{(props.calculation?.total_cost ?? 0).toFixed(2)}</strong></div>
        <div><span>理论最高奖金</span><strong>¥{(props.calculation?.max_prize ?? 0).toFixed(2)}</strong></div>
      </div>
      {props.warning && <div className="betting-warnings" role="alert">{props.warning}</div>}
      <button type="button" className="betting-submit" disabled={!canConfirm} onClick={props.onConfirm}>
        {props.submitting ? '保存中…' : props.calculating ? '计算中…' : '确认投注'}
      </button>
    </aside>
  );
}
