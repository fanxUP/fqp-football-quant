import type { BetSlipItem, CalculationResult } from '../../core/types';
import { optionLabel } from '../../shared/constants';
import { formatPassTypes } from './model';
import { useLanguage } from '../../app/LanguageContext';

interface BetSlipProps {
  selections: BetSlipItem[];
  selectedMatchCount: number;
  selectedPassTypes: string[];
  availablePassTypes: string[];
  multiple: number;
  calculation: CalculationResult | null;
  calculating: boolean;
  submitting: boolean;
  warning: string;
  detailsOpen: boolean;
  onTogglePassType: (passType: string) => void;
  onMultiple: (multiple: number) => void;
  onToggleDetails: () => void;
  onConfirm: () => void;
}

function passTypeForK(k: number): string {
  return k === 1 ? 'single' : `${k}x1`;
}

function passLabel(k: number, language: 'zh-CN' | 'en', translate: (text: string) => string): string {
  return k === 1 ? translate('单场') : language === 'en' ? `${k} ${translate('关')}` : `${k}${translate('关')}`;
}

export default function BetSlip(props: BetSlipProps) {
  const { language, translate } = useLanguage();
  if (props.selections.length === 0) return null;
  const cost = props.calculation?.total_cost ?? 0;
  const prize = props.calculation?.max_prize ?? 0;
  const overLimit = cost > 20_000;
  return (
    <aside className="sporttery-bet-slip" role="complementary" aria-label={translate('投注单')}>
      <div className="sporttery-slip-summary">
        <div className="selected-count"><strong>{props.selectedMatchCount}</strong><span>{translate('已选')}</span></div>
        <div className="sporttery-summary-copy">
          <div>{translate('共计')}: <strong>{props.calculation?.bet_count ?? 0}</strong> {translate('注')} <strong>{cost.toFixed(2)}</strong> {translate('元')}</div>
          <small>{translate('理论最高奖金')}: <span>{props.calculating ? translate('计算中') : prize.toFixed(2)}</span>{translate('元')}</small>
        </div>
        <button type="button" className="sporttery-detail-button" aria-expanded={props.detailsOpen} onClick={props.onToggleDetails}>{translate('查看')}<br />{translate('明细⌄')}</button>
      </div>
      {props.detailsOpen && (
        <div className="sporttery-slip-details">
          <div className="sporttery-selected-details">
            {props.selections.map((item) => (
              <span key={`${item.match_id}:${item.play_type}:${item.option_code}`}>{optionLabel(item.play_type, item.option_code)} @{item.sp_value.toFixed(2)}</span>
            ))}
          </div>
          <div className="sporttery-pass-grid" role="group" aria-label={translate('过关方式')}>
            {Array.from({ length: 8 }, (_, index) => index + 1).map((k) => {
              const passType = passTypeForK(k);
              const allowed = props.availablePassTypes.includes(passType);
              const selected = props.selectedPassTypes.includes(passType);
              return (
                <button
                  key={passType}
                  type="button"
                  className={selected ? 'is-selected' : ''}
                  disabled={!allowed}
                  aria-pressed={selected}
                  onClick={() => props.onTogglePassType(passType)}
                >{passLabel(k, language, translate)}</button>
              );
            })}
          </div>
        </div>
      )}
      <div className="sporttery-slip-footer">
        <span className="sporttery-current-pass">{props.selectedPassTypes.length > 0 ? `${formatPassTypes(props.selectedPassTypes)}⌃` : translate('请选择过关')}</span>
        <span className="sporttery-multiple-label">{translate('倍数')}</span>
        <button type="button" aria-label={translate('减少倍数')} onClick={() => props.onMultiple(Math.max(1, props.multiple - 1))} disabled={props.multiple <= 1}>−</button>
        <input
          type="number"
          min={1}
          max={50}
          value={props.multiple}
          aria-label={translate('当前倍数')}
          onChange={(event) => {
            const next = Number.parseInt(event.target.value, 10);
            if (Number.isFinite(next)) props.onMultiple(Math.min(50, Math.max(1, next)));
          }}
        />
        <button type="button" aria-label={translate('增加倍数')} onClick={() => props.onMultiple(Math.min(50, props.multiple + 1))} disabled={props.multiple >= 50}>＋</button>
        <button
          type="button"
          className="sporttery-confirm-button"
          onClick={props.onConfirm}
          disabled={props.selectedPassTypes.length === 0 || !props.calculation || props.calculating || props.submitting || overLimit || Boolean(props.warning)}
        >{props.submitting ? translate('保存中') : translate('确定')}</button>
      </div>
      {(props.warning || overLimit) && <div className="sporttery-warning" role="alert">{overLimit ? translate('单票金额不能超过20,000元') : props.warning}</div>}
    </aside>
  );
}
