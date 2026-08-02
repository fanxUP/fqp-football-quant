import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../core/apiClient';
import { getAvailablePassTypes, getTicketPlayType, type SportteryPlayType } from '../core/bettingRules';
import { navigate } from '../core/router';
import type { BetSlipItem, BettingMatch, BettingOddsOption, CalculationResult, LiveRecommendation, SportterySalesWindow } from '../core/types';
import { ApiError } from '../core/types';
import BetSlip from '../features/betting-terminal/BetSlip';
import {
  AllGamesDialog,
  ConfirmationDialog,
  FilterDialog,
  RulesDialog,
} from '../features/betting-terminal/Dialogs';
import MatchCard from '../features/betting-terminal/MatchCard';
import {
  PLAY_TYPES,
  createSlipItem,
  findMatchingOption,
  selectedMatchCount,
  selectionKey,
  toCalculateItems,
} from '../features/betting-terminal/model';
import {
  RecommendationPanel,
  TicketPreview,
} from '../features/betting-terminal/WorkbenchPanels';
import { useToast } from '../shared/components/Toast';
import { useLanguage } from '../app/LanguageContext';
import '../features/betting-terminal/SportteryBettingTerminal.css';

interface ConfirmationState {
  ticketUid: string;
  calculation: CalculationResult;
  selections: BetSlipItem[];
  passTypes: string[];
  multiple: number;
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : error instanceof Error ? error.message : fallback;
}

function autoPassTypes(availablePassTypes: string[]): string[] {
  const straightPasses = availablePassTypes.filter((passType) => /^\d+x1$/.test(passType));
  if (straightPasses.length > 0) {
    return [straightPasses.reduce((largest, current) => Number(current.split('x')[0]) > Number(largest.split('x')[0]) ? current : largest)];
  }
  return availablePassTypes.includes('single') ? ['single'] : [];
}

