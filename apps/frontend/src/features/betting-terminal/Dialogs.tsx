import type { BetSlipItem, BettingMatch, BettingOddsOption } from '../../core/types';
import type { SportteryPlayType } from '../../core/bettingRules';
import { optionLabel, playTypeLabel } from '../../shared/constants';
import { displayOption, formatPassTypes, optionAriaLabel, PLAY_LABELS, PLAY_TYPES, selectionKey } from './model';
import ScoreOddsGrid from './ScoreOddsGrid';
import { useLanguage } from '../../app/LanguageContext';

interface AllGamesDialogProps {
  match: BettingMatch;
  selections: BetSlipItem[];
  onToggle: (match: BettingMatch, playType: SportteryPlayType, option: BettingOddsOption) => void;
  onClose: () => void;
  bettingClosed?: boolean;
}

export function AllGamesDialog({ match, selections, onToggle, onClose, bettingClosed = false }: AllGamesDialogProps) {
  const { translate } = useLanguage();
  return (
    <div className="sporttery-dialog-backdrop" role="presentation" onClick={onClose}>
      <section className="sporttery-dialog sporttery-play-dialog" role="dialog" aria-modal="true" aria-label={`${match.match_num_str} ${translate('全部游戏')}`} onClick={(event) => event.stopPropagation()}>
        <div className="sporttery-play-heading">{match.match_num_str}　{match.league_name}　{match.kickoff_time.slice(5, 16).replace('T', ' ')}</div>
        <div className="sporttery-play-teams"><small>{translate('[主]')}</small>{match.home_team_name} <span>{translate('对阵')}</span> {match.away_team_name}</div>
        <div className="sporttery-play-scroll">
          {PLAY_TYPES.map((playType) => {
            const market = match.odds[playType];
            const selectable = market.is_single_allowed === true || market.is_pass_allowed !== false;
            if (market.options.length === 0) return null;
            return (
              <section key={playType} className="sporttery-play-section">
                <h3 aria-label={PLAY_LABELS[playType]}>
                  <span>{PLAY_LABELS[playType]}</span>
                  <span className="sporttery-play-flags">
                    {market.is_single_allowed && <small className="is-single">{translate('单场')}</small>}
                    {market.is_pass_allowed !== false && <small className="is-pass">{translate('过关')}</small>}
                  </span>
                </h3>
                {playType === 'bf' ? (
                  <ScoreOddsGrid
                    options={market.options}
                    selectedOptionCodes={new Set(
                      selections
                        .filter((item) => item.match_id === match.match_id && item.play_type === playType)
                        .map((item) => item.option_code),
                    )}
                    selectable={selectable && !bettingClosed}
                    onToggle={(option) => onToggle(match, playType, option)}
                  />
                ) : (
                  <div className={`sporttery-modal-grid is-${playType}`}>
                    {market.options.map((option) => {
                      const selected = selections.some((item) => selectionKey(item.match_id, item.play_type, item.option_code) === selectionKey(match.match_id, playType, option.option_code));
                      return (
                        <button
                          key={option.option_code}
                          type="button"
                          className={`sporttery-modal-odd ${selected ? 'is-selected' : ''}`}
                          aria-label={optionAriaLabel(playType, option)}
                          aria-pressed={selected}
                          disabled={!selectable || bettingClosed}
                          onClick={() => onToggle(match, playType, option)}
                        >
                          <span>{displayOption(playType, option)}</span>
                          <small>{option.sp_value.toFixed(2)}</small>
                        </button>
                      );
                    })}
                  </div>
                )}
              </section>
            );
          })}
        </div>
        <button type="button" className="sporttery-dialog-close" onClick={onClose}>{translate('关闭')}</button>
      </section>
    </div>
  );
}

