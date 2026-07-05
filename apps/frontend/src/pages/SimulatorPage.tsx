import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../core/apiClient';
import { ApiError } from '../core/types';
import type {
  BankrollSummary,
  BetSlipItem,
  CalculationResult,
  SimulatorMatch,
} from '../core/types';
import PageHeader from '../shared/components/PageHeader';
import Card from '../shared/components/Card';
import ErrorState from '../shared/components/ErrorState';
import LoadingSpinner from '../shared/components/LoadingSpinner';
import { useToast } from '../shared/components/Toast';
import DisclaimerBanner from '../shared/components/DisclaimerBanner';
import { PLAY_TYPE_LABELS, PASS_TYPE_LABELS } from '../shared/constants';

// Count-up animation component
function CountUp({ value, duration = 600 }: { value: number; duration?: number }) {
  const [display, setDisplay] = useState(0);
  useEffect(() => {
    let rafId: number;
    const start = performance.now();
    const animate = (now: number) => {
      const elapsed = now - start;
      const t = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - t, 3); // easeOutCubic
      setDisplay(Math.round(value * eased));
      if (t < 1) rafId = requestAnimationFrame(animate);
    };
    rafId = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(rafId);
  }, [value, duration]);
  return <span>{display.toFixed(2)}</span>;
}

type PlayTypeKey = 'spf' | 'rqspf' | 'zjq' | 'bf' | 'bqc';