export default function BettingTerminalPage() {
  const { translate } = useLanguage();
  const toast = useToast();
  const [matches, setMatches] = useState<BettingMatch[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [salesWindow, setSalesWindow] = useState<SportterySalesWindow | null>(null);
  const [timeMachineMode, setTimeMachineMode] = useState(false);
  const [timeMachineDates, setTimeMachineDates] = useState<Array<{ businessDate: string; matchCount: number }>>([]);
  const [timeMachineDate, setTimeMachineDate] = useState('');
  const [timeMachineMatches, setTimeMachineMatches] = useState<BettingMatch[]>([]);
  const [timeMachineLoading, setTimeMachineLoading] = useState(false);
  const [timeMachineError, setTimeMachineError] = useState('');
  const [timeMachineRefreshToken, setTimeMachineRefreshToken] = useState(0);
  const [recommendations, setRecommendations] = useState<LiveRecommendation[]>([]);
  const [recommendationsLoading, setRecommendationsLoading] = useState(true);
  const [recommendationsError, setRecommendationsError] = useState('');
  const [selections, setSelections] = useState<BetSlipItem[]>([]);
  const [selectedPassTypes, setSelectedPassTypes] = useState<string[]>([]);
  const [passTouched, setPassTouched] = useState(false);
  const [multiple, setMultiple] = useState(1);
  const [calculation, setCalculation] = useState<CalculationResult | null>(null);
  const [calculating, setCalculating] = useState(false);
  const [calculationWarning, setCalculationWarning] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(true);
  const [activeMatch, setActiveMatch] = useState<BettingMatch | null>(null);
  const [showRules, setShowRules] = useState(false);
  const [showFilter, setShowFilter] = useState(false);
  const [league, setLeague] = useState('');
  const [singleOnly, setSingleOnly] = useState(false);
  const [confirmation, setConfirmation] = useState<ConfirmationState | null>(null);
  const calculateRequestRef = useRef(0);

  const resetBetSlip = useCallback(() => {
    calculateRequestRef.current += 1;
    setSelections([]);
    setSelectedPassTypes([]);
    setPassTouched(false);
    setMultiple(1);
    setCalculation(null);
    setCalculating(false);
    setCalculationWarning('');
    setDetailsOpen(true);
  }, []);

  const fetchMatches = useCallback(() => {
    setLoading(true);
    setLoadError('');
    api.bettingTerminal.matches({ limit: 100 })
      .then((response) => {
        // 休市接口会返回空的“当前可售”列表，但页面保留上一批已加载比赛，
        // 让用户继续查看盘口；真正的下注能力由 bettingClosed 统一锁定。
        if ((response.matches || []).length > 0) setMatches(response.matches);
        setSalesWindow(response.sales_window ?? null);
      })
      .catch((error) => setLoadError(errorMessage(error, translate('官方比赛加载失败'))))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { fetchMatches(); }, [fetchMatches]);

  useEffect(() => {
    if (!timeMachineMode) return;
    setTimeMachineLoading(true);
    setTimeMachineError('');
    api.betting.timeMachineDates()
      .then((response) => {
        const dates = response.dates || [];
        setTimeMachineDates(dates);
        setTimeMachineDate((current) => current || dates[0]?.businessDate || '');
      })
      .catch((error) => setTimeMachineError(errorMessage(error, translate('历史业务日加载失败'))))
      .finally(() => setTimeMachineLoading(false));
  }, [timeMachineMode]);

  useEffect(() => {
    if (!timeMachineMode || !timeMachineDate) return;
    setTimeMachineLoading(true);
    setTimeMachineError('');
    api.betting.timeMachineMatches(timeMachineDate)
      .then((response) => setTimeMachineMatches(response.matches || []))
      .catch((error) => setTimeMachineError(errorMessage(error, translate('历史官方比赛加载失败'))))
      .finally(() => setTimeMachineLoading(false));
  }, [timeMachineDate, timeMachineMode, timeMachineRefreshToken]);

  useEffect(() => {
    if (salesWindow?.is_open === false) resetBetSlip();
  }, [resetBetSlip, salesWindow?.is_open]);

  useEffect(() => {
    setRecommendationsLoading(true);
    setRecommendationsError('');
    api.liveRecommendations({ limit: 12, min_ev: -1, min_confidence: 0 })
      .then((response) => setRecommendations(response.recommendations || []))
      .catch((error) => setRecommendationsError(errorMessage(error, translate('推荐投注加载失败'))))
      .finally(() => setRecommendationsLoading(false));
  }, []);

  const activeMatches = timeMachineMode ? timeMachineMatches : matches;
  const bettingClosed = !timeMachineMode && salesWindow?.is_open === false;

  const leagues = useMemo(
    () => [...new Set(activeMatches.map((match) => match.league_name).filter(Boolean))].sort(),
    [activeMatches],
  );

  const filteredMatches = useMemo(
    () => activeMatches.filter((match) => {
      if (league && match.league_name !== league) return false;
      if (!singleOnly) return true;
      return Object.values(match.odds).some((market) => market.options.length > 0 && market.is_single_allowed === true);
    }),
    [activeMatches, league, singleOnly],
  );

  const availablePassTypes = useMemo(
    () => getAvailablePassTypes(selections).filter((item) => item === 'single' || /^\d+x1$/.test(item)),
    [selections],
  );
  const hasPublishedOdds = useMemo(
    () => activeMatches.some((match) => Object.values(match.odds).some((market) => market.options.length > 0)),
    [activeMatches],
  );
  const hasSelectableOfficialMarket = useMemo(
    () => activeMatches.some((match) => Object.values(match.odds).some(
      (market) => market.options.length > 0 && (market.is_single_allowed || market.is_pass_allowed),
    )),
    [activeMatches],
  );
  const matchCount = useMemo(() => selectedMatchCount(selections), [selections]);
  const encodedPassTypes = selectedPassTypes.join(',');
  const availableRecommendationIds = useMemo(() => {
    const ids = new Set<number>();
    recommendations.forEach((recommendation) => {
      const playType = recommendation.play_type as SportteryPlayType;
      if (!PLAY_TYPES.includes(playType)) return;
      const match = activeMatches.find((item) => item.match_id === recommendation.match_id);
      const market = match?.odds[playType];
      const option = market
        ? findMatchingOption(playType, market.options, recommendation.option_code)
        : undefined;
      if (match && market && option && (market.is_single_allowed || market.is_pass_allowed)) {
        ids.add(recommendation.prediction_id);
      }
    });
    return ids;
  }, [activeMatches, recommendations]);

  useEffect(() => {
    if (selections.length === 0) {
      if (selectedPassTypes.length > 0) setSelectedPassTypes([]);
      setPassTouched(false);
      return;
    }
    const validPassTypes = selectedPassTypes.filter((passType) => availablePassTypes.includes(passType));
    if (validPassTypes.length !== selectedPassTypes.length) {
      setSelectedPassTypes(validPassTypes);
      return;
    }
    if (validPassTypes.length === 0 && !passTouched) {
      const nextPassTypes = autoPassTypes(availablePassTypes);
      if (nextPassTypes.length > 0) setSelectedPassTypes(nextPassTypes);
    }
  }, [availablePassTypes, passTouched, selectedPassTypes, selections.length]);

  useEffect(() => {
    const requestId = ++calculateRequestRef.current;
    if (selectedPassTypes.length === 0 || selections.length === 0) {
      setCalculation(null);
      setCalculating(false);
      setCalculationWarning(selections.length > 0 ? '请选择可用的过关方式' : '');
      return;
    }
    setCalculating(true);
    setCalculationWarning('');
    api.bettingTerminal.calculate({ items: toCalculateItems(selections), pass_type: encodedPassTypes, multiple })
      .then((result) => {
        if (requestId === calculateRequestRef.current) setCalculation(result);
      })
      .catch((error) => {
        if (requestId !== calculateRequestRef.current) return;
        setCalculation(null);
        setCalculationWarning(errorMessage(error, '投注计算失败'));
      })
      .finally(() => {
        if (requestId === calculateRequestRef.current) setCalculating(false);
      });
  }, [encodedPassTypes, multiple, selections, selectedPassTypes.length]);

  const toggleSelection = (match: BettingMatch, playType: SportteryPlayType, option: BettingOddsOption) => {
    const key = selectionKey(match.match_id, playType, option.option_code);
    setSelections((current) => {
      const exists = current.some((item) => selectionKey(item.match_id, item.play_type, item.option_code) === key);
      return exists
        ? current.filter((item) => selectionKey(item.match_id, item.play_type, item.option_code) !== key)
        : [...current, createSlipItem(match, playType, option)];
    });
    if (!passTouched) setSelectedPassTypes([]);
  };

  const addRecommendation = (recommendation: LiveRecommendation) => {
    const playType = recommendation.play_type as SportteryPlayType;
    const match = matches.find((item) => item.match_id === recommendation.match_id);
    const market = PLAY_TYPES.includes(playType) ? match?.odds[playType] : undefined;
    const option = market
      ? findMatchingOption(playType, market.options, recommendation.option_code)
      : undefined;
    if (!match || !market || !option || (!market.is_single_allowed && !market.is_pass_allowed)) {
      toast.warning('该推荐当前没有对应的官方可售选项，未加入投注器。');
      return;
    }
    const nextItem: BetSlipItem = {
      ...createSlipItem(match, playType, option),
      basis: {
        source: 'recommendation',
        modelProbability: recommendation.model_probability,
        marketProbability: recommendation.market_probability,
        edge: recommendation.edge,
        ev: recommendation.ev,
        confidence: recommendation.confidence,
        summary: '推荐投注使用当前官方固定奖金入单',
      },
    };
    const key = selectionKey(nextItem.match_id, nextItem.play_type, nextItem.option_code);
    setSelections((current) => {
      const existingIndex = current.findIndex(
        (item) => selectionKey(item.match_id, item.play_type, item.option_code) === key,
      );
      if (existingIndex < 0) return [...current, nextItem];
      const next = [...current];
      next[existingIndex] = nextItem;
      return next;
    });
    if (!passTouched) setSelectedPassTypes([]);
  };

  const removeSelection = (target: BetSlipItem) => {
    const key = selectionKey(target.match_id, target.play_type, target.option_code);
    setSelections((current) => current.filter(
      (item) => selectionKey(item.match_id, item.play_type, item.option_code) !== key,
    ));
  };

  const refresh = () => {
    resetBetSlip();
    setConfirmation(null);
    fetchMatches();
  };

  const completeConfirmation = () => {
    setConfirmation(null);
    resetBetSlip();
  };

  const confirmTicket = async () => {
    if (selectedPassTypes.length === 0 || !calculation || calculation.total_cost > 20_000 || calculationWarning) return;
    setSubmitting(true);
    try {
      const result = timeMachineMode
        ? await api.betting.createTimeMachineTicket({
          business_date: timeMachineDate,
          pass_type: encodedPassTypes,
          multiple,
          selections: selections.map((item) => ({
            match_id: item.match_id, play_type: item.play_type, option_code: item.option_code,
          })),
        })
        : await api.betting.createTicket({
          source: 'real-user',
          play_type: getTicketPlayType(selections),
          pass_type: encodedPassTypes,
          multiple,
          items: toCalculateItems(selections),
        });
      setConfirmation({ ticketUid: result.ticketUid, calculation, selections: [...selections], passTypes: [...selectedPassTypes], multiple });
      toast.success(timeMachineMode ? '历史彩票已补录，并已纳入我的盈亏。' : '投注已保存到我的彩票。');
    } catch (error) {
      toast.error(errorMessage(error, '投注保存失败'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="betting-terminal betting-desktop-workbench">
      <div className="betting-workbench">
        {timeMachineMode ? (
          <aside className="fqp-card time-machine-guide" aria-label={translate('时光机补录说明')}>
            <h3>{translate('时光机补录')}</h3>
            <p>{translate('仅使用体彩官方编号比赛及停售前最后一次官方赔率。补录票会进入比赛结果和我的盈亏。')}</p>
          </aside>
        ) : (
          <RecommendationPanel
            recommendations={recommendations}
            loading={recommendationsLoading}
            error={recommendationsError}
            availableRecommendationIds={availableRecommendationIds}
            onAdd={addRecommendation}
          />
        )}

        <section className="betting-market sporttery-widget-column" aria-label={translate('投注器')}>
          <div className="betting-slip-head betting-market-head">
            <div><h3>{timeMachineMode ? translate('历史投注器') : translate('投注器')}</h3><span>{timeMachineMode ? translate('按历史官方封盘赔率重新录入真实彩票') : translate('可手工选号，也可接收左侧推荐投注')}</span></div>
          </div>
          <section className="sporttery-terminal" role="region" aria-label={translate('竞彩足球模拟试玩投注器')}>
      <div className="sporttery-main">
          <div className="sporttery-toolbar">
          <button type="button" className="sporttery-mode-button" aria-label={translate('混合过关')}>{translate('混合过关')} <span aria-hidden="true">▾</span></button>
          <div className="sporttery-toolbar-actions" aria-label={translate('投注器工具')}>
            <button
              type="button"
              className="sporttery-toolbar-action sporttery-time-machine-action"
              aria-pressed={timeMachineMode}
              onClick={() => { resetBetSlip(); setTimeMachineMode((value) => !value); }}
            >
              <span aria-hidden="true">◷</span> {translate('时光机补录')}
            </button>
            <button
              type="button"
              className="sporttery-toolbar-action"
              aria-label={translate('刷新赔率')}
              aria-busy={timeMachineMode ? timeMachineLoading : loading}
              onClick={timeMachineMode ? () => setTimeMachineRefreshToken((value) => value + 1) : refresh}
            >
              <span className={timeMachineMode ? timeMachineLoading ? 'is-spinning' : '' : loading ? 'is-spinning' : ''} aria-hidden="true">↻</span> {translate('刷新')}
            </button>
            <button type="button" className="sporttery-toolbar-action" aria-expanded={showRules} onClick={() => setShowRules(true)}><span aria-hidden="true">ⓘ</span> {translate('游戏规则')}</button>
            <button type="button" className="sporttery-toolbar-action" aria-expanded={showFilter} onClick={() => setShowFilter(true)}><span aria-hidden="true">⌕</span> {translate('筛选')}</button>
          </div>
        </div>

        {timeMachineMode && (
          <label className="sporttery-time-machine-date">
            <span>{translate('选择原投注业务日')}</span>
            <select aria-label={translate('选择原投注业务日')} value={timeMachineDate} onChange={(event) => { resetBetSlip(); setTimeMachineDate(event.target.value); }} disabled={timeMachineLoading}>
              {timeMachineDates.length === 0 && <option value="">{translate('暂无可补录日期')}</option>}
              {timeMachineDates.map((item) => <option key={item.businessDate} value={item.businessDate}>{item.businessDate} · {item.matchCount} {translate('场')}</option>)}
            </select>
          </label>
        )}

        <BetSlip
          selections={selections}
          selectedMatchCount={matchCount}
          selectedPassTypes={selectedPassTypes}
          availablePassTypes={availablePassTypes}
          multiple={multiple}
          calculation={calculation}
          calculating={calculating}
          submitting={submitting}
          warning={calculationWarning}
          detailsOpen={detailsOpen}
          onTogglePassType={(value) => {
            setPassTouched(true);
            setSelectedPassTypes((current) => availablePassTypes.filter((passType) => (
              passType === value ? !current.includes(passType) : current.includes(passType)
            )));
          }}
          onMultiple={setMultiple}
          onToggleDetails={() => setDetailsOpen((current) => !current)}
          onConfirm={confirmTicket}
        />

        {(timeMachineMode ? timeMachineLoading : loading) && <div className="sporttery-status" role="status">{timeMachineMode ? translate('正在读取历史官方比赛…') : translate('正在读取官方开售比赛…')}</div>}
        {(timeMachineMode ? timeMachineError : loadError) && <div className="sporttery-status is-error" role="alert">{timeMachineMode ? timeMachineError : loadError}<button type="button" onClick={timeMachineMode ? () => setTimeMachineRefreshToken((value) => value + 1) : fetchMatches}>{translate('重试')}</button></div>}
        {!timeMachineMode && !loading && !loadError && salesWindow?.is_open === false && (
          <div className="sporttery-status" role="status">{salesWindow.message}</div>
        )}
        {!(timeMachineMode ? timeMachineLoading : loading) && !(timeMachineMode ? timeMachineError : loadError) && (!timeMachineMode && salesWindow?.is_open === false ? false : filteredMatches.length === 0) && <div className="sporttery-status">{timeMachineMode ? translate('该日没有可补录的官方封盘赔率') : translate('当前筛选条件下没有开售比赛')}</div>}
        {!timeMachineMode && !loading && !loadError && activeMatches.length > 0 && hasPublishedOdds && !hasSelectableOfficialMarket && (
          <div className="sporttery-status" role="status">{translate('官方赔率已发布，但当前未开放单关或过关，请稍后刷新。')}</div>
        )}
        <section className="sporttery-match-list" aria-label={timeMachineMode ? translate('历史官方比赛') : translate('开售比赛')}>
          {filteredMatches.map((match) => (
            <MatchCard
              key={match.match_id}
              match={match}
              selections={selections}
              onToggle={toggleSelection}
              onAllGames={setActiveMatch}
              onAnalyse={(item) => navigate(`/matches/${item.match_id}`)}
              bettingClosed={bettingClosed}
            />
          ))}
        </section>
        {activeMatches.some((match) => Object.values(match.odds).some((market) => market.is_single_allowed)) && (
          <aside className="sporttery-single-tip"><span aria-hidden="true">💡</span><span>{translate('有“单”标记的选项可投单场，其他至少选择2场比赛')}</span></aside>
        )}
        <p className="sporttery-disclaimer">{timeMachineMode ? translate('赔率已锁定为官方停售前最后一次快照，补录后请人工核对票面。') : translate('比赛信息及固定奖金仅供参考，请以出票时刻为准。')}</p>
      </div>

          </section>
        </section>

        <TicketPreview
          selections={selections}
          selectedMatchCount={matchCount}
          selectedPassTypes={selectedPassTypes}
          multiple={multiple}
          calculation={calculation}
          calculating={calculating}
          submitting={submitting}
          warning={calculationWarning}
          onRemove={removeSelection}
          onConfirm={confirmTicket}
        />
      </div>

      {activeMatch && <AllGamesDialog match={activeMatch} selections={selections} onToggle={toggleSelection} onClose={() => setActiveMatch(null)} bettingClosed={bettingClosed} />}
      {showRules && <RulesDialog onClose={() => setShowRules(false)} />}
      {showFilter && <FilterDialog leagues={leagues} league={league} singleOnly={singleOnly} onLeague={setLeague} onSingleOnly={setSingleOnly} onClose={() => setShowFilter(false)} />}
      {confirmation && <ConfirmationDialog selections={confirmation.selections} passTypes={confirmation.passTypes} multiple={confirmation.multiple} betCount={confirmation.calculation.bet_count} stake={confirmation.calculation.total_cost} prize={confirmation.calculation.max_prize} ticketUid={confirmation.ticketUid} onClose={completeConfirmation} />}
    </div>
  );
}