export function RulesDialog({ onClose }: { onClose: () => void }) {
  const { translate } = useLanguage();
  return (
    <div className="sporttery-dialog-backdrop" role="presentation" onClick={onClose}>
      <section className="sporttery-dialog" role="dialog" aria-modal="true" aria-label={translate('竞彩足球游戏规则')} onClick={(event) => event.stopPropagation()}>
        <header><h2>{translate('竞彩足球游戏规则')}</h2><button type="button" onClick={onClose} aria-label={translate('关闭')}>×</button></header>
        <div className="sporttery-rules-content">
          <p>{translate('竞猜结果按全场90分钟（含伤停补时）计算，加时赛和点球不计。')}</p>
          <ul>
            <li>{translate('每注2元；页面中的1倍为基础投注，最高50倍。')}</li>
            <li>{translate('单场仅限带“单”标记的比赛；过关需选择2–8场。')}</li>
            <li>{translate('同一场多个选择按复式备选展开，不会彼此串成一注。')}</li>
            <li>{translate('胜平负/让球最多8关，总进球最多6关，比分/半全场最多4关。')}</li>
            <li>{translate('单票金额不得超过20,000元。')}</li>
            <li>{translate('单注奖金上限：单场10万元，2–3场20万元，4–5场50万元，6场及以上100万元；倍数另计。')}</li>
          </ul>
        </div>
        <button type="button" className="sporttery-dialog-close" onClick={onClose}>{translate('知道了')}</button>
      </section>
    </div>
  );
}

interface FilterDialogProps {
  leagues: string[];
  league: string;
  singleOnly: boolean;
  onLeague: (league: string) => void;
  onSingleOnly: (singleOnly: boolean) => void;
  onClose: () => void;
}

export function FilterDialog({ leagues, league, singleOnly, onLeague, onSingleOnly, onClose }: FilterDialogProps) {
  const { translate } = useLanguage();
  return (
    <div className="sporttery-dialog-backdrop" role="presentation" onClick={onClose}>
      <section className="sporttery-dialog" role="dialog" aria-modal="true" aria-label={translate('筛选比赛')} onClick={(event) => event.stopPropagation()}>
        <header><h2>{translate('筛选比赛')}</h2><button type="button" onClick={onClose} aria-label={translate('关闭')}>×</button></header>
        <label className="sporttery-field-label">
          <span>{translate('联赛')}</span>
          <select aria-label={translate('联赛')} value={league} onChange={(event) => onLeague(event.target.value)}>
            <option value="">{translate('全部赛事')}</option>
            {leagues.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
        <label className="sporttery-check-row">
          <input type="checkbox" checked={singleOnly} onChange={(event) => onSingleOnly(event.target.checked)} />
          {translate('仅看可单场投注')}
        </label>
        <button type="button" className="sporttery-dialog-close" onClick={onClose}>{translate('完成')}</button>
      </section>
    </div>
  );
}

interface ConfirmationDialogProps {
  selections: BetSlipItem[];
  passTypes: string[];
  multiple: number;
  betCount: number;
  stake: number;
  prize: number;
  ticketUid: string;
  onClose: () => void;
}

export function ConfirmationDialog(props: ConfirmationDialogProps) {
  const { translate } = useLanguage();
  return (
    <div className="sporttery-dialog-backdrop" role="presentation" onClick={props.onClose}>
      <section className="sporttery-dialog" role="dialog" aria-modal="true" aria-label={translate('模拟投注明细')} onClick={(event) => event.stopPropagation()}>
        <header><h2>{translate('模拟投注明细')}</h2><button type="button" onClick={props.onClose} aria-label={translate('关闭')}>×</button></header>
        <div className="sporttery-confirm-body">
          <p className="sporttery-saved">{translate('已保存到我的彩票')} · {props.ticketUid}</p>
          <p><strong>{new Set(props.selections.map((item) => item.match_id)).size} {translate('场')} / {props.selections.length} {translate('项')}</strong></p>
          <ol>{props.selections.map((item) => <li key={selectionKey(item.match_id, item.play_type, item.option_code)}>{item.home_team} {translate('对阵')} {item.away_team} {playTypeLabel(item.play_type)} {optionLabel(item.play_type, item.option_code)} @{item.sp_value.toFixed(2)}</li>)}</ol>
          <p>{translate('过关方式')}：{formatPassTypes(props.passTypes)}<br />{translate('倍数')}：{props.multiple}{translate('倍')}<br />{translate('注数')}：{props.betCount}{translate('注')}<br />{translate('模拟金额')}：{props.stake.toFixed(2)}{translate('元')}<br />{translate('理论最高奖金')}：{props.prize.toFixed(2)}{translate('元')}</p>
        </div>
        <button type="button" className="sporttery-dialog-close" onClick={props.onClose}>{translate('完成')}</button>
      </section>
    </div>
  );
}
