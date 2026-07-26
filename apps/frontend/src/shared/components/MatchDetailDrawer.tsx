import { useEffect, useState, useCallback, useRef } from 'react';
import { api } from '../../core/apiClient';
import type {
  MatchDetail,
  MatchDetailFormEntry,
  MatchDetailH2HMatch,
  MatchDetailStandingEntry,
  MatchDetailInjury,
  MatchDetailLineup,
} from '../../core/types';
import { ApiError } from '../../core/types';
import ErrorState from './ErrorState';
import { optionLabel, statusLabel } from '../constants';
import TeamLogo from './TeamLogo';

interface MatchDetailDrawerProps {
  matchId: number | null;
  onClose: () => void;
}

// ── Helpers ──────────────────────────────────────────────

function fmtTime(iso: string): string {
  return iso.replace('T', ' ').slice(0, 16);
}

function fmtDate(iso: string): string {
  return iso.slice(0, 10);
}

function pct(v: number | null | undefined): string {
  if (v == null) return '—';
  return `${(v * 100).toFixed(0)}%`;
}

function formColor(status: string | null): string {
  switch (status) {
    case 'W': return 'var(--fqp-success)';
    case 'D': return 'var(--fqp-warning)';
    case 'L': return 'var(--fqp-red-neon)';
    default: return 'var(--fqp-text-muted)';
  }
}

const SPF_LABELS: Record<string, string> = {
  '3': '主胜', '1': '平', '0': '主负',
  h: '主胜', d: '平', a: '主负',
};

// ── Sub-components ──────────────────────────────────────

function FormBadge({ status }: { status: string | null }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
      width: '24px', height: '24px', borderRadius: '4px',
      fontSize: '11px', fontWeight: 700,
      background: status
        ? (status === 'W' ? 'rgba(23,201,100,0.2)'
          : status === 'D' ? 'rgba(245,165,36,0.2)'
          : 'rgba(255,42,61,0.2)')
        : 'var(--fqp-border-subtle)',
      color: formColor(status),
    }}>
      {status || '—'}
    </span>
  );
}

function ProbBar({ label, value, color, delay = 0 }: { label: string; value: number | null; color: string; delay?: number }) {
  const p = value != null ? Math.round(value * 100) : 0;
  const [animate, setAnimate] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setAnimate(true), delay);
    return () => clearTimeout(t);
  }, [delay, value]);
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
      <span style={{ width: '50px', fontSize: '12px', color: 'var(--fqp-text-muted)' }}>{label}</span>
      <div style={{
        flex: 1, height: '18px', borderRadius: '4px',
        background: 'var(--fqp-hover-bg)', overflow: 'hidden',
        position: 'relative',
      }}>
        <div style={{
          width: animate ? `${p}%` : '0%', height: '100%',
          background: color, borderRadius: '4px',
          transition: 'width 0.8s cubic-bezier(0.16,1,0.3,1)',
        }} />
      </div>
      <span style={{ width: '40px', textAlign: 'right', fontSize: '12px', fontWeight: 600 }}>
        {value != null ? pct(value) : '—'}
      </span>
    </div>
  );
}

function Section({ title, children, icon, delay = 0 }: { title: string; children: React.ReactNode; icon?: string; delay?: number }) {
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setVisible(true), delay);
    return () => clearTimeout(t);
  }, [delay]);
  return (
    <div style={{
      marginBottom: '20px',
      opacity: visible ? 1 : 0,
      transform: visible ? 'translateY(0)' : 'translateY(10px)',
      transition: 'opacity 0.3s ease-out, transform 0.3s ease-out',
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: '6px',
        fontSize: '13px', fontWeight: 700, color: 'var(--fqp-red)',
        marginBottom: '10px', textTransform: 'uppercase',
        letterSpacing: '0.05em',
      }}>
        {icon && <span style={{ fontSize: '14px' }}>{icon}</span>}
        {title}
      </div>
      <div style={{
        background: 'var(--fqp-bg-glass)',
        borderRadius: '8px',
        border: '1px solid var(--fqp-border-subtle)',
        padding: '12px',
      }}>
        {children}
      </div>
    </div>
  );
}

// ── Tab types ──────────────────────────────────────────

type TabKey = 'overview' | 'odds' | 'data' | 'injuries';

const TABS: { key: TabKey; label: string; icon: string }[] = [
  { key: 'overview', label: '赛况', icon: '⚔️' },
  { key: 'odds', label: '赔率', icon: '📊' },
  { key: 'data', label: '数据', icon: '📋' },
  { key: 'injuries', label: '伤停', icon: '🏥' },
];

// ── Main component ─────────────────────────────────────