export default function SimulatorPage() {
  const toast = useToast();

  // Matches
  const [matches, setMatches] = useState<SimulatorMatch[]>([]);
  const [matchesLoading, setMatchesLoading] = useState(true);
  const [matchesError, setMatchesError] = useState<string | null>(null);
  const [filterDate, setFilterDate] = useState('');
  const [filterLeague, setFilterLeague] = useState('');

  // Bet slip
  const [betSlip, setBetSlip] = useState<BetSlipItem[]>([]);
  const [passType, setPassType] = useState('single');
  const [multiple, setMultiple] = useState(1);

  // Calculation
  const [calcResult, setCalcResult] = useState<CalculationResult | null>(null);
  const [calcLoading, setCalcLoading] = useState(false);

  // Bankroll
  const [bankroll, setBankroll] = useState<BankrollSummary | null>(null);

  // Submitting
  const [submitting, setSubmitting] = useState(false);
  const [notes, setNotes] = useState('');

  // Active play type tab for match list
  const [activePlayType, setActivePlayType] = useState<PlayTypeKey>('spf');

  // Fetch matches
  const fetchMatches = useCallback(() => {
    setMatchesLoading(true);
    setMatchesError(null);
    api.simulator
      .matches({ date: filterDate || undefined, league_name: filterLeague || undefined, limit: 50 })
      .then((res) => {
        setMatches(res.matches);
        setMatchesLoading(false);
      })
      .catch((e) => {
        setMatchesError(e instanceof ApiError ? e.message : '加载比赛失败');
        setMatchesLoading(false);
      });
  }, [filterDate, filterLeague]);

  // Fetch bankroll
  const fetchBankroll = useCallback(() => {
    api.simulator.bankroll.summary().then(setBankroll).catch(() => {});
  }, []);

  useEffect(() => {
    fetchMatches();
    fetchBankroll();
  }, [fetchMatches, fetchBankroll]);

  // Debounced calculation — waits 300ms after last change before calling API.
  // Uses AbortController to cancel stale in-flight requests.
  const calcTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const calcAbortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (betSlip.length === 0) {
      setCalcResult(null);
      setCalcLoading(false);
      return;
    }

    setCalcLoading(true);

    // Debounce: wait 300ms before firing
    if (calcTimerRef.current) clearTimeout(calcTimerRef.current);
    calcTimerRef.current = setTimeout(() => {
      // Abort any previous in-flight request
      if (calcAbortRef.current) calcAbortRef.current.abort();
      const controller = new AbortController();
      calcAbortRef.current = controller;

      const items = betSlip.map((item) => ({
        match_id: item.match_id,
        play_type: item.play_type,
        option_code: item.option_code,
        option_name: item.option_name,
        sp_value: item.sp_value,
        handicap: item.handicap ?? undefined,
        is_dan: item.is_dan,
      }));

      api.simulator
        .calculate({ items, pass_type: passType, multiple })
        .then((res) => {
          if (!controller.signal.aborted) {
            setCalcResult(res);
            setCalcLoading(false);
          }
        })
        .catch(() => {
          if (!controller.signal.aborted) {
            setCalcResult(null);
            setCalcLoading(false);
          }
        });
    }, 300);

    return () => {
      if (calcTimerRef.current) clearTimeout(calcTimerRef.current);
    };
  }, [betSlip, passType, multiple]);

  // Get unique leagues for filter
  const leagues = useMemo(() => {
    const s = new Set(matches.map((m) => m.league_name).filter(Boolean));
    return Array.from(s).sort();
  }, [matches]);

  // Add match to bet slip
  const addToSlip = (match: SimulatorMatch, playType: PlayTypeKey, option: { option_code: string; option_name: string; sp_value: number }) => {
    // Check if already in slip
    const existingIdx = betSlip.findIndex(
      (item) => item.match_id === match.match_id && item.play_type === playType,
    );
    if (existingIdx >= 0) {
      // Update the existing item's option
      const updated = [...betSlip];
      updated[existingIdx] = {
        ...updated[existingIdx],
        option_code: option.option_code,
        option_name: option.option_name,
        sp_value: option.sp_value,
      };
      setBetSlip(updated);
      return;
    }

    const newItem: BetSlipItem = {
      match_id: match.match_id,
      home_team: match.home_team_name,
      away_team: match.away_team_name,
      league_name: match.league_name,
      kickoff_time: match.kickoff_time,
      play_type: playType,
      play_type_label: PLAY_TYPE_LABELS[playType] || playType,
      option_code: option.option_code,
      option_name: option.option_name,
      sp_value: option.sp_value,
      handicap: playType === 'rqspf' ? (match.odds.rqspf?.handicap ?? null) : undefined,
      is_dan: false,
    };
    setBetSlip([...betSlip, newItem]);
  };

  // Remove from slip
  const removeFromSlip = (index: number) => {
    setBetSlip(betSlip.filter((_, i) => i !== index));
  };

  // Toggle dan
  const toggleDan = (index: number) => {
    const updated = [...betSlip];
    updated[index] = { ...updated[index], is_dan: !updated[index].is_dan };
    setBetSlip(updated);
  };

  // Handle submit
  const handleSubmit = async () => {
    if (!calcResult || betSlip.length === 0) return;
    if (bankroll && bankroll.current_balance < calcResult.total_cost) {
      toast.error('虚拟余额不足！');
      return;
    }

    setSubmitting(true);
    try {
      const playTypes = new Set(betSlip.map((i) => i.play_type));
      const overallPlayType = playTypes.size === 1 ? betSlip[0].play_type : 'hhgg';

      const items = betSlip.map((item) => ({
        match_id: item.match_id,
        play_type: item.play_type,
        option_code: item.option_code,
        option_name: item.option_name,
        sp_value: item.sp_value,
        handicap: item.handicap ?? undefined,
        is_dan: item.is_dan,
      }));

      await api.simulator.tickets.create({
        play_type: overallPlayType,
        pass_type: passType,
        multiple,
        items,
        notes,
      });

      toast.success('投注成功！');
      setBetSlip([]);
      setPassType('single');
      setMultiple(1);
      setNotes('');
      setCalcResult(null);
      fetchBankroll();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : '投注失败');
    } finally {
      setSubmitting(false);
    }
  };

  // Track newly added/removed items for animation
  const [enteringIdx, setEnteringIdx] = useState<number | null>(null);
  const [exitingIdx, setExitingIdx] = useState<number | null>(null);
  const prevSlipLen = useRef(betSlip.length);

  useEffect(() => {
    if (betSlip.length > prevSlipLen.current) {
      setEnteringIdx(betSlip.length - 1);
      setTimeout(() => setEnteringIdx(null), 400);
    }
    prevSlipLen.current = betSlip.length;
  }, [betSlip.length]);

  // Wrapped remove with exit animation
  const removeFromSlipAnimated = (index: number) => {
    setExitingIdx(index);
    setTimeout(() => {
      setExitingIdx(null);
      setBetSlip(betSlip.filter((_, i) => i !== index));
    }, 250);
  };

  // Render odds options for a play type
  const renderOddsButtons = (match: SimulatorMatch, pt: PlayTypeKey) => {
    const group = match.odds[pt];
    if (!group || !group.options || group.options.length === 0) {
      return <span className="fqp-text-muted" style={{ fontSize: '12px' }}>暂无赔率</span>;
    }

    return (
      <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
        {group.options.map((opt) => {
          const isSelected = betSlip.some(
            (item) => item.match_id === match.match_id && item.play_type === pt && item.option_code === opt.option_code,
          );
          return (
            <button
              key={opt.option_code}
              className={`fqp-btn ${isSelected ? 'fqp-btn-primary' : 'fqp-btn-sm'}`}
              style={{
                padding: '3px 10px',
                fontSize: '12px',
                background: isSelected ? undefined : 'var(--fqp-bg-tertiary)',
                border: isSelected ? undefined : '1px solid var(--fqp-border)',
                color: isSelected ? undefined : 'var(--fqp-text)',
                cursor: 'pointer',
                animation: isSelected ? 'fqpPopIn 0.3s cubic-bezier(0.34,1.56,0.64,1) both' : undefined,
              }}
              onClick={() => addToSlip(match, pt, opt)}
              title={`${opt.option_name} @ ${opt.sp_value}`}
            >
              {opt.option_name}<br />
              <span style={{ fontWeight: 700, color: 'var(--fqp-accent)' }}>{opt.sp_value}</span>
            </button>
          );
        })}
      </div>
    );
  };

  return (
    <div>
      <PageHeader
        title="⚽ 投注模拟器"
        actions={
          bankroll && (
            <span style={{ fontSize: '14px' }}>
              余额:{' '}
              <strong style={{ color: bankroll.current_balance > 0 ? 'var(--fqp-accent)' : 'var(--fqp-danger)' }}>
                ¥{bankroll.current_balance.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
              </strong>
            </span>
          )
        }
      />
      <p style={{ color: 'var(--fqp-text-muted)', fontSize: '14px', marginTop: '-8px', marginBottom: '16px' }}>
        模拟体彩官方投注终端 — 虚拟资金练习
      </p>

      <DisclaimerBanner text="虚拟投注模拟器。仅用于学习和策略验证，不涉及真实资金交易。赔率来自官方数据。" />

      {/* Main layout: two columns */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 420px', gap: '16px', alignItems: 'start' }}>
        {/* Left: Match list */}
        <Card title="可投注比赛">
          {/* Filters */}
          <div style={{ display: 'flex', gap: '8px', marginBottom: '12px', flexWrap: 'wrap' }}>
            <input
              type="date"
              className="fqp-input"
              value={filterDate}
              onChange={(e) => setFilterDate(e.target.value)}
              style={{ width: '150px' }}
            />
            <select
              className="fqp-select"
              value={filterLeague}
              onChange={(e) => setFilterLeague(e.target.value)}
              style={{ width: '150px' }}
            >
              <option value="">全部联赛</option>
              {leagues.map((l) => (
                <option key={l} value={l}>{l}</option>
              ))}
            </select>
            <button className="fqp-btn fqp-btn-primary" onClick={fetchMatches}>
              刷新
            </button>
          </div>

          {/* Play type tabs */}
          <div style={{ display: 'flex', gap: '4px', marginBottom: '12px', flexWrap: 'wrap' }}>
            {(Object.keys(PLAY_TYPE_LABELS) as PlayTypeKey[]).map((pt) => (
              <button
                key={pt}
                className={`fqp-btn ${activePlayType === pt ? 'fqp-btn-primary' : 'fqp-btn-sm'}`}
                style={{ padding: '4px 10px', fontSize: '12px' }}
                onClick={() => setActivePlayType(pt)}
              >
                {PLAY_TYPE_LABELS[pt]}
              </button>
            ))}
          </div>

          {matchesError ? (
            <ErrorState message={matchesError} onRetry={fetchMatches} />
          ) : matchesLoading && matches.length === 0 ? (
            <LoadingSpinner text="加载比赛中..." />
          ) : matches.length === 0 ? (
            <div className="fqp-empty-state">
              <div className="fqp-empty-icon">📭</div>
              <div className="fqp-empty-desc">暂无在售比赛</div>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '600px', overflowY: 'auto' }}>
              {matches.map((match, idx) => {
                const handicap = match.odds.rqspf?.handicap;
                const handicapLabel = handicap
                  ? (handicap > 0 ? `(+${handicap})` : `(${handicap})`)
                  : '';

                return (
                  <div
                    key={`${match.match_id}-${activePlayType}`}
                    style={{
                      padding: '10px 12px',
                      border: '1px solid var(--fqp-border)',
                      borderRadius: '6px',
                      background: 'var(--fqp-bg-secondary)',
                      animation: `fqpCardEnter 0.4s ease both`,
                      animationDelay: `${idx * 40}ms`,
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                      <div>
                        <span style={{ fontSize: '11px', color: 'var(--fqp-text-muted)', marginRight: '6px' }}>
                          {match.league_name}
                        </span>
                        <span style={{ fontSize: '12px', color: 'var(--fqp-text-muted)' }}>
                          {match.kickoff_time?.slice(11, 16) || ''}
                        </span>
                      </div>
                      <span style={{ fontSize: '11px', color: 'var(--fqp-text-muted)' }}>
                        #{match.match_id}
                      </span>
                    </div>
                    <div style={{ fontWeight: 600, marginBottom: '8px', fontSize: '14px' }}>
                      {match.home_team_name} {activePlayType === 'rqspf' && handicapLabel ? <span style={{fontSize:'12px',color:'var(--fqp-accent)'}}>{handicapLabel}</span> : null} vs {match.away_team_name}
                    </div>
                    {renderOddsButtons(match, activePlayType)}
                  </div>
                );
              })}
            </div>
          )}
        </Card>

        {/* Right: Bet slip */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          {/* Selected matches */}
          <Card title={`投注单 (${betSlip.length}场)`}>
            {betSlip.length === 0 ? (
              <div style={{ color: 'var(--fqp-text-muted)', fontSize: '13px', padding: '12px 0' }}>
                点击左侧比赛的赔率按钮，将比赛添加到投注单
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {betSlip.map((item, idx) => (
                  <div
                    key={`${item.match_id}-${item.play_type}`}
                    style={{
                      padding: '8px 10px',
                      border: '1px solid var(--fqp-border)',
                      borderRadius: '4px',
                      background: 'var(--fqp-bg-tertiary)',
                      fontSize: '13px',
                      animation: enteringIdx === idx
                        ? 'fqpSlideInLeft 0.35s cubic-bezier(0.34,1.56,0.64,1) both'
                        : exitingIdx === idx
                        ? 'fqpSlideInLeft 0.25s ease-in reverse both'
                        : undefined,
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                      <div>
                        <span style={{ fontSize: '11px', color: 'var(--fqp-text-muted)', marginRight: '6px' }}>[{item.play_type_label}]</span>
                        <span style={{ fontWeight: 600 }}>
                          {item.home_team} vs {item.away_team}
                        </span>
                      </div>
                      <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
                        <button
                          className="fqp-btn fqp-btn-sm"
                          style={{ padding: '1px 6px', fontSize: '11px' }}
                          onClick={() => toggleDan(idx)}
                          title={item.is_dan ? '取消胆材' : '设为胆材'}
                        >
                          {item.is_dan ? '⭐' : '☆'}
                        </button>
                        <button
                          className="fqp-btn fqp-btn-sm"
                          style={{ padding: '1px 6px', fontSize: '11px', color: 'var(--fqp-danger)' }}
                          onClick={() => removeFromSlipAnimated(idx)}
                        >
                          ✕
                        </button>
                      </div>
                    </div>
                    <div>
                      <span style={{ color: 'var(--fqp-accent)', fontWeight: 700 }}>
                        {item.option_name}
                      </span>
                      <span style={{ color: 'var(--fqp-text-muted)', marginLeft: '6px' }}>
                        @ {item.sp_value}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>

          {/* Pass type & multiple */}
          {betSlip.length > 0 && (
            <Card title="过关设置">
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                {/* Pass type */}
                <div>
                  <label className="fqp-label">过关方式</label>
                  <select
                    className="fqp-select"
                    value={passType}
                    onChange={(e) => setPassType(e.target.value)}
                    style={{ width: '100%' }}
                  >
                    {calcResult?.available_pass_types?.map((pt) => (
                      <option key={pt} value={pt}>
                        {PASS_TYPE_LABELS[pt] || pt}
                      </option>
                    )) || (
                      <option value={passType}>{PASS_TYPE_LABELS[passType] || passType}</option>
                    )}
                  </select>
                  {calcResult && (
                    <div style={{ fontSize: '11px', color: 'var(--fqp-text-muted)', marginTop: '4px' }}>
                      {calcResult.bet_count}注 × 2元 × {multiple}倍
                    </div>
                  )}
                </div>

                {/* Multiple */}
                <div>
                  <label className="fqp-label">倍数</label>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <button
                      className="fqp-btn fqp-btn-sm"
                      onClick={() => setMultiple(Math.max(1, multiple - 1))}
                      disabled={multiple <= 1}
                    >
                      −
                    </button>
                    <input
                      type="number"
                      className="fqp-input"
                      value={multiple}
                      onChange={(e) => {
                        const v = parseInt(e.target.value, 10);
                        if (!isNaN(v) && v >= 1 && v <= 99) setMultiple(v);
                      }}
                      min={1}
                      max={99}
                      style={{ width: '60px', textAlign: 'center' }}
                    />
                    <button
                      className="fqp-btn fqp-btn-sm"
                      onClick={() => setMultiple(Math.min(99, multiple + 1))}
                      disabled={multiple >= 99}
                    >
                      +
                    </button>
                  </div>
                </div>

                {/* Notes */}
                <div>
                  <label className="fqp-label">备注（可选）</label>
                  <input
                    type="text"
                    className="fqp-input"
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    placeholder="如：看好主胜"
                    style={{ width: '100%' }}
                  />
                </div>
              </div>
            </Card>
          )}

          {/* Summary & Submit */}
          {calcResult && (
            <Card title="投注摘要" style={{ animation: 'fqpSlideUpBounce 0.4s ease both' }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '14px' }}>
                  <span className="fqp-text-muted">注数</span>
                  <span className="fqp-mono">{calcResult.bet_count} 注</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '14px' }}>
                  <span className="fqp-text-muted">投注金额</span>
                  <span className="fqp-mono" style={{ color: 'var(--fqp-accent)', fontWeight: 600 }}>
                    ¥<CountUp value={calcResult.total_cost} />
                  </span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '14px' }}>
                  <span className="fqp-text-muted">最高奖金</span>
                  <span className="fqp-mono" style={{ color: 'var(--fqp-success)', fontWeight: 600 }}>
                    ¥<CountUp value={calcResult.max_prize} duration={800} />
                  </span>
                </div>
                {bankroll && calcResult.total_cost > bankroll.current_balance && (
                  <div style={{ color: 'var(--fqp-danger)', fontSize: '12px', textAlign: 'center' }}>
                    ⚠ 余额不足！当前余额 ¥{bankroll.current_balance.toFixed(2)}
                  </div>
                )}
                <button
                  className="fqp-btn fqp-btn-primary"
                  style={{ width: '100%', padding: '10px', fontSize: '15px', fontWeight: 700 }}
                  onClick={handleSubmit}
                  disabled={
                    submitting ||
                    calcLoading ||
                    (bankroll !== null && calcResult.total_cost > bankroll.current_balance)
                  }
                >
                  {submitting ? '提交中...' : calcLoading ? '计算中...' : '🎫 确认投注'}
                </button>
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
