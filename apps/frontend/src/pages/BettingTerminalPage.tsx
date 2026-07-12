import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from 'react';
import { api } from '../core/apiClient';
import { mapOcrTicketToSlip, type OcrUnmatchedItem } from '../core/ocrTicketMapping';
import {
  getAvailablePassTypes,
  getPassTypeBetCount,
  getPassTypesBetCount,
  getPlayRule,
  getSelectionKey,
  getSlipWarnings,
  getTicketPlayType,
  SPORTTERY_PLAY_RULES,
  STAKE_UNIT,
  WAGER_SOURCE_OPTIONS,
  type SportteryPlayType,
} from '../core/bettingRules';
import { ApiError } from '../core/types';
import type {
  BetSlipItem,
  BettingMatch,
  BettingOddsOption,
  CalculationResult,
  LiveRecommendation,
  TicketOcrResult,
} from '../core/types';
import ErrorState from '../shared/components/ErrorState';
import LoadingSpinner from '../shared/components/LoadingSpinner';
import { useToast } from '../shared/components/Toast';
import { optionLabel, PASS_TYPE_LABELS } from '../shared/constants';
import TeamName from '../shared/components/TeamName';

type PlayTabKey = 'spf-rqspf' | Exclude<SportteryPlayType, 'spf' | 'rqspf'>;

const PLAY_TABS: Array<{ key: PlayTabKey; label: string }> = [
  { key: 'spf-rqspf', label: '胜负平/让球' },
  { key: 'zjq', label: SPORTTERY_PLAY_RULES.zjq.shortLabel },
  { key: 'bf', label: SPORTTERY_PLAY_RULES.bf.shortLabel },
  { key: 'bqc', label: SPORTTERY_PLAY_RULES.bqc.shortLabel },
];

const WIN_DRAW_LOSS_ORDER = ['3', 'h', '1', 'd', '0', 'a'];

function orderedWinDrawLossOptions(options: BettingOddsOption[]): BettingOddsOption[] {
  return [...options].sort((a, b) => {
    const left = WIN_DRAW_LOSS_ORDER.indexOf(a.option_code);
    const right = WIN_DRAW_LOSS_ORDER.indexOf(b.option_code);
    if (left === -1 && right === -1) return 0;
    if (left === -1) return 1;
    if (right === -1) return -1;
    return left - right;
  });
}

function displaySportteryOptionName(playType: string, option: Pick<BettingOddsOption, 'option_code' | 'option_name'>): string {
  if (playType === 'spf' || playType === 'rqspf') {
    return optionLabel(playType, option.option_code);
  }
  return option.option_name;
}

