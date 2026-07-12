import type { BetSlipItem, CalculationResult } from '../../core/types';

interface BetSlipProps {
  selections: BetSlipItem[];
  selectedMatchCount: number;
  passType: string | null;
  availablePassTypes: string[];
  multiple: number;
  calculation: CalculationResult | null;
  calculating: boolean;
  submitting: boolean;
  warning: string;
  detailsOpen: boolean;
  onPassType: (passType: string) => void;
  onMultiple: (multiple: number) => void;
  onToggleDetails: () => void;
  onConfirm: () => void;
}

function passTypeForK(k: number): string {
  return k === 1 ? 'single' : `${k}x1`;
}

function passLabel(k: number): string {
  return k === 1 ? '单场' : `${k}关`;
}

export default function BetSlip(props: BetSlipProps) {
  if (props.selections.length === 0) return null;
  const cost = props.calculation?.total_cost ?? 0;
  const prize = props.calculation?.max_prize ?? 0;
  const overLimit = cost > 20_000;
  return (
    <aside className="sporttery-bet-slip" role="complementary" aria-label="投注单">
      <div className="sporttery-slip-summary">
        <div className="selected-count"><strong>{props.selectedMatchCount}</strong><span>已选</span></div>
        <div className="sporttery-summary-copy">
          <div>共计: <strong>{props.calculation?.bet_count ?? 0}</strong> 注 <strong>{cost.toFixed(2)}</strong> 元</div>
          <small>理论最高奖金: <span>{props.calculating ? '计算中' : prize.toFixed(2)}</span>元</small>
        </div>
        <button type="button" className="sporttery-detail-button" aria-expanded={props.detailsOpen} onClick={props.onToggleDetails}>查看<br />明细⌄</button>
      </div>
      {props.detailsOpen && (
        <div className="sporttery-slip-details">
          <div className="sporttery-selected-details">
            {props.selections.map((item) => (
              <span key={`${item.match_id}:${item.play_type}:${item.option_code}`}>{item.option_name} @{item.sp_value.toFixed(2)}</span>
            ))}
          </div>
          <div className="sporttery-pass-grid" role="group" aria-label="过关方式">
            {Array.from({ length: 8 }, (_, index) => index + 1).map((k) => {
              const passType = passTypeForK(k);
              const allowed = props.availablePassTypes.includes(passType);
              return (
                <button
                  key={passType}
                  type="button"
                  className={props.passType === passType ? 'is-selected' : ''}
                  disabled={!allowed}
                  aria-pressed={props.passType === passType}
                  onClick={() => props.onPassType(passType)}
                >{passLabel(k)}</button>
              );
            })}
          </div>
        </div>
      )}
      <div className="sporttery-slip-footer">
        <span className="sporttery-current-pass">{props.passType === 'single' ? '单场⌃' : props.passType ? `${props.passType.split('x')[0]}关⌃` : '请选择过关'}</span>
        <span className="sporttery-multiple-label">倍数</span>
        <button type="button" aria-label="减少倍数" onClick={() => props.onMultiple(Math.max(1, props.multiple - 1))} disabled={props.multiple <= 1}>−</button>
        <output aria-label="当前倍数">{props.multiple}</output>
        <button type="button" aria-label="增加倍数" onClick={() => props.onMultiple(Math.min(50, props.multiple + 1))} disabled={props.multiple >= 50}>＋</button>
        <button
          type="button"
          className="sporttery-confirm-button"
          onClick={props.onConfirm}
          disabled={!props.passType || !props.calculation || props.calculating || props.submitting || overLimit || Boolean(props.warning)}
        >{props.submitting ? '保存中' : '确定'}</button>
      </div>
      {(props.warning || overLimit) && <div className="sporttery-warning" role="alert">{overLimit ? '单票金额不能超过20,000元' : props.warning}</div>}
    </aside>
  );
}
