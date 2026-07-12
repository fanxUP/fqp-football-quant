import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../core/apiClient';
import { getAvailablePassTypes, getTicketPlayType, type SportteryPlayType } from '../core/bettingRules';
import { navigate } from '../core/router';
import type { BetSlipItem, BettingMatch, BettingOddsOption, CalculationResult } from '../core/types';
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
  createSlipItem,
  selectedMatchCount,
  selectionKey,
  toCalculateItems,
} from '../features/betting-terminal/model';
import { useToast } from '../shared/components/Toast';
import '../features/betting-terminal/SportteryBettingTerminal.css';

interface ConfirmationState {
  ticketUid: string;
  calculation: CalculationResult;
  selections: BetSlipItem[];
  passType: string;
  multiple: number;
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : error instanceof Error ? error.message : fallback;
}

function autoPassType(items: BetSlipItem[], availablePassTypes: string[]): string | null {
  const straightPasses = availablePassTypes.filter((passType) => /^\d+x1$/.test(passType));
  if (straightPasses.length > 0) {
    return straightPasses.reduce((largest, current) => Number(current.split('x')[0]) > Number(largest.split('x')[0]) ? current : largest);
  }
  return availablePassTypes.includes('single') ? 'single' : null;
}

export default function BettingTerminalPage() {
  const toast = useToast();
  const [matches, setMatches] = useState<BettingMatch[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [selections, setSelections] = useState<BetSlipItem[]>([]);
  const [passType, setPassType] = useState<string | null>(null);
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

  const fetchMatches = useCallback(() => {
    setLoading(true);
    setLoadError('');
    api.bettingTerminal.matches({ limit: 100 })
      .then((response) => setMatches(response.matches || []))
      .catch((error) => setLoadError(errorMessage(error, '官方比赛加载失败')))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { fetchMatches(); }, [fetchMatches]);

  const leagues = useMemo(
    () => [...new Set(matches.map((match) => match.league_name).filter(Boolean))].sort(),
    [matches],
  );

  const filteredMatches = useMemo(
    () => matches.filter((match) => {
      if (league && match.league_name !== league) return false;
      if (!singleOnly) return true;
      return Object.values(match.odds).some((market) => market.options.length > 0 && market.is_single_allowed === true);
    }),
    [matches, league, singleOnly],
  );

  const availablePassTypes = useMemo(
    () => getAvailablePassTypes(selections).filter((item) => item === 'single' || /^\d+x1$/.test(item)),
    [selections],
  );
  const matchCount = useMemo(() => selectedMatchCount(selections), [selections]);

  useEffect(() => {
    if (selections.length === 0) {
      setPassType(null);
      setPassTouched(false);
      return;
    }
    if (passType && availablePassTypes.includes(passType)) return;
    const nextPassType = autoPassType(selections, availablePassTypes);
    setPassType(nextPassType);
    if (!nextPassType) setPassTouched(false);
  }, [availablePassTypes, passType, selections]);

  useEffect(() => {
    const requestId = ++calculateRequestRef.current;
    if (!passType || selections.length === 0) {
      setCalculation(null);
      setCalculating(false);
      setCalculationWarning(passType ? '' : selections.length > 0 ? '请选择可用的过关方式' : '');
      return;
    }
    setCalculating(true);
    setCalculationWarning('');
    api.bettingTerminal.calculate({ items: toCalculateItems(selections), pass_type: passType, multiple })
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
  }, [multiple, passType, selections]);

  const toggleSelection = (match: BettingMatch, playType: SportteryPlayType, option: BettingOddsOption) => {
    const key = selectionKey(match.match_id, playType, option.option_code);
    setSelections((current) => {
      const exists = current.some((item) => selectionKey(item.match_id, item.play_type, item.option_code) === key);
      return exists
        ? current.filter((item) => selectionKey(item.match_id, item.play_type, item.option_code) !== key)
        : [...current, createSlipItem(match, playType, option)];
    });
    if (!passTouched) setPassType(null);
  };

  const refresh = () => {
    setSelections([]);
    setPassType(null);
    setPassTouched(false);
    setMultiple(1);
    setConfirmation(null);
    fetchMatches();
  };

  const confirmTicket = async () => {
    if (!passType || !calculation || calculation.total_cost > 20_000 || calculationWarning) return;
    setSubmitting(true);
    try {
      const result = await api.betting.createTicket({
        source: 'real-user',
        play_type: getTicketPlayType(selections),
        pass_type: passType,
        multiple,
        items: toCalculateItems(selections),
      });
      setConfirmation({ ticketUid: result.ticketUid, calculation, selections: [...selections], passType, multiple });
      toast.success('投注已保存到我的彩票。');
    } catch (error) {
      toast.error(errorMessage(error, '投注保存失败'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="sporttery-terminal" role="region" aria-label="竞彩足球模拟试玩投注器">
      <header className="sporttery-hero">
        <div className="sporttery-hero-title">
          <span aria-hidden="true">⚽</span>
          <div><h2>竞彩足球</h2><small>模拟试玩</small></div>
          <button type="button" aria-label="刷新赔率" onClick={refresh}>↻</button>
        </div>
        <nav aria-label="竞彩玩法"><span>胜平负</span><span>4场进球</span><strong>竞彩足球</strong><span>竞彩篮球</span></nav>
      </header>

      <div className="sporttery-main">
        <div className="sporttery-toolbar">
          <button type="button" className="sporttery-mode-button" aria-label="混合过关">混合过关 <span aria-hidden="true">▾</span></button>
          <div><button type="button" onClick={() => setShowRules(true)}>游戏规则</button><button type="button" onClick={() => setShowFilter(true)}>筛选</button></div>
        </div>

        {loading && <div className="sporttery-status" role="status">正在读取官方开售比赛…</div>}
        {loadError && <div className="sporttery-status is-error" role="alert">{loadError}<button type="button" onClick={fetchMatches}>重试</button></div>}
        {!loading && !loadError && filteredMatches.length === 0 && <div className="sporttery-status">当前筛选条件下没有开售比赛</div>}
        <section className="sporttery-match-list" aria-label="开售比赛">
          {filteredMatches.map((match) => (
            <MatchCard
              key={match.match_id}
              match={match}
              selections={selections}
              onToggle={toggleSelection}
              onAllGames={setActiveMatch}
              onAnalyse={(item) => navigate(`/matches/${item.match_id}`)}
            />
          ))}
        </section>
        {matches.some((match) => Object.values(match.odds).some((market) => market.is_single_allowed)) && (
          <aside className="sporttery-single-tip"><span aria-hidden="true">💡</span><span>有“单”标记的选项可投单场，其他至少选择2场比赛</span></aside>
        )}
        <p className="sporttery-disclaimer">比赛信息及固定奖金仅供参考，请以出票时刻为准。</p>
      </div>

      <BetSlip
        selections={selections}
        selectedMatchCount={matchCount}
        passType={passType}
        availablePassTypes={availablePassTypes}
        multiple={multiple}
        calculation={calculation}
        calculating={calculating}
        submitting={submitting}
        warning={calculationWarning}
        detailsOpen={detailsOpen}
        onPassType={(value) => { setPassType(value); setPassTouched(true); }}
        onMultiple={setMultiple}
        onToggleDetails={() => setDetailsOpen((current) => !current)}
        onConfirm={confirmTicket}
      />

      {activeMatch && <AllGamesDialog match={activeMatch} selections={selections} onToggle={toggleSelection} onClose={() => setActiveMatch(null)} />}
      {showRules && <RulesDialog onClose={() => setShowRules(false)} />}
      {showFilter && <FilterDialog leagues={leagues} league={league} singleOnly={singleOnly} onLeague={setLeague} onSingleOnly={setSingleOnly} onClose={() => setShowFilter(false)} />}
      {confirmation && <ConfirmationDialog selections={confirmation.selections} passType={confirmation.passType} multiple={confirmation.multiple} betCount={confirmation.calculation.bet_count} stake={confirmation.calculation.total_cost} prize={confirmation.calculation.max_prize} ticketUid={confirmation.ticketUid} onClose={() => setConfirmation(null)} />}
    </section>
  );
}