function money(value: number): string {
  return value.toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function clockLabel(value: string): string {
  if (!value) return '--:--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.slice(11, 16) || value;
  return date.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

function businessDateKey(match: BettingMatch): string {
  if (match.business_date) return match.business_date;
  if (!match.kickoff_time) return '未定日期';
  const date = new Date(match.kickoff_time);
  if (Number.isNaN(date.getTime())) return match.kickoff_time.slice(0, 10) || '未定日期';
  return date.toISOString().slice(0, 10);
}

function dateHeaderLabel(dateKey: string, count: number): string {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(dateKey)) {
    return `${dateKey} 有${count}场比赛`;
  }
  const date = new Date(`${dateKey}T12:00:00`);
  const weekday = Number.isNaN(date.getTime())
    ? ''
    : ` 周${['日', '一', '二', '三', '四', '五', '六'][date.getDay()]}`;
  return `${dateKey}${weekday} 有${count}场比赛（比赛编号日期 ${dateKey.replace(/-/g, '').slice(2)}）`;
}

function formatPassType(passType: string): string {
  if (passType === 'single') return PASS_TYPE_LABELS[passType] || '单关';
  return passType.replace('x', '×');
}

function parsePassTypes(passType: string | undefined): string[] {
  const parsed = (passType || 'single')
    .split(',')
    .map((type) => type.trim())
    .filter(Boolean);
  return parsed.length > 0 ? parsed : ['single'];
}

function serializePassTypes(passTypes: string[]): string {
  return passTypes.join(',');
}

function formatPassTypes(passTypes: string[]): string {
  if (passTypes.length === 0) return '待选择';
  return passTypes.map(formatPassType).join(' + ');
}

function getAutoPassTypes(items: BetSlipItem[], availablePassTypes: string[]): string[] {
  if (items.length === 0) return [];
  const parlayPasses = availablePassTypes.filter((type) => type !== 'single');
  const straightPasses = parlayPasses.filter((type) => type.endsWith('x1'));
  if (straightPasses.length > 0) {
    return [straightPasses.reduce((largest, type) => Number(type.split('x')[0]) > Number(largest.split('x')[0]) ? type : largest)];
  }
  if (parlayPasses.length > 0) return [parlayPasses[0]];
  return availablePassTypes.includes('single') ? ['single'] : [];
}

function buildSubmitItems(betSlip: BetSlipItem[]) {
  return betSlip.map((item) => ({
    match_id: item.match_id,
    play_type: item.play_type,
    option_code: item.option_code,
    option_name: item.option_name,
    sp_value: item.sp_value,
    handicap: item.handicap ?? undefined,
    is_dan: item.is_dan,
  }));
}

function pct(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

export function calculateSentimentWeight({
  edge,
  ev,
  confidence,
}: Pick<LiveRecommendation, 'edge' | 'ev' | 'confidence'>): number {
  const normalizedEdge = Math.max(-0.2, Math.min(0.2, edge)) / 0.2;
  const normalizedEv = Math.max(-0.5, Math.min(0.5, ev)) / 0.5;
  const confidenceOffset = (Math.max(0, Math.min(1, confidence)) - 0.5) * 2;
  const score = 50 + normalizedEdge * 18 + normalizedEv * 14 + confidenceOffset * 12;
  return Math.round(Math.max(0, Math.min(100, score)));
}

export default function BettingTerminalPage() {
  const toast = useToast();
  const [matches, setMatches] = useState<BettingMatch[]>([]);
  const [matchesLoading, setMatchesLoading] = useState(true);
  const [matchesError, setMatchesError] = useState<string | null>(null);
  const [recommendations, setRecommendations] = useState<LiveRecommendation[]>([]);
  const [recommendationsLoading, setRecommendationsLoading] = useState(true);
  const [recommendationsError, setRecommendationsError] = useState<string | null>(null);
  const [filterDate, setFilterDate] = useState('');
  const [filterLeague, setFilterLeague] = useState('');
  const [activePlayType, setActivePlayType] = useState<PlayTabKey>('spf-rqspf');
  const [allGamesMatch, setAllGamesMatch] = useState<BettingMatch | null>(null);
  const [betSlip, setBetSlip] = useState<BetSlipItem[]>([]);
  const [selectedPassTypes, setSelectedPassTypes] = useState<string[]>([]);
  const [passSelectionMode, setPassSelectionMode] = useState<'auto' | 'manual'>('auto');
  const [multiple, setMultiple] = useState(1);
  const [notes, setNotes] = useState('');
  const [calcResult, setCalcResult] = useState<CalculationResult | null>(null);
  const [calcLoading, setCalcLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [ocrResult, setOcrResult] = useState<TicketOcrResult | null>(null);
  const [ocrMatchedCount, setOcrMatchedCount] = useState(0);
  const [ocrUnmatched, setOcrUnmatched] = useState<OcrUnmatchedItem[]>([]);
  const [ocrLoading, setOcrLoading] = useState(false);
  const [ocrError, setOcrError] = useState<string | null>(null);
  const calcTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const calcAbortRef = useRef<AbortController | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const fetchMatches = useCallback(() => {
    setMatchesLoading(true);
    setMatchesError(null);
    api.bettingTerminal
      .matches({ date: filterDate || undefined, league_name: filterLeague || undefined, limit: 100 })
      .then((res) => {
        setMatches(res.matches);
        setMatchesLoading(false);
      })
      .catch((e) => {
        setMatchesError(e instanceof ApiError ? e.message : '加载比赛失败');
        setMatchesLoading(false);
      });
  }, [filterDate, filterLeague]);

  useEffect(() => {
    fetchMatches();
  }, [fetchMatches]);

  useEffect(() => {
    setRecommendationsLoading(true);
    setRecommendationsError(null);
    api.liveRecommendations({ limit: 12, min_ev: 0.02, min_confidence: 0.45 })
      .then((res) => {
        setRecommendations(res.recommendations || []);
        setRecommendationsLoading(false);
      })
      .catch((e) => {
        setRecommendationsError(e instanceof ApiError ? e.message : '推荐单加载失败');
        setRecommendationsLoading(false);
      });
  }, []);

  const normalizedPassTypes = useMemo(() => selectedPassTypes, [selectedPassTypes]);

  const serializedPassType = useMemo(() => serializePassTypes(normalizedPassTypes), [normalizedPassTypes]);

  const availablePassTypes = useMemo(() => getAvailablePassTypes(betSlip), [betSlip]);

  const localGroupCount = useMemo(
    () => getPassTypesBetCount(betSlip, normalizedPassTypes),
    [betSlip, normalizedPassTypes],
  );

  const localTotalCost = useMemo(
    () => localGroupCount * STAKE_UNIT * multiple,
    [localGroupCount, multiple],
  );

  const isDanAvailable = normalizedPassTypes.some((passType) => passType !== 'single');

  useEffect(() => {
    setSelectedPassTypes((current) => {
      if (betSlip.length === 0) {
        if (passSelectionMode !== 'auto') setPassSelectionMode('auto');
        return current.length === 0 ? current : [];
      }

      const filtered = current.filter((type) => availablePassTypes.includes(type));
      if (passSelectionMode === 'manual' && filtered.length > 0) {
        return filtered.length === current.length && filtered.every((type, index) => type === current[index])
          ? current
          : filtered;
      }

      if (passSelectionMode === 'manual') setPassSelectionMode('auto');
      const auto = getAutoPassTypes(betSlip, availablePassTypes);
      return auto.length === current.length && auto.every((type, index) => type === current[index]) ? current : auto;
    });
  }, [availablePassTypes, betSlip, passSelectionMode]);

  useEffect(() => {
    if (betSlip.length === 0) {
      setCalcResult(null);
      setCalcLoading(false);
      return;
    }

    if (normalizedPassTypes.length === 0) {
      setCalcResult(null);
      setCalcLoading(false);
      return;
    }

    setCalcLoading(true);
    if (calcTimerRef.current) clearTimeout(calcTimerRef.current);
    calcTimerRef.current = setTimeout(() => {
      if (calcAbortRef.current) calcAbortRef.current.abort();
      const controller = new AbortController();
      calcAbortRef.current = controller;

      const activePassTypes = normalizedPassTypes.filter((type) => availablePassTypes.includes(type));
      if (activePassTypes.length === 0) {
        setCalcResult(null);
        setCalcLoading(false);
        return;
      }

      Promise.all(
        activePassTypes.map((type) =>
          api.bettingTerminal.calculate({ items: buildSubmitItems(betSlip), pass_type: type, multiple }),
        ),
      )
        .then((results) => {
          if (!controller.signal.aborted) {
            const primary = results[0];
            const combined: CalculationResult = {
              ...primary,
              pass_type: serializePassTypes(results.map((result) => result.pass_type)),
              bet_count: results.reduce((sum, result) => sum + result.bet_count, 0),
              total_cost: results.reduce((sum, result) => sum + result.total_cost, 0),
              max_prize: results.reduce((sum, result) => sum + result.max_prize, 0),
              combinations: results.flatMap((result) => result.combinations),
              available_pass_types: primary.available_pass_types,
            };
            setCalcResult(combined);
            setCalcLoading(false);
          }
        })
        .catch(() => {
          if (!controller.signal.aborted) {
            setCalcResult(null);
            setCalcLoading(false);
          }
        });
    }, 250);

    return () => {
      if (calcTimerRef.current) clearTimeout(calcTimerRef.current);
    };
  }, [betSlip, normalizedPassTypes, availablePassTypes, multiple]);

  const leagues = useMemo(() => {
    return Array.from(new Set(matches.map((match) => match.league_name).filter(Boolean))).sort();
  }, [matches]);

  const groupedMatches = useMemo(() => {
    const groups = new Map<string, BettingMatch[]>();
    matches.forEach((match) => {
      const key = businessDateKey(match);
      const list = groups.get(key) ?? [];
      list.push(match);
      groups.set(key, list);
    });
    return Array.from(groups.entries()).sort(([left], [right]) => left.localeCompare(right));
  }, [matches]);

  const slipWarnings = useMemo(
    () => Array.from(new Set(normalizedPassTypes.flatMap((passType) => getSlipWarnings(betSlip, passType)))),
    [betSlip, normalizedPassTypes],
  );

  const activeSource = WAGER_SOURCE_OPTIONS[0];
  const currentRule =
    activePlayType === 'spf-rqspf'
      ? {
          label: '胜负平/让球',
          maxMatches: SPORTTERY_PLAY_RULES.spf.maxMatches,
          settlementBasis: '上排为胜平负，下排为让球胜平负，按官方赛果与让球数分别结算。',
        }
      : SPORTTERY_PLAY_RULES[activePlayType];
  const slipSourceLabel = betSlip.some((item) => item.basis?.source === 'recommendation')
    ? '推荐单'
    : ocrResult?.ticket_image_url
      ? 'OCR 识别'
      : '手工选号';

  const addToSlip = (
    match: BettingMatch,
    playType: SportteryPlayType,
    option: BettingOddsOption,
  ) => {
    const existingIdx = betSlip.findIndex((item) => item.match_id === match.match_id);
    const nextItem: BetSlipItem = {
      match_id: match.match_id,
      home_team: match.home_team_name,
      away_team: match.away_team_name,
      league_name: match.league_name,
      kickoff_time: match.kickoff_time,
      play_type: playType,
      play_type_label: getPlayRule(playType).label,
      option_code: option.option_code,
      option_name: displaySportteryOptionName(playType, option),
      sp_value: option.sp_value,
      handicap: playType === 'rqspf' ? (match.odds.rqspf?.handicap ?? null) : undefined,
      is_single_allowed: match.odds[playType]?.is_single_allowed === true,
      is_dan: false,
      basis: {
        source: 'manual',
        summary: `${getPlayRule(playType).label}手工选号`,
      },
    };

    if (existingIdx >= 0) {
      if (betSlip[existingIdx].play_type === playType && betSlip[existingIdx].option_code === option.option_code) {
        setBetSlip(betSlip.filter((_, itemIndex) => itemIndex !== existingIdx));
        return;
      }
      const updated = [...betSlip];
      updated[existingIdx] = nextItem;
      setBetSlip(updated);
      return;
    }
    setBetSlip([...betSlip, nextItem]);
  };

  const addRecommendationToSlip = (recommendation: LiveRecommendation) => {
    const playType = recommendation.play_type as SportteryPlayType;
    const matched = matches.find((match) => match.match_id === recommendation.match_id);
    const matchedOption = matched?.odds[playType]?.options.find(
      (option) => option.option_code === recommendation.option_code,
    );
    const nextItem: BetSlipItem = {
      match_id: recommendation.match_id,
      home_team: matched?.home_team_name ?? recommendation.home_team,
      away_team: matched?.away_team_name ?? recommendation.away_team,
      league_name: matched?.league_name ?? recommendation.league,
      kickoff_time: matched?.kickoff_time ?? recommendation.kickoff_time ?? '',
      play_type: recommendation.play_type,
      play_type_label: recommendation.play_type_name || getPlayRule(recommendation.play_type).label,
      option_code: recommendation.option_code,
      option_name: displaySportteryOptionName(playType, matchedOption ?? recommendation),
      sp_value: matchedOption?.sp_value ?? recommendation.fair_odds,
      handicap: playType === 'rqspf' ? (matched?.odds.rqspf?.handicap ?? null) : undefined,
      is_single_allowed: matched?.odds[playType]?.is_single_allowed === true,
      is_dan: false,
      basis: {
        source: 'recommendation',
        modelProbability: recommendation.model_probability,
        marketProbability: recommendation.market_probability,
        edge: recommendation.edge,
        ev: recommendation.ev,
        confidence: recommendation.confidence,
        sentimentWeight: calculateSentimentWeight(recommendation),
        summary: '模型优势、市场概率差、市场热度与互联网情绪代理权重综合入单',
      },
    };

    const existingIdx = betSlip.findIndex((item) => item.match_id === nextItem.match_id);
    if (existingIdx >= 0) {
      const updated = [...betSlip];
      updated[existingIdx] = nextItem;
      setBetSlip(updated);
      return;
    }
    setBetSlip([...betSlip, nextItem]);
  };

  const removeFromSlip = (index: number) => {
    setBetSlip(betSlip.filter((_, itemIndex) => itemIndex !== index));
  };

  const toggleDan = (index: number) => {
    if (!isDanAvailable) return;
    const updated = [...betSlip];
    updated[index] = { ...updated[index], is_dan: !updated[index].is_dan };
    setBetSlip(updated);
  };

  const togglePassType = (passType: string) => {
    setPassSelectionMode('manual');
    if (selectedPassTypes.includes(passType)) {
      if (selectedPassTypes.length === 1) return;
      setSelectedPassTypes(selectedPassTypes.filter((type) => type !== passType));
      return;
    }
    setSelectedPassTypes([...selectedPassTypes, passType]);
  };

  const clearSlip = () => {
    setBetSlip([]);
    setCalcResult(null);
    setSelectedPassTypes([]);
    setPassSelectionMode('auto');
  };

  const clearOcr = () => {
    setOcrResult(null);
    setOcrMatchedCount(0);
    setOcrUnmatched([]);
    setOcrError(null);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const handleOcrUpload = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    const allowed = ['image/png', 'image/jpeg', 'image/jpg', 'image/webp'];
    if (file.type && !allowed.includes(file.type)) {
      setOcrError('不支持的文件格式，请选择 PNG、JPG 或 WEBP 图片');
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      setOcrError('文件过大，最大支持 10MB');
      return;
    }

    setOcrLoading(true);
    setOcrError(null);
    try {
      const result = await api.betting.ocrUpload(file);
      setOcrResult(result);
      const mapping = mapOcrTicketToSlip(result, matches);
      setOcrMatchedCount(mapping.mapped.length);
      setOcrUnmatched(mapping.unmatched);
      if (mapping.mapped.length > 0) {
        setBetSlip((current) => {
          const next = [...current];
          for (const mapped of mapping.mapped) {
            const existingIndex = next.findIndex(
              (item) => getSelectionKey(item.match_id, item.play_type) === getSelectionKey(mapped.match_id, mapped.play_type),
            );
            if (existingIndex >= 0) {
              next[existingIndex] = mapped;
            } else {
              next.push(mapped);
            }
          }
          return next;
        });
      }
      if (result.pass_type) {
        const nextPassTypes = parsePassTypes(result.pass_type).filter((type) => getAvailablePassTypes(mapping.mapped).includes(type));
        setSelectedPassTypes(nextPassTypes);
        setPassSelectionMode(nextPassTypes.length > 0 ? 'manual' : 'auto');
      }
      if (result.multiple && Number.isFinite(result.multiple)) {
        setMultiple(Math.min(99, Math.max(1, result.multiple)));
      }
      if (result.success) {
        toast.success(`OCR 已投射到投注器：自动匹配 ${mapping.mapped.length} 场，请核对后确认投注。`);
      } else {
        toast.warning('OCR 未识别到完整票面，仍可作为票据图片保存。');
      }
    } catch (e) {
      const message = e instanceof ApiError ? e.message : 'OCR 上传失败';
      setOcrError(message);
      toast.error(message);
    } finally {
      setOcrLoading(false);
    }
  };

  const handleSubmit = async () => {
    if (betSlip.length === 0 || normalizedPassTypes.length === 0 || !calcResult || slipWarnings.length > 0) return;

    setSubmitting(true);
    try {
      await api.betting.createTicket({
        source: activeSource.code,
        play_type: getTicketPlayType(betSlip),
        pass_type: serializedPassType,
        multiple,
        items: buildSubmitItems(betSlip),
        notes,
        ticket_no: ocrResult?.ticket_no,
        ticket_image_url: ocrResult?.ticket_image_url,
        ocr_status: ocrResult?.ticket_image_url ? 'recognized' : undefined,
      });
      toast.success('投注已确认，可在彩票台账查看。');
      clearSlip();
      clearOcr();
      setNotes('');
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : '投注失败');
    } finally {
      setSubmitting(false);
    }
  };

  const renderOddButton = (
    match: BettingMatch,
    playType: SportteryPlayType,
    option: BettingOddsOption,
  ) => {
    const displayName = displaySportteryOptionName(playType, option);
    const selected = betSlip.some(
      (item) =>
        item.match_id === match.match_id &&
        item.play_type === playType &&
        item.option_code === option.option_code,
    );
    return (
      <button
        key={`${playType}-${option.option_code}`}
        type="button"
        className={`betting-odd betting-odd-${option.option_code} ${selected ? 'is-selected' : ''}`}
        onClick={() => addToSlip(match, playType, option)}
        aria-pressed={selected}
        aria-label={`${displayName}${option.sp_value.toFixed(2)}`}
      >
        <span>{displayName}</span>
        <strong>{option.sp_value.toFixed(2)}</strong>
      </button>
    );
  };

  const renderSinglePlayOdds = (match: BettingMatch, playType: SportteryPlayType) => {
    const group = match.odds[playType];
    if (!group?.options?.length) {
      return <div className="betting-odds-empty">未开售</div>;
    }

    const options = playType === 'spf' || playType === 'rqspf'
      ? orderedWinDrawLossOptions(group.options)
      : group.options;

    return (
      <div className="betting-odds-grid" data-play-type={playType}>
        {options.map((option) => renderOddButton(match, playType, option))}
      </div>
    );
  };

  const renderCombinedWinDrawLossOdds = (match: BettingMatch) => {
    const spfOptions = match.odds.spf?.options ?? [];
    const rqspfOptions = match.odds.rqspf?.options ?? [];
    if (spfOptions.length === 0 && rqspfOptions.length === 0) {
      return <div className="betting-odds-empty">未开售</div>;
    }

    const rqspfHandicap = match.odds.rqspf?.handicap ?? null;
    const formatHandicap = (value: number | null | undefined) => {
      if (value === undefined || value === null || value === 0) return '-';
      return value > 0 ? `+${value}` : String(value);
    };
    const renderSaleMarker = (singleAllowed: boolean | undefined, handicap: string, label: string) => (
      <div
        className={`betting-sale-marker ${singleAllowed ? 'is-single' : 'is-no-single'} ${handicap.startsWith('+') ? 'is-positive' : handicap.startsWith('-') ? 'is-negative' : ''}`}
        aria-label={`${label}${singleAllowed ? '支持单关' : '不支持单关'}，支持过关，让球${handicap}`}
      >
        <div className="betting-sale-flag" aria-hidden="true">
          <span>{singleAllowed ? '单' : '-'}</span>
          <em>过</em>
        </div>
        <strong>{handicap}</strong>
      </div>
    );

    return (
      <div className="betting-combined-odds" aria-label="胜负平/让球赔率">
        <div className="betting-market-line">
          {renderSaleMarker(match.odds.spf?.is_single_allowed, '-', '胜平负')}
          <div className="betting-odds-grid" data-play-type="spf">
            {spfOptions.length > 0
              ? orderedWinDrawLossOptions(spfOptions).map((option) => renderOddButton(match, 'spf', option))
              : <div className="betting-odds-empty">胜平负未开售</div>}
          </div>
        </div>
        <div className="betting-market-line">
          {renderSaleMarker(match.odds.rqspf?.is_single_allowed, formatHandicap(rqspfHandicap), '让球胜平负')}
          <div className="betting-odds-grid" data-play-type="rqspf">
            {rqspfOptions.length > 0
              ? orderedWinDrawLossOptions(rqspfOptions).map((option) => renderOddButton(match, 'rqspf', option))
              : <div className="betting-odds-empty">让球未开售</div>}
          </div>
        </div>
        <button type="button" className="betting-all-games" onClick={() => setAllGamesMatch(match)}>
          全部<br />游戏
        </button>
      </div>
    );
  };

  const renderOdds = (match: BettingMatch) => {
    if (activePlayType === 'spf-rqspf') {
      return renderCombinedWinDrawLossOdds(match);
    }
    return renderSinglePlayOdds(match, activePlayType);
  };

  return (
    <div className="betting-terminal">
      <header className="betting-mobile-header">
        <button type="button" aria-label="返回" className="betting-mobile-back">‹</button>
        <strong>模拟试投</strong>
        <span className="betting-mobile-actions" aria-hidden="true">•••　◎</span>
      </header>
      <nav className="betting-mobile-nav" aria-label="玩法导航">
        {['胜平负', '让球胜平负', '半全场', '进球数', '竞彩足球', '竞彩篮'].map((label) => (
          <span key={label} className={label === '竞彩足球' ? 'is-active' : ''}>{label}</span>
        ))}
        <span aria-hidden="true">☰　▣</span>
      </nav>
      <div className="betting-workbench">
        <aside className="betting-recommendations" aria-label="推荐单">
          <div className="betting-slip-head">
            <div>
              <h3>推荐单</h3>
              <span>按深度分析生成</span>
            </div>
          </div>
          {recommendationsError ? (
            <ErrorState message={recommendationsError} />
          ) : recommendationsLoading ? (
            <LoadingSpinner text="加载推荐单..." />
          ) : recommendations.length === 0 ? (
            <div className="betting-slip-empty">
              <strong>暂无推荐</strong>
              <span>当分析模块产生正 EV 信号后会进入这里。</span>
            </div>
          ) : (
            <div className="betting-recommendation-list">
              {recommendations.map((recommendation) => {
                const sentimentWeight = calculateSentimentWeight(recommendation);
                const recommendationOptionName = displaySportteryOptionName(recommendation.play_type, recommendation);
                return (
                  <article key={recommendation.prediction_id} className="betting-recommendation-card">
                    <div className="betting-recommendation-head">
                      <span>{recommendation.match_num_str || recommendation.league}</span>
                      <strong style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <TeamName name={recommendation.home_team} size={18} />{' vs '}<TeamName name={recommendation.away_team} size={18} />
                      </strong>
                    </div>
                    <div className="betting-recommendation-pick">
                      <span>{recommendation.play_type_name}</span>
                      <strong>{recommendationOptionName} @{recommendation.fair_odds.toFixed(2)}</strong>
                    </div>
                    <div className="betting-recommendation-metrics">
                      <span>模型 {pct(recommendation.model_probability)}</span>
                      <span>市场 {pct(recommendation.market_probability)}</span>
                      <span>EV {recommendation.ev.toFixed(3)}</span>
                      <span>情绪 {sentimentWeight}</span>
                    </div>
                    <button
                      type="button"
                      className="fqp-btn fqp-btn-primary"
                      onClick={() => addRecommendationToSlip(recommendation)}
                    >
                      加入 {recommendationOptionName}
                    </button>
                  </article>
                );
              })}
            </div>
          )}
        </aside>

        <section className="betting-market" aria-label="投注器">
          <div className="betting-slip-head betting-market-head">
            <div>
              <h3>投注器</h3>
              <span>按体彩规则选号、过关、倍数、金额和理论奖金</span>
            </div>
          </div>
          <div className="betting-market-toolbar">
            <div className="betting-filters">
              <input
                type="date"
                className="fqp-input"
                value={filterDate}
                onChange={(event) => setFilterDate(event.target.value)}
                aria-label="筛选日期"
              />
              <select
                className="fqp-select"
                value={filterLeague}
                onChange={(event) => setFilterLeague(event.target.value)}
                aria-label="筛选联赛"
              >
                <option value="">全部联赛</option>
                {leagues.map((league) => (
                  <option key={league} value={league}>{league}</option>
                ))}
              </select>
              <button type="button" className="fqp-btn fqp-btn-primary" onClick={fetchMatches}>
                刷新
              </button>
            </div>
            <div className="betting-rule-note">
              <strong>{currentRule.label}</strong>
              <span>最多{currentRule.maxMatches}场 · {currentRule.settlementBasis}</span>
            </div>
          </div>

          <div className="betting-play-tabs" role="tablist" aria-label="竞彩玩法">
            {PLAY_TABS.map((tab) => {
              return (
                <button
                  key={tab.key}
                  type="button"
                  role="tab"
                  aria-selected={activePlayType === tab.key}
                  className={`betting-play-tab ${activePlayType === tab.key ? 'is-active' : ''}`}
                  onClick={() => setActivePlayType(tab.key)}
                >
                  {tab.label}
                </button>
              );
            })}
          </div>

          <div className={`betting-builder-panel ${betSlip.length > 0 ? 'has-selections' : 'is-empty'}`} aria-label="投注方案设置">
            <div className="betting-builder-head">
              <div>
                <strong>方案设置</strong>
                <span>{betSlip.length > 0 ? `已选 ${betSlip.length} 场` : '先点击赔率加入方案'}</span>
              </div>
              <button type="button" className="fqp-btn fqp-btn-sm" onClick={clearSlip} disabled={betSlip.length === 0}>
                清空方案
              </button>
            </div>

            {betSlip.length > 0 && (
              <div className="betting-builder-picks">
                {betSlip.map((item, index) => (
                  <div key={`${item.match_id}-${item.play_type}`} className="betting-builder-pick">
                    <div>
                      <span>{item.play_type_label}</span>
                      <strong style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <TeamName name={item.home_team} size={18} />{' vs '}<TeamName name={item.away_team} size={18} />
                      </strong>
                    </div>
                    <div className="betting-builder-pick-value">
                      <span>{item.option_name} @{item.sp_value.toFixed(2)}</span>
                      <button
                        type="button"
                        onClick={() => toggleDan(index)}
                        aria-pressed={item.is_dan}
                        disabled={!isDanAvailable}
                        title={isDanAvailable ? '胆码会出现在每一组过关组合中' : '单关不支持设胆'}
                      >
                        {item.is_dan ? '胆' : '设胆'}
                      </button>
                      <button type="button" onClick={() => removeFromSlip(index)}>
                        删除
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}

            <div className="betting-builder-controls">
              <div className="betting-pass-control">
                <span>过关方式</span>
                <div className="betting-pass-buttons" role="group" aria-label="过关方式">
                  {availablePassTypes.map((type) => (
                    <button
                      key={type}
                      type="button"
                      role="checkbox"
                      aria-checked={normalizedPassTypes.includes(type)}
                      aria-pressed={normalizedPassTypes.includes(type)}
                      aria-label={formatPassType(type)}
                      className={normalizedPassTypes.includes(type) ? 'is-active' : ''}
                      onClick={() => togglePassType(type)}
                      disabled={betSlip.length === 0}
                    >
                      <span>{formatPassType(type)}</span>
                      <small>{getPassTypeBetCount(betSlip, type)}组</small>
                    </button>
                  ))}
                  {availablePassTypes.length === 0 && (
                    <span className="betting-pass-empty">先选择赔率</span>
                  )}
                </div>
              </div>

              <label className="betting-builder-field">
                <span>倍数</span>
                <div className="betting-stepper">
                  <button type="button" onClick={() => setMultiple(Math.max(1, multiple - 1))} disabled={multiple <= 1}>-</button>
                  <input
                    type="number"
                    className="fqp-input"
                    min={1}
                    max={99}
                    value={multiple}
                    onChange={(event) => {
                      const next = Number.parseInt(event.target.value, 10);
                      if (Number.isFinite(next)) setMultiple(Math.min(99, Math.max(1, next)));
                    }}
                    aria-label="投注倍数"
                  />
                  <button type="button" onClick={() => setMultiple(Math.min(99, multiple + 1))} disabled={multiple >= 99}>+</button>
                </div>
              </label>

              <label className="betting-builder-field betting-builder-notes">
                <span>备注</span>
                <input
                  type="text"
                  className="fqp-input"
                  value={notes}
                  onChange={(event) => setNotes(event.target.value)}
                  placeholder="策略、场景或票据编号"
                  aria-label="方案备注"
                />
              </label>
            </div>

            <div className="betting-ocr-box">
              <div className="betting-ocr-head">
                <span>OCR 识别</span>
                {ocrResult && (
                  <button type="button" className="fqp-btn fqp-btn-sm" onClick={clearOcr}>
                    移除
                  </button>
                )}
              </div>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/png,image/jpeg,image/webp"
                onChange={handleOcrUpload}
                disabled={ocrLoading}
                aria-label="上传彩票图片进行 OCR 识别"
              />
              {ocrLoading && <small>正在识别票据...</small>}
              {ocrError && <small className="betting-ocr-error">{ocrError}</small>}
              {ocrResult && (
                <div className="betting-ocr-result">
                  <span>{ocrResult.success ? '已投射到投注器' : '已保存图片凭证'}</span>
                  <strong>{ocrResult.ticket_no || ocrResult.filename || '未识别票号'}</strong>
                  <small>
                    识别 {ocrResult.items?.length ?? 0} 场 · 已匹配 {ocrMatchedCount} 场
                    {ocrUnmatched.length > 0 ? ` · 待核对 ${ocrUnmatched.length} 场` : ''}
                    {ocrResult.total_amount ? ` · 票面 ¥${money(ocrResult.total_amount)}` : ''}
                  </small>
                  {ocrUnmatched.length > 0 && (
                    <div className="betting-ocr-unmatched">
                      {ocrUnmatched.slice(0, 3).map((item) => (
                        <small key={`${item.label}-${item.reason}`}>{item.label}：{item.reason}</small>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>

          {matchesError ? (
            <ErrorState message={matchesError} onRetry={fetchMatches} />
          ) : matchesLoading && matches.length === 0 ? (
            <LoadingSpinner text="加载官方在售赛事..." />
          ) : matches.length === 0 ? (
            <div className="betting-empty">暂无在售比赛</div>
          ) : (
            <div className="betting-match-list">
              {groupedMatches.map(([dateKey, dateMatches]) => (
                <section key={dateKey} className="betting-match-day" aria-label={dateHeaderLabel(dateKey, dateMatches.length)}>
                  <div className="betting-match-day-head">
                    <strong>{dateHeaderLabel(dateKey, dateMatches.length)}</strong>
                    <span>⌃</span>
                  </div>
                  {dateMatches.map((match) => (
                    <article key={match.match_id} className="betting-match-row">
                      <div className="betting-match-meta">
                        <span>{match.match_num_str || `#${match.match_id}`}</span>
                        <span>{match.league_name}</span>
                        <span>{clockLabel(match.kickoff_time)}</span>
                      </div>
                      <div className="betting-teams">
                        <span>[主]</span>
                        <TeamName name={match.home_team_name} style={{ fontWeight: 700 }} />
                        <em>VS</em>
                        <TeamName name={match.away_team_name} style={{ fontWeight: 700 }} />
                      </div>
                      {renderOdds(match)}
                    </article>
                  ))}
                </section>
              ))}
            </div>
          )}
        </section>

        <aside className={`betting-slip ${betSlip.length > 0 ? 'has-selections' : 'is-empty'}`} aria-label="投注单">
          <div className="betting-slip-head">
            <div>
              <h3>投注单</h3>
              <span>{betSlip.length} 场</span>
            </div>
          </div>

          {betSlip.length === 0 ? (
            <div className="betting-slip-empty">
              <strong>等待投注器生成确认</strong>
              <span>在中间投注器完成选号、过关和倍数后，这里会同步确认信息。</span>
            </div>
          ) : (
            <div className="betting-slip-items">
              {betSlip.map((item, index) => (
                <div key={`${item.match_id}-${item.play_type}`} className="betting-slip-item">
                  <div>
                    <span>{item.play_type_label}</span>
                    <strong style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <TeamName name={item.home_team} size={18} />{' vs '}<TeamName name={item.away_team} size={18} />
                    </strong>
                  </div>
                  <div className="betting-slip-pick">
                    <span>{item.option_name}</span>
                    <strong>@ {item.sp_value.toFixed(2)}</strong>
                  </div>
                  {item.basis && (
                    <div className="betting-slip-basis">
                      <div>
                        <span>玩法</span>
                        <strong>{item.play_type_label}</strong>
                      </div>
                      <div>
                        <span>单注金额</span>
                        <strong>¥{money(STAKE_UNIT * multiple)}</strong>
                      </div>
                      {item.basis.source === 'recommendation' && (
                        <>
                          <div>
                            <span>模型 {pct(item.basis.modelProbability ?? 0)}</span>
                            <span>市场 {pct(item.basis.marketProbability ?? 0)}</span>
                          </div>
                          <div>
                            <span>Edge {pct(item.basis.edge ?? 0)}</span>
                            <span>EV {(item.basis.ev ?? 0).toFixed(3)}</span>
                          </div>
                          <div>
                            <span>情绪权重</span>
                            <strong>{item.basis.sentimentWeight}</strong>
                          </div>
                          <small>{item.basis.summary}</small>
                        </>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {slipWarnings.length > 0 && (
            <div className="betting-warnings">
              {slipWarnings.map((warning) => (
                <div key={warning}>{warning}</div>
              ))}
            </div>
          )}

          <div className="betting-summary">
            <h4>投注确认</h4>
            <div>
              <span>归属</span>
              <strong>我的彩票</strong>
            </div>
            <div>
              <span>来源</span>
              <strong>{slipSourceLabel}</strong>
            </div>
            {ocrResult?.ticket_no && (
              <div>
                <span>票号</span>
                <strong>{ocrResult.ticket_no}</strong>
              </div>
            )}
            <div>
              <span>过关方式</span>
              <strong>{formatPassTypes(normalizedPassTypes)}</strong>
            </div>
            <div>
              <span>组合数</span>
              <strong>{localGroupCount} 组</strong>
            </div>
            <div>
              <span>胆码</span>
              <strong>{betSlip.filter((item) => item.is_dan).length} 场</strong>
            </div>
            <div>
              <span>倍数</span>
              <strong>{multiple} 倍</strong>
            </div>
            <div>
              <span>注数</span>
              <strong>{localGroupCount} 注</strong>
            </div>
            <div>
              <span>投注金额</span>
              <strong>¥{money(localTotalCost)}</strong>
            </div>
            <div>
              <span>理论最高奖金</span>
              <strong>¥{money(calcResult?.max_prize ?? 0)}</strong>
            </div>
            <small>{STAKE_UNIT}元/注 · {formatPassTypes(normalizedPassTypes)} · 赛后按官方赛果结算</small>
          </div>

          <button
            type="button"
            className="betting-submit"
            onClick={handleSubmit}
            disabled={
              submitting ||
              calcLoading ||
              betSlip.length === 0 ||
              normalizedPassTypes.length === 0 ||
              !calcResult ||
              slipWarnings.length > 0
            }
          >
            {submitting ? '提交中...' : calcLoading ? '计算中...' : activeSource.submitLabel}
          </button>
        </aside>
      </div>

      {allGamesMatch && (
        <div className="betting-all-games-backdrop" role="presentation" onClick={() => setAllGamesMatch(null)}>
          <section className="betting-all-games-modal" role="dialog" aria-modal="true" aria-label="全部游戏" onClick={(event) => event.stopPropagation()}>
            <header className="betting-all-games-modal-head">
              <div>
                <strong>{allGamesMatch.match_num_str || `#${allGamesMatch.match_id}`}　{allGamesMatch.home_team_name} VS {allGamesMatch.away_team_name}</strong>
                <span>{allGamesMatch.league_name} · {clockLabel(allGamesMatch.kickoff_time)}</span>
              </div>
              <button type="button" aria-label="关闭全部游戏" onClick={() => setAllGamesMatch(null)}>×</button>
            </header>
            <div className="betting-all-games-content">
              <section><h4>胜平负</h4>{renderSinglePlayOdds(allGamesMatch, 'spf')}</section>
              <section><h4>让球胜平负</h4>{renderSinglePlayOdds(allGamesMatch, 'rqspf')}</section>
              <section><h4>比分</h4>{renderSinglePlayOdds(allGamesMatch, 'bf')}</section>
              <section><h4>总进球数</h4>{renderSinglePlayOdds(allGamesMatch, 'zjq')}</section>
              <section><h4>半全场</h4>{renderSinglePlayOdds(allGamesMatch, 'bqc')}</section>
            </div>
            <button type="button" className="betting-all-games-close" onClick={() => setAllGamesMatch(null)}>关闭</button>
          </section>
        </div>
      )}
    </div>
  );
}
