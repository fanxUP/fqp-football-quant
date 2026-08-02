import type { BetSlipItem, CalculationResult, LiveRecommendation } from '../../core/types';
import { optionLabel, playTypeLabel } from '../../shared/constants';
import { formatPassTypes } from './model';
import { useLanguage } from '../../app/LanguageContext';

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
  const { translate } = useLanguage();
  return (
    <aside className="betting-recommendations" aria-label={translate('推荐投注')}>
      <div className="betting-slip-head">
        <div><h3>{translate('智能代理每日推荐')}</h3><span>{translate('虚拟 500 元用于记录模型表现，是否购买由你决定')}</span></div>
      </div>
      {props.error ? (
        <div className="betting-slip-empty"><strong>{translate('推荐加载失败')}</strong><span>{props.error}</span></div>
      ) : props.loading ? (
        <div className="betting-slip-empty"><strong>{translate('正在读取推荐')}</strong><span>{translate('正在同步模型与官方在售赔率…')}</span></div>
      ) : props.recommendations.length === 0 ? (
        <div className="betting-slip-empty"><strong>{translate('暂无推荐')}</strong><span>{translate('可信模型与官方赔率准备完成后会显示在这里。')}</span></div>
      ) : (
        <div className="betting-recommendation-list">
          {props.recommendations.map((recommendation) => {
            const available = props.availableRecommendationIds.has(recommendation.prediction_id);
            const optionName = optionLabel(recommendation.play_type, recommendation.option_code);
            const actionTitle = available
              ? translate('使用当前官方固定奖金加入投注器')
              : translate('当前官方投注器没有对应的可售选项');
            return (
              <article key={recommendation.prediction_id} className="betting-recommendation-card">
                <div className="betting-recommendation-head">
                  <span>{recommendation.match_num_str || recommendation.league}</span>
                  <strong>{recommendation.home_team} VS {recommendation.away_team}</strong>
                </div>
                <div className="betting-recommendation-pick">
                  <span>{playTypeLabel(recommendation.play_type)}</span>
                  <strong>{optionName} @{recommendation.sp_value.toFixed(2)}</strong>
                </div>
                <div className="betting-recommendation-metrics">
                  <span>{translate('模型')} {percent(recommendation.model_probability)}</span>
                  <span>{translate('市场')} {percent(recommendation.market_probability)}</span>
                  <span>{translate('保本')} {percent(recommendation.break_even_probability)}</span>
                  <span>{translate('市场 Edge')} {percent(recommendation.market_edge)}</span>
                  <span>EV {percent(recommendation.ev)}</span>
                  <span>{translate('完整度')} {recommendation.data_completeness == null ? '—' : `${recommendation.data_completeness.toFixed(0)}%`}</span>
                </div>
                <button
                  type="button"
                  className="fqp-btn fqp-btn-primary"
                  disabled={!available}
                  title={actionTitle}
                  onClick={() => props.onAdd(recommendation)}
                >
                  {available ? `${translate('加入')} ${optionName}` : translate('当前不可投')}
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
  const { translate } = useLanguage();
  const source = props.selections.some((item) => item.basis?.source === 'recommendation') ? translate('推荐投注') : translate('手工选号');
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
    <aside className={`betting-slip ${props.selections.length > 0 ? 'has-selections' : 'is-empty'}`} aria-label={translate('票面预览')}>
      <div className="betting-slip-head">
        <div><h3>{translate('票面预览')}</h3><span>{props.selectedMatchCount} {translate('场')} / {props.selections.length} {translate('项')}</span></div>
      </div>
      {props.selections.length === 0 ? (
        <div className="betting-slip-empty"><strong>{translate('等待投注器生成票面')}</strong><span>{translate('从左侧加入推荐，或在中间投注器手工选号。')}</span></div>
      ) : (
        <div className="betting-slip-items">
          {props.selections.map((item) => (
            <article key={`${item.match_id}:${item.play_type}:${item.option_code}`} className="betting-slip-item">
              <span>{playTypeLabel(item.play_type)}</span>
              <strong>{item.home_team} VS {item.away_team}</strong>
              <div className="betting-slip-pick"><span>{optionLabel(item.play_type, item.option_code)}</span><strong>@ {item.sp_value.toFixed(2)}</strong></div>
              <div className="betting-slip-basis">
                <div><span>{translate('来源')}</span><strong>{item.basis?.source === 'recommendation' ? translate('推荐投注') : translate('手工选号')}</strong></div>
                <button type="button" className="fqp-btn fqp-btn-sm" onClick={() => props.onRemove(item)}>{translate('移除')}</button>
              </div>
            </article>
          ))}
        </div>
      )}
      <div className="betting-summary">
        <h4>{translate('投注确认')}</h4>
        <div><span>{translate('来源')}</span><strong>{source}</strong></div>
        <div><span>{translate('过关方式')}</span><strong>{formatPassTypes(props.selectedPassTypes)}</strong></div>
        <div><span>{translate('倍数')}</span><strong>{props.multiple} {translate('倍')}</strong></div>
        <div><span>{translate('注数')}</span><strong>{props.calculation?.bet_count ?? 0} {translate('注')}</strong></div>
        <div><span>{translate('投注金额')}</span><strong>¥{(props.calculation?.total_cost ?? 0).toFixed(2)}</strong></div>
        <div><span>{translate('理论最高奖金')}</span><strong>¥{(props.calculation?.max_prize ?? 0).toFixed(2)}</strong></div>
      </div>
      {props.warning && <div className="betting-warnings" role="alert">{props.warning}</div>}
      <button type="button" className="betting-submit" disabled={!canConfirm} onClick={props.onConfirm}>
        {props.submitting ? translate('保存中…') : props.calculating ? translate('计算中…') : translate('确认投注')}
      </button>
    </aside>
  );
}