export default function MatchDetailDrawer({ matchId, onClose }: MatchDetailDrawerProps) {
  const [data, setData] = useState<MatchDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabKey>('overview');
  const [closing, setClosing] = useState(false);
  const [mounted, setMounted] = useState(false);

  // Trigger mounted for entrance animations
  useEffect(() => {
    if (matchId) {
      setMounted(false);
      requestAnimationFrame(() => setMounted(true));
    }
  }, [matchId]);

  // Close with animation
  const doClose = useCallback(() => {
    setClosing(true);
    setTimeout(() => {
      setClosing(false);
      onClose();
    }, 200); // match slideOutRight duration
  }, [onClose]);

  // Close on ESC
  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if (e.key === 'Escape') doClose();
  }, [doClose]);

  useEffect(() => {
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);

  // Reset tab when match changes
  useEffect(() => {
    setActiveTab('overview');
  }, [matchId]);

  // Fetch data
  useEffect(() => {
    if (!matchId) return;
    setLoading(true);
    setError(null);
    setData(null);
    api.matches.detail(matchId)
      .then((res) => { setData(res); setLoading(false); })
      .catch((e) => {
        setError(e instanceof ApiError ? e.message : '加载失败');
        setLoading(false);
      });
  }, [matchId]);

  if (!matchId) return null;

  const d = data;

  // ── Render helpers ──

  function renderForm(entries: MatchDetailFormEntry[]) {
    if (!entries.length) return <span style={{ color: 'var(--fqp-text-muted)', fontSize: '12px' }}>暂无数据</span>;
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
        <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
          {entries.map((f, i) => <FormBadge key={i} status={f.status} />)}
        </div>
        {entries.slice(0, 3).map((f, i) => (
          <div key={i} style={{ fontSize: '11px', color: 'var(--fqp-text-muted)' }}>
            {fmtDate(f.date)} {f.is_home ? '主' : '客'} vs {f.opponent}
            {f.goals_for != null && ` ${f.goals_for}:${f.goals_against}`}
          </div>
        ))}
      </div>
    );
  }

  function renderH2HMatches(matches: MatchDetailH2HMatch[]) {
    if (!matches.length) return <span style={{ color: 'var(--fqp-text-muted)', fontSize: '12px' }}>暂无交锋记录</span>;
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
        {matches.map((m, i) => (
          <div key={i} style={{
            display: 'flex', alignItems: 'center', gap: '8px',
            fontSize: '12px', padding: '5px 0',
            borderBottom: i < matches.length - 1 ? '1px solid var(--fqp-border-subtle)' : 'none',
          }}>
            <span style={{ color: 'var(--fqp-text-muted)', width: '75px', flexShrink: 0, fontSize: '11px' }}>{fmtDate(m.date)}</span>
            <span style={{ flex: 1, textAlign: 'right', fontWeight: 500 }}>{m.home}</span>
            <span style={{
              fontWeight: 700, color: 'var(--fqp-accent)', minWidth: '44px', textAlign: 'center',
              fontSize: '13px',
            }}>
              {m.home_goals != null ? `${m.home_goals}:${m.away_goals}` : 'vs'}
            </span>
            <span style={{ flex: 1, fontWeight: 500 }}>{m.away}</span>
            <span style={{ color: 'var(--fqp-text-muted)', fontSize: '11px', width: '60px', textAlign: 'right' }}>
              {m.league}
            </span>
          </div>
        ))}
      </div>
    );
  }

  function renderStandings(entries: MatchDetailStandingEntry[]) {
    if (!entries.length) return <span style={{ color: 'var(--fqp-text-muted)', fontSize: '12px' }}>暂无积分榜数据</span>;
    const top10 = entries.slice(0, 10);
    return (
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', fontSize: '11px', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ color: 'var(--fqp-text-muted)', borderBottom: '1px solid var(--fqp-border-medium)' }}>
              {['#', '球队', '赛', '胜', '平', '负', '进/失', '净胜', '积分'].map(h => (
                <th key={h} style={{
                  padding: '5px 6px', textAlign: h === '#' || h === '球队' ? 'left' : 'center',
                  fontWeight: 600, fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.04em',
                }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {top10.map((s) => {
              const isHome = d && s.team_name === d.teams.home.name_cn;
              const isAway = d && s.team_name === d.teams.away.name_cn;
              const hl = isHome || isAway;
              const allCaps = [...top10].sort((a, b) => b.points - a.points);
              const isChampion = allCaps.length > 0 && s.rank === allCaps[0].rank;
              return (
                <tr key={s.rank} style={{
                  borderBottom: '1px solid var(--fqp-hover-subtle)',
                  background: isHome ? 'rgba(229,9,20,0.08)' : isAway ? 'rgba(59,130,246,0.08)' : 'transparent',
                  fontWeight: hl ? 700 : 400,
                  transition: 'background 0.15s',
                }}>
                  <td style={{
                    padding: '5px 6px', textAlign: 'left',
                    color: isChampion ? 'var(--fqp-warning)' : 'var(--fqp-text-muted)',
                    fontWeight: isChampion ? 700 : 400,
                  }}>
                    {isChampion ? '👑' : s.rank}
                  </td>
                  <td style={{ padding: '5px 6px', maxWidth: '120px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {s.team_name}
                  </td>
                  <td style={{ padding: '5px 6px', textAlign: 'center' }}>{s.played}</td>
                  <td style={{ padding: '5px 6px', textAlign: 'center', color: 'var(--fqp-success)' }}>{s.won}</td>
                  <td style={{ padding: '5px 6px', textAlign: 'center', color: 'var(--fqp-warning)' }}>{s.drawn}</td>
                  <td style={{ padding: '5px 6px', textAlign: 'center', color: 'var(--fqp-red-neon)' }}>{s.lost}</td>
                  <td style={{ padding: '5px 6px', textAlign: 'center' }}>{s.goals_for}:{s.goals_against}</td>
                  <td style={{ padding: '5px 6px', textAlign: 'center', color: s.goal_diff > 0 ? 'var(--fqp-success)' : s.goal_diff < 0 ? 'var(--fqp-red-neon)' : undefined }}>
                    {s.goal_diff > 0 ? `+${s.goal_diff}` : s.goal_diff}
                  </td>
                  <td style={{ padding: '5px 6px', textAlign: 'center', fontWeight: 700, fontSize: '13px' }}>{s.points}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    );
  }

  function renderLineup(lineup: MatchDetailLineup | null, label: string) {
    if (!lineup || !lineup.players.length) return null;
    const starters = lineup.players.filter(p => p.is_starting);
    const subs = lineup.players.filter(p => p.is_substitute);
    return (
      <div style={{ flex: 1, minWidth: '200px' }}>
        <div style={{
          fontSize: '11px', fontWeight: 600, marginBottom: '8px',
          color: 'var(--fqp-text)',
          background: 'var(--fqp-border-subtle)', padding: '4px 8px', borderRadius: '4px',
        }}>
          {label}
          {lineup.formation && <span style={{ marginLeft: '8px', color: 'var(--fqp-red)' }}>▸ {lineup.formation}</span>}
          {lineup.strength_score != null && (
            <span style={{ marginLeft: '8px', color: 'var(--fqp-text-muted)', fontSize: '10px' }}>
              战力 {lineup.strength_score.toFixed(1)}
            </span>
          )}
        </div>
        {starters.map((p, i) => (
          <div key={i} style={{
            fontSize: '11px', padding: '3px 8px', display: 'flex', gap: '6px',
            borderRadius: '3px',
            transition: 'background 0.1s',
          }}>
            <span style={{ color: 'var(--fqp-text-muted)', width: '18px', fontWeight: 600 }}>{i + 1}</span>
            <span style={{ color: 'var(--fqp-text-muted)', width: '50px', fontSize: '10px' }}>
              {p.primary_position || p.position || ''}
            </span>
            <span style={{ fontWeight: 500 }}>{p.name_cn || p.name_en || `球员#${p.player_id}`}</span>
          </div>
        ))}
        {subs.length > 0 && (
          <div style={{
            marginTop: '8px', paddingTop: '6px',
            borderTop: '1px solid var(--fqp-border-subtle)',
            fontSize: '11px', color: 'var(--fqp-text-muted)',
            padding: '4px 8px',
          }}>
            替补: {subs.map(s => s.name_cn || s.name_en).filter(Boolean).join(', ')}
          </div>
        )}
      </div>
    );
  }

  function renderInjuries(entries: MatchDetailInjury[]) {
    if (!entries.length) return <span style={{ color: 'var(--fqp-text-muted)', fontSize: '12px' }}>暂无伤停信息</span>;
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
        {entries.map((ij, i) => (
          <div key={i} style={{
            display: 'flex', alignItems: 'center', gap: '10px',
            fontSize: '12px', padding: '6px 8px',
            borderRadius: '4px',
            transition: 'background 0.1s',
          }}>
            <span style={{
              width: '8px', height: '8px', borderRadius: '50%', flexShrink: 0,
              background: ij.status === 'injured' ? 'var(--fqp-red-neon)'
                : ij.status === 'suspended' ? 'var(--fqp-warning)'
                : 'var(--fqp-text-muted)',
              boxShadow: ij.status === 'injured' ? '0 0 6px var(--fqp-red-neon)' : 'none',
            }} />
            <span style={{ width: '85px', fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {ij.player_name_cn || ij.player_name_en || '未知'}
            </span>
            <span style={{ color: 'var(--fqp-text-muted)', width: '50px', fontSize: '11px' }}>{ij.position || ''}</span>
            <span style={{ flex: 1 }}>{ij.injury_type || ''}{ij.body_part ? ` (${ij.body_part})` : ''}</span>
            {ij.expected_return && (
              <span style={{ color: 'var(--fqp-text-muted)', fontSize: '11px', whiteSpace: 'nowrap' }}>
                ⌛ {ij.expected_return}
              </span>
            )}
          </div>
        ))}
      </div>
    );
  }

  // ── Scoreboard header ──

  function renderScoreboard() {
    if (!d) return null;
    const hasScore = d.scores && (d.scores.ft_home != null || d.scores.ft_away != null);
    const statusText = d.match.match_status ? statusLabel(d.match.match_status) : d.match.match_status;
    const isSettled = d.match.match_status === 'Settled' || d.match.match_status === 'Finished';
    const isSelling = d.match.match_status === 'Selling';

    const anim = (delay: number): React.CSSProperties => ({
      animation: mounted ? `dropIn 0.35s ease-out ${delay}ms both` : 'none',
    });
    const scaleAnim = (delay: number): React.CSSProperties => ({
      animation: mounted ? `scaleIn 0.35s cubic-bezier(0.34,1.56,0.64,1) ${delay}ms both` : 'none',
    });
    const fadeAnim = (delay: number): React.CSSProperties => ({
      animation: mounted ? `fadeUp 0.3s ease-out ${delay}ms both` : 'none',
    });

    return (
      <div style={{
        textAlign: 'center', padding: '20px 0 18px',
        borderBottom: '1px solid var(--fqp-hover-bg)',
        marginBottom: '16px',
        position: 'relative',
      }}>
        {/* Top info row */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          gap: '8px', marginBottom: '14px',
          fontSize: '11px', ...fadeAnim(0),
        }}>
          <span style={{
            background: 'rgba(229,9,20,0.1)', color: 'var(--fqp-red)',
            padding: '2px 8px', borderRadius: '4px',
            fontWeight: 600, fontSize: '10px',
          }}>
            {d.match.league_name}
          </span>
          <span style={{
            padding: '2px 8px', borderRadius: '4px',
            fontWeight: 600, fontSize: '10px',
            background: isSettled ? 'rgba(23,201,100,0.12)' : isSelling ? 'rgba(245,165,36,0.12)' : 'var(--fqp-hover-bg)',
            color: isSettled ? 'var(--fqp-success)' : isSelling ? 'var(--fqp-warning)' : 'var(--fqp-text-muted)',
          }}>
            {statusText || d.match.sale_status || '—'}
          </span>
        </div>

        {/* Team logos + VS + Score */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0' }}>
          {/* Home */}
          <div style={{ flex: 1, textAlign: 'right', paddingRight: '12px', ...anim(60) }}>
            <TeamLogo
              nameCn={d.teams.home.name_cn}
              nameEn={d.teams.home.name_en}
              shortName={d.teams.home.short_name}
              country={d.teams.home.country || d.match.league_name}
              size={60}
            />
            <div style={{ fontSize: '15px', fontWeight: 700, marginTop: '6px', lineHeight: 1.2 }}>
              {d.teams.home.short_name || d.match.home_team_name}
            </div>
            <div style={{ fontSize: '10px', color: 'var(--fqp-text-muted)', marginTop: '2px' }}>
              {d.match.home_team_name}
            </div>
          </div>

          {/* VS + Score */}
          <div style={{ minWidth: '80px', textAlign: 'center', ...anim(120) }}>
            <div style={{
              fontSize: '12px', fontWeight: 700, color: 'var(--fqp-text-muted)',
              opacity: 0.5, letterSpacing: '0.1em', marginBottom: '4px',
            }}>
              VS
            </div>
            {hasScore ? (
              <>
                <div style={{
                  fontSize: '38px', fontWeight: 900,
                  color: 'var(--fqp-red-neon)',
                  lineHeight: 1.1, letterSpacing: '-0.02em',
                  textShadow: '0 0 20px rgba(229,9,20,0.3)',
                  ...scaleAnim(180),
                }}>
                  {d.scores!.ft_home}:{d.scores!.ft_away}
                </div>
                {d.scores!.ht_home != null && (
                  <div style={{ fontSize: '11px', color: 'var(--fqp-text-muted)', marginTop: '2px', ...fadeAnim(280) }}>
                    (半场 {d.scores!.ht_home}:{d.scores!.ht_away})
                  </div>
                )}
                {d.scores!.spf_result && (
                  <div style={{
                    marginTop: '4px',
                    display: 'inline-block',
                    background: 'rgba(229,9,20,0.12)',
                    color: 'var(--fqp-red)',
                    padding: '1px 10px', borderRadius: '10px',
                    fontSize: '10px', fontWeight: 700,
                    ...fadeAnim(320),
                  }}>
                    {SPF_LABELS[d.scores!.spf_result] || d.scores!.spf_result}
                  </div>
                )}
              </>
            ) : (
              <div style={{
                fontSize: '22px', fontWeight: 800,
                color: 'var(--fqp-text-muted)', opacity: 0.4,
              }}>
                vs
              </div>
            )}
          </div>

          {/* Away */}
          <div style={{ flex: 1, textAlign: 'left', paddingLeft: '12px', ...anim(60) }}>
            <TeamLogo
              nameCn={d.teams.away.name_cn}
              nameEn={d.teams.away.name_en}
              shortName={d.teams.away.short_name}
              country={d.teams.away.country || d.match.league_name}
              size={60}
            />
            <div style={{ fontSize: '15px', fontWeight: 700, marginTop: '6px', lineHeight: 1.2 }}>
              {d.teams.away.short_name || d.match.away_team_name}
            </div>
            <div style={{ fontSize: '10px', color: 'var(--fqp-text-muted)', marginTop: '2px' }}>
              {d.match.away_team_name}
            </div>
          </div>
        </div>

        {/* Info bar */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          gap: '12px', marginTop: '12px',
          fontSize: '11px', color: 'var(--fqp-text-muted)',
          ...fadeAnim(340),
        }}>
          <span>{fmtTime(d.match.kickoff_time)}</span>
          {d.feature_snapshot?.temperature != null && (
            <>
              <span style={{ opacity: 0.3 }}>|</span>
              <span>🌡️ {d.feature_snapshot.temperature}°C</span>
            </>
          )}
        </div>
      </div>
    );
  }

  // ── Tab navigation ──

  function renderTabs() {
    return (
      <div style={{
        display: 'flex', gap: '2px', marginBottom: '16px',
        background: 'var(--fqp-bg-glass)',
        borderRadius: '8px', padding: '3px',
        border: '1px solid var(--fqp-border-subtle)',
      }}>
        {TABS.map(tab => {
          const isActive = activeTab === tab.key;
          // Determine if tab has content
          let hasContent = false;
          if (d) {
            switch (tab.key) {
              case 'overview': hasContent = d.form.home.length > 0 || d.form.away.length > 0 || d.h2h.total_matches > 0; break;
              case 'odds': hasContent = !!(d.predictions && d.predictions.models.some(m => m.play_type === 'spf' && m.model_probability != null)); break;
              case 'data': hasContent = d.standings.length > 0 || !!(d.lineups.home || d.lineups.away) || !!d.feature_snapshot; break;
              case 'injuries': hasContent = d.injuries.length > 0; break;
            }
          }
          if (!hasContent && d) return null;
          return (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              style={{
                flex: 1, padding: '7px 10px',
                border: 'none', borderRadius: '6px',
                cursor: 'pointer',
                fontSize: '12px', fontWeight: isActive ? 700 : 500,
                background: isActive ? 'var(--fqp-accent)' : 'transparent',
                color: isActive ? '#fff' : 'var(--fqp-text-muted)',
                transition: 'all 0.15s',
              }}
            >
              {tab.icon} {tab.label}
            </button>
          );
        })}
      </div>
    );
  }

  // ── Tab content ──

  function renderTabContent() {
    if (!d) return null;
    switch (activeTab) {
      case 'overview':
        return (
          <div key="overview" style={{ animation: 'tabEnter 0.2s ease-out both' }}>
            {/* Form */}
            {(d.form.home.length > 0 || d.form.away.length > 0) && (
              <Section title="比赛近况" icon="📈" delay={50}>
                <div style={{ display: 'flex', gap: '20px', flexWrap: 'wrap' }}>
                  {d.form.home.length > 0 && (
                    <div style={{ flex: 1, minWidth: '180px' }}>
                      <div style={{ fontSize: '12px', fontWeight: 600, marginBottom: '6px', color: 'var(--fqp-red)' }}>
                        {d.match.home_team_name}
                      </div>
                      {renderForm(d.form.home)}
                    </div>
                  )}
                  {d.form.away.length > 0 && (
                    <div style={{ flex: 1, minWidth: '180px' }}>
                      <div style={{ fontSize: '12px', fontWeight: 600, marginBottom: '6px', color: 'var(--fqp-info)' }}>
                        {d.match.away_team_name}
                      </div>
                      {renderForm(d.form.away)}
                    </div>
                  )}
                </div>
              </Section>
            )}

            {/* H2H */}
            {d.h2h.total_matches > 0 && (
              <Section title={`交锋记录 (${d.h2h.total_matches}场)`} icon="⚔️" delay={120}>
                <div style={{
                  display: 'flex', gap: '16px', marginBottom: '10px',
                  fontSize: '12px', justifyContent: 'center',
                }}>
                  <span style={{ color: 'var(--fqp-red)', fontWeight: 700 }}>
                    {d.match.home_team_name} {d.h2h.home_wins}胜
                  </span>
                  <span style={{ color: 'var(--fqp-warning)', fontWeight: 700 }}>
                    平 {d.h2h.draws}场
                  </span>
                  <span style={{ color: 'var(--fqp-info)', fontWeight: 700 }}>
                    {d.match.away_team_name} {d.h2h.away_wins}胜
                  </span>
                </div>
                {renderH2HMatches(d.h2h.recent_matches)}
              </Section>
            )}

            {/* Empty state for overview */}
            {d.form.home.length === 0 && d.form.away.length === 0 && d.h2h.total_matches === 0 && (
              <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--fqp-text-muted)', fontSize: '13px' }}>
                暂无赛况数据
              </div>
            )}
          </div>
        );

      case 'odds':
        return (
          <div key="odds" style={{ animation: 'tabEnter 0.2s ease-out both' }}>
            {/* Win Probability */}
            {d.predictions && d.predictions.models.some(m => m.play_type === 'spf' && m.model_probability != null) && (
              <Section title="胜率预测" icon="📊" delay={50}>
                {(() => {
                  const spfPred = d.predictions!.models.filter(m => m.play_type === 'spf');
                  const best = spfPred.reduce((a, b) => (a.ev ?? -999) > (b.ev ?? -999) ? a : b, spfPred[0]);
                  const h = spfPred.find(m => m.option_code === '3');
                  const dr = spfPred.find(m => m.option_code === '1');
                  const a = spfPred.find(m => m.option_code === '0');
                  if (!h && !dr && !a) {
                    return <span style={{ color: 'var(--fqp-text-muted)', fontSize: '12px' }}>胜率数据格式不匹配</span>;
                  }
                  const models = [...new Set(spfPred.map(m => m.model_name))];
                  return (
                    <div>
                      {models.length > 0 && (
                        <div style={{
                          fontSize: '11px', color: 'var(--fqp-text-muted)', marginBottom: '10px',
                          padding: '6px 8px', background: 'var(--fqp-hover-subtle)', borderRadius: '4px',
                        }}>
                          模型: {models.join(' · ')}
                          {best && (
                            <span style={{ marginLeft: '8px' }}>
                              最优: <span style={{
                                color: best.option_code === '3' ? 'var(--fqp-red)' : best.option_code === '1' ? 'var(--fqp-warning)' : 'var(--fqp-info)',
                                fontWeight: 700,
                              }}>
                                {optionLabel(best.play_type, best.option_code)}
                              </span>
                              {best.ev != null && (
                                <span style={{ color: best.ev >= 0 ? 'var(--fqp-success)' : 'var(--fqp-red-neon)', marginLeft: '4px' }}>
                                  EV {best.ev >= 0 ? '+' : ''}{best.ev.toFixed(3)}
                                </span>
                              )}
                            </span>
                          )}
                        </div>
                      )}
                      <div style={{ padding: '0 4px' }}>
                        {h && <ProbBar label="主胜" value={h.model_probability} color="var(--fqp-red)" delay={0} />}
                        {dr && <ProbBar label="平局" value={dr.model_probability} color="var(--fqp-warning)" delay={100} />}
                        {a && <ProbBar label="主负" value={a.model_probability} color="var(--fqp-info)" delay={200} />}
                      </div>
                    </div>
                  );
                })()}
              </Section>
            )}

            {/* Empty state for odds */}
            {(!d.predictions || !d.predictions.models.some(m => m.play_type === 'spf' && m.model_probability != null)) && (
              <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--fqp-text-muted)', fontSize: '13px' }}>
                暂无赔率数据
              </div>
            )}
          </div>
        );

      case 'data':
        return (
          <div key="data" style={{ animation: 'tabEnter 0.2s ease-out both' }}>
            {/* Standings */}
            {d.standings.length > 0 && (
              <Section title="积分榜" icon="🏆" delay={50}>
                {renderStandings(d.standings)}
              </Section>
            )}

            {/* Lineups */}
            {(d.lineups.home || d.lineups.away) && (
              <Section title="阵容" icon="👥" delay={120}>
                <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap' }}>
                  {renderLineup(d.lineups.home, d.match.home_team_name)}
                  {renderLineup(d.lineups.away, d.match.away_team_name)}
                </div>
              </Section>
            )}

            {/* Feature Snapshot */}
            {d.feature_snapshot && (
              <Section title="数据快照" icon="📊" delay={180}>
                <div style={{
                  display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px 16px',
                  fontSize: '12px',
                }}>
                  {d.feature_snapshot.completeness_score != null && (
                    <>
                      <span style={{ color: 'var(--fqp-text-muted)' }}>数据完整度</span>
                      <span style={{ fontWeight: 600 }}>{d.feature_snapshot.completeness_score}%</span>
                    </>
                  )}
                  {d.feature_snapshot.home_rest_days != null && (
                    <>
                      <span style={{ color: 'var(--fqp-text-muted)' }}>休息天数</span>
                      <span>主 {d.feature_snapshot.home_rest_days}d / 客 {d.feature_snapshot.away_rest_days}d</span>
                    </>
                  )}
                  {d.feature_snapshot.rest_days_diff != null && (
                    <>
                      <span style={{ color: 'var(--fqp-text-muted)' }}>休息差</span>
                      <span style={{
                        color: d.feature_snapshot.rest_days_diff > 0 ? 'var(--fqp-success)' : d.feature_snapshot.rest_days_diff < 0 ? 'var(--fqp-red-neon)' : undefined,
                      }}>
                        {d.feature_snapshot.rest_days_diff > 0 ? `多${d.feature_snapshot.rest_days_diff}d` : d.feature_snapshot.rest_days_diff < 0 ? `少${-d.feature_snapshot.rest_days_diff}d` : '相同'}
                      </span>
                    </>
                  )}
                  {d.feature_snapshot.temperature != null && (
                    <>
                      <span style={{ color: 'var(--fqp-text-muted)' }}>天气</span>
                      <span>{d.feature_snapshot.temperature}°C{d.feature_snapshot.wind_speed ? ` | ${d.feature_snapshot.wind_speed}m/s` : ''}</span>
                    </>
                  )}
                  {d.feature_snapshot.travel_distance_km != null && (
                    <>
                      <span style={{ color: 'var(--fqp-text-muted)' }}>客队旅途</span>
                      <span>{d.feature_snapshot.travel_distance_km.toFixed(0)} km</span>
                    </>
                  )}
                  {d.feature_snapshot.home_motivation != null && (
                    <>
                      <span style={{ color: 'var(--fqp-text-muted)' }}>战意</span>
                      <span>主 {d.feature_snapshot.home_motivation.toFixed(1)} / 客 {d.feature_snapshot.away_motivation?.toFixed(1)}</span>
                    </>
                  )}
                  {d.feature_snapshot.home_absence_impact != null && (
                    <>
                      <span style={{ color: 'var(--fqp-text-muted)' }}>伤停影响</span>
                      <span>主 {d.feature_snapshot.home_absence_impact.toFixed(1)} / 客 {d.feature_snapshot.away_absence_impact?.toFixed(1)}</span>
                    </>
                  )}
                </div>
              </Section>
            )}

            {/* Empty */}
            {d.standings.length === 0 && !d.lineups.home && !d.lineups.away && !d.feature_snapshot && (
              <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--fqp-text-muted)', fontSize: '13px' }}>
                暂无数据
              </div>
            )}
          </div>
        );

      case 'injuries':
        return (
          <div key="injuries" style={{ animation: 'tabEnter 0.2s ease-out both' }}>
            {d.injuries.length > 0 ? (
              <Section title="伤停一览" icon="🏥" delay={50}>
                {renderInjuries(d.injuries)}
              </Section>
            ) : (
              <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--fqp-text-muted)', fontSize: '13px' }}>
                ✅ 暂无伤停信息
              </div>
            )}
          </div>
        );
    }
  }

  // ── Drawer overlay ──

  return (
    <div
      onClick={doClose}
      style={{
        position: 'fixed', inset: 0, zIndex: 1000,
        background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)',
        animation: closing ? 'fadeOut 0.2s ease-in forwards' : 'drawerFadeIn 0.2s ease-out both',
      }}
    >
      {/* Drawer panel */}
      <div
        onAnimationEnd={() => {
          // Prevent double events
        }}
        onClick={(e) => e.stopPropagation()}
        style={{
          position: 'absolute', right: 0, top: 0, bottom: 0,
          width: '660px', maxWidth: '100vw',
          background: 'var(--fqp-panel)',
          borderLeft: '1px solid var(--fqp-border)',
          display: 'flex', flexDirection: 'column',
          animation: closing
            ? 'slideOutRight 0.22s ease-in forwards'
            : 'drawerSlideIn 0.25s cubic-bezier(0.16,1,0.3,1) both',
          boxShadow: '-8px 0 32px rgba(0,0,0,0.4)',
        }}
      >
        {/* ── Header bar ── */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '14px 20px', borderBottom: '1px solid var(--fqp-border)',
          flexShrink: 0,
          background: 'rgba(0,0,0,0.2)',
        }}>
          <span style={{ fontSize: '15px', fontWeight: 700 }}>
            {data ? `${data.match.home_team_name} vs ${data.match.away_team_name}` : '比赛详情'}
          </span>
          <button
            onClick={doClose}
            style={{
              width: '32px', height: '32px',
              background: 'var(--fqp-hover-bg)',
              border: '1px solid var(--fqp-border-medium)',
              color: 'var(--fqp-text-muted)',
              cursor: 'pointer', fontSize: '16px', borderRadius: '8px',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              lineHeight: 1, transition: 'all 0.25s cubic-bezier(0.34,1.56,0.64,1)',
            }}
            onMouseEnter={e => {
              e.currentTarget.style.background = 'rgba(229,9,20,0.15)';
              e.currentTarget.style.color = 'var(--fqp-red-neon)';
              e.currentTarget.style.transform = 'rotate(90deg)';
              e.currentTarget.style.boxShadow = '0 0 12px rgba(229,9,20,0.3)';
            }}
            onMouseLeave={e => {
              e.currentTarget.style.background = 'var(--fqp-hover-bg)';
              e.currentTarget.style.color = 'var(--fqp-text-muted)';
              e.currentTarget.style.transform = 'rotate(0deg)';
              e.currentTarget.style.boxShadow = 'none';
            }}
          >
            ✕
          </button>
        </div>

        {/* ── Body ── */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '0 20px 20px' }}>
          {loading && (
            <div style={{ paddingTop: '20px' }}>
              {/* Skeleton Scoreboard */}
              <div style={{ textAlign: 'center', padding: '20px 0', borderBottom: '1px solid var(--fqp-hover-bg)', marginBottom: '16px' }}>
                <div className="fqp-skeleton" style={{ width: '140px', height: '20px', margin: '0 auto 14px', borderRadius: '4px' }} />
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '16px' }}>
                  <div style={{ flex: 1, textAlign: 'right', display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '8px' }}>
                    <div className="fqp-skeleton" style={{ width: '60px', height: '60px', borderRadius: '50%' }} />
                    <div className="fqp-skeleton" style={{ width: '80px', height: '14px', borderRadius: '4px' }} />
                  </div>
                  <div style={{ minWidth: '80px', textAlign: 'center' }}>
                    <div className="fqp-skeleton" style={{ width: '70px', height: '36px', margin: '0 auto', borderRadius: '4px' }} />
                  </div>
                  <div style={{ flex: 1, textAlign: 'left', display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: '8px' }}>
                    <div className="fqp-skeleton" style={{ width: '60px', height: '60px', borderRadius: '50%' }} />
                    <div className="fqp-skeleton" style={{ width: '80px', height: '14px', borderRadius: '4px' }} />
                  </div>
                </div>
                <div className="fqp-skeleton" style={{ width: '160px', height: '12px', margin: '12px auto 0', borderRadius: '4px' }} />
              </div>
              {/* Skeleton tabs */}
              <div style={{ display: 'flex', gap: '2px', marginBottom: '16px', padding: '3px', background: 'var(--fqp-bg-glass)', borderRadius: '8px' }}>
                {[1,2,3,4].map(i => <div key={i} className="fqp-skeleton" style={{ flex: 1, height: '34px', borderRadius: '6px' }} />)}
              </div>
              {/* Skeleton sections */}
              {[1,2].map(i => (
                <div key={i} style={{ marginBottom: '20px' }}>
                  <div className="fqp-skeleton" style={{ width: '100px', height: '14px', marginBottom: '10px', borderRadius: '4px' }} />
                  <div style={{ background: 'var(--fqp-bg-glass)', borderRadius: '8px', padding: '12px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    <div className="fqp-skeleton" style={{ width: '100%', height: '12px', borderRadius: '4px' }} />
                    <div className="fqp-skeleton" style={{ width: '70%', height: '12px', borderRadius: '4px' }} />
                    <div className="fqp-skeleton" style={{ width: '85%', height: '12px', borderRadius: '4px' }} />
                  </div>
                </div>
              ))}
            </div>
          )}
          {error && <ErrorState message={error} onRetry={() => { setError(null); setLoading(true); api.matches.detail(matchId).then(setData).catch(e => setError(e instanceof ApiError ? e.message : '加载失败')).finally(() => setLoading(false)); }} />}

          {d && (
            <>
              {renderScoreboard()}
              {renderTabs()}
              {renderTabContent()}
            </>
          )}
        </div>
      </div>

      {/* ── Keyframe animations ── */}
      <style>{`
        /* Drawer open */
        @keyframes drawerFadeIn { from { opacity: 0; } to { opacity: 1; } }
        @keyframes drawerSlideIn { from { transform: translateX(100%); } to { transform: translateX(0); } }
        /* Drawer close */
        @keyframes fadeOut { from { opacity: 1; } to { opacity: 0; } }
        @keyframes slideOutRight { from { transform: translateX(0); } to { transform: translateX(100%); } }
        /* Scoreboard */
        @keyframes dropIn { from { opacity: 0; transform: translateY(-20px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes scaleIn { from { opacity: 0; transform: scale(0.6); } to { opacity: 1; transform: scale(1); } }
        @keyframes fadeUp { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
        /* Tab content transition */
        @keyframes tabEnter { from { opacity: 0; transform: translateX(12px); } to { opacity: 1; transform: translateX(0); } }
      `}</style>
    </div>
  );
}
