import type { BetSlipItem, BettingMatch, BettingOddsOption } from '../../core/types';
import type { SportteryPlayType } from '../../core/bettingRules';
import {
  displayOption,
  formatHandicap,
  isStartingSoon,
  matchDateTime,
  matchTime,
  optionAriaLabel,
  PLAY_LABELS,
  selectedForMatch,
  selectionKey,
} from './model';
import { useLanguage } from '../../app/LanguageContext';

interface MatchCardProps {
  match: BettingMatch;
  selections: BetSlipItem[];
  onToggle: (match: BettingMatch, playType: SportteryPlayType, option: BettingOddsOption) => void;
  onAllGames: (match: BettingMatch) => void;
  onAnalyse: (match: BettingMatch) => void;
  bettingClosed?: boolean;
}

function MarketFlags({ match, playType }: { match: BettingMatch; playType: 'spf' | 'rqspf' }) {
  const { language, translate } = useLanguage();
  const market = match.odds[playType];
  const single = market.is_single_allowed === true;
  const pass = market.is_pass_allowed !== false;
  return (
    <span
      className="sporttery-market-flags"
      aria-label={`${PLAY_LABELS[playType]}${language === 'en' ? ' ' : ''}${translate(single ? '支持单场' : '不支持单场')}${language === 'en' ? ', ' : '，'}${translate(pass ? '支持过关' : '不支持过关')}`}
    >
      <span className={single ? 'is-single' : ''}>{single ? '单' : '−'}</span>
      <span className={pass ? 'is-pass' : ''}>{pass ? '过' : '−'}</span>
    </span>
  );
}

function OddsRow({
  match,
  playType,
  selections,
  onToggle,
  bettingClosed = false,
}: MatchCardProps & { playType: 'spf' | 'rqspf' }) {
  const { translate } = useLanguage();
  const options = match.odds[playType].options;
  const market = match.odds[playType];
  const selectable = market.is_single_allowed === true || market.is_pass_allowed !== false;
  return (
    <div className="sporttery-odds-row">
      {options.length === 0 ? (
        <span className="sporttery-market-closed">{translate('未开售')}</span>
      ) : options.map((option) => {
        const selected = selections.some((item) => selectionKey(item.match_id, item.play_type, item.option_code) === selectionKey(match.match_id, playType, option.option_code));
        return (
          <button
            key={option.option_code}
            type="button"
            className={`sporttery-odd ${selected ? 'is-selected' : ''}`}
            aria-label={optionAriaLabel(playType, option)}
            aria-pressed={selected}
            disabled={!selectable || bettingClosed}
            onClick={() => onToggle(match, playType, option)}
          >
            <span>{displayOption(playType, option)}</span>
            <strong>{option.sp_value.toFixed(2)}</strong>
          </button>
        );
      })}
    </div>
  );
}

export default function MatchCard(props: MatchCardProps) {
  const { language, translate } = useLanguage();
  const { match, selections, onAllGames } = props;
  const selectedCount = selectedForMatch(selections, match.match_id);
  const handicap = formatHandicap(match.odds.rqspf.handicap);
  const handicapClass = handicap.startsWith('+') ? 'is-positive' : handicap.startsWith('-') ? 'is-negative' : '';
  return (
    <article className="sporttery-match-card" aria-label={`${match.match_num_str} ${match.home_team_name} ${translate('对')} ${match.away_team_name}`}>
      <div className="sporttery-match-meta">
        <span aria-hidden="true">♟</span>
        <span>{match.match_num_str}</span>
        <span className="sporttery-league">{match.league_name}</span>
        {isStartingSoon(match) && <span className="sporttery-start-soon">{translate('即将开赛')}</span>}
        <time dateTime={match.kickoff_time} title={matchDateTime(match)}>{matchTime(match)}</time>
      </div>
      <div className="sporttery-teams-row">
        <span className="sporttery-home-tag">{translate('[主]')} ★</span>
        <div className="sporttery-teams">
          <strong>{match.home_team_name}</strong><small>{translate('对阵')}</small><strong>{match.away_team_name}</strong><span aria-hidden="true"> ★</span>
        </div>
        <button type="button" className="sporttery-analyse" aria-label={`${translate('查看')}${match.home_team_name} ${translate('对阵')} ${match.away_team_name}${translate('分析')}`} onClick={() => props.onAnalyse(match)}>{translate('析')}</button>
      </div>
      <div className="sporttery-quick-games">
        <div className="sporttery-goal-stack" aria-label={translate('让球数')}>
          <span>−</span>
          <span className={handicapClass}>{handicap}</span>
        </div>
        <div className="sporttery-market-stack">
          <MarketFlags match={match} playType="spf" />
          <MarketFlags match={match} playType="rqspf" />
        </div>
        <div className="sporttery-odds-stack">
          <OddsRow {...props} playType="spf" />
          <OddsRow {...props} playType="rqspf" />
        </div>
        <button
          type="button"
          className="sporttery-all-games"
          aria-label={selectedCount ? language === 'en' ? `${translate('已选')} ${selectedCount} ${translate('项')}` : `${translate('已选')} ${selectedCount}${translate('项')}` : translate('全部游戏')}
          onClick={() => onAllGames(match)}
        >
          {selectedCount ? <><span>{translate('已选')}</span><strong>{selectedCount}{translate('项')}</strong></> : <>{translate('全部')}<br />{translate('游戏')}</>}
        </button>
      </div>
    </article>
  );
}
