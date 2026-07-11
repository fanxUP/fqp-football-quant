/** Agent 资金池综合看板 — 取代单一环形图，展示多维度策略数据 */

import { useEffect, useState } from 'react';
import type { DashboardTodayKpi, DashboardModelPerfItem } from '../core/types';

// ---- CountUp: animates a number from 0 to target ----
function CountUp({ value, duration = 600 }: { value: number; duration?: number }) {
  const [display, setDisplay] = useState(0);
  useEffect(() => {
    if (value <= 0) { setDisplay(0); return; }
    const start = performance.now();
    let raf: number;
    const animate = (now: number) => {
      const p = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - p, 3);
      setDisplay(Math.round(value * eased));
      if (p < 1) raf = requestAnimationFrame(animate);
    };
    raf = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(raf);
  }, [value, duration]);
  return <span>{display.toLocaleString()}</span>;
}

// ---- KPI meta config ----
interface KpiMeta {
  key: string;
  icon: string;
  color: string;
  unit: string;
  label: string;
}

const KPI_ITEMS: KpiMeta[] = [
  { key: 'predicted_match_count', icon: '🎯', color: '#3B82F6', unit: '场', label: '已预测' },
  { key: 'ai_stake_today',        icon: '💰', color: '#F5A524', unit: '',    label: '策略投入' },
  { key: 'ai_ticket_count',       icon: '📋', color: '#22C55E', unit: '张', label: '票单数' },
  { key: 'pending_settlement_count', icon: '⏳', color: '#FF2A3D', unit: '张', label: '待开奖' },
];

const MODEL_LABELS: Record<string, string> = {
  dixon_coles: 'D-C',
  elo_rating: 'Elo',
  maher_poisson: 'Poisson',
};

// ---- Props ----
interface AiPoolDashboardProps {
  kpis: DashboardTodayKpi[];
  models: DashboardModelPerfItem[];
  extras: {
    current_round_label: string | null;
    business_date: string;
  };
  pageStats?: {
    matchCount: number;
    predictionCount: number;
    activeTicketCount: number;
    ticketLedgerCount: number;
  };
  loading?: boolean;
  error?: string | null;
}

export default function AiPoolDashboard({
  kpis,
  models,
  extras,
  pageStats,
  loading,
  error,
}: AiPoolDashboardProps) {
  // ---- Helper: get KPI value by key ----
  const kpiVal = (key: string): number => {
    const found = kpis.find((k) => k.key === key);
    return found?.value ?? 0;
  };

  // ---- Date formatting ----
  const dateStr = extras.business_date;
  const dayOfWeek = dateStr
    ? new Date(dateStr + 'T00:00:00').toLocaleDateString('zh-CN', { weekday: 'short' })
    : '';

  // ---- Proportional bar data ----
  const barItems = KPI_ITEMS.map((m) => ({
    label: m.label,
    value: kpiVal(m.key),
    color: m.color,
  }));
  const barTotal = barItems.reduce((s, i) => s + i.value, 0);

  // ---- Loading ----
  if (loading) {
    return (
      <div style={{ padding: '24px 0', textAlign: 'center' }}>
        <div className="fqp-skeleton" style={{ width: '90%', height: 200, borderRadius: 8, margin: '0 auto' }} />
      </div>
    );
  }

  // ---- Error ----
  if (error) {
    return (
      <div style={{ padding: '24px 0', textAlign: 'center', color: 'var(--fqp-red-neon)' }}>
        ⚠️ {error}
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
      {/* ========== Round info bar ========== */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '6px 12px',
          background: 'var(--fqp-hover-subtle)',
          borderRadius: 6,
          fontSize: 12,
        }}
      >
        <span style={{ color: 'var(--fqp-text)' }}>
          <span style={{ fontWeight: 600 }}>{extras.current_round_label || '—'}</span>
          <span style={{ color: 'var(--fqp-text-muted)', marginLeft: 8 }}>
            · {dayOfWeek} {dateStr}
          </span>
        </span>
        <span style={{ color: 'var(--fqp-text-muted)' }}>
          预测累计 {pageStats?.predictionCount ?? kpiVal('predicted_match_count')} 条
        </span>
      </div>

      {/* ========== 4-Column KPI grid ========== */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '8px' }}>
        {KPI_ITEMS.map((meta) => {
          const val = kpiVal(meta.key);
          const rgb = hexToRgb(meta.color);
          return (
            <div
              key={meta.key}
              style={{
                textAlign: 'center',
                padding: '12px 2px',
                background: `rgba(${rgb},0.06)`,
                borderRadius: 8,
                border: `1px solid rgba(${rgb},0.12)`,
              }}
            >
              <div style={{ fontSize: 18, marginBottom: 2 }}>{meta.icon}</div>
              <div
                className="fqp-mono"
                style={{
                  fontSize: 20,
                  fontWeight: 700,
                  color: meta.color,
                  lineHeight: 1.2,
                  marginTop: 2,
                }}
              >
                {meta.key === 'ai_stake_today' ? (
                  <><span style={{ fontSize: 13, fontWeight: 500 }}>¥</span><CountUp value={val} /></>
                ) : (
                  <CountUp value={val} />
                )}
                {meta.unit && <span style={{ fontSize: 12, fontWeight: 500, marginLeft: 1 }}>{meta.unit}</span>}
              </div>
              <div style={{ fontSize: 11, color: 'var(--fqp-text-muted)', marginTop: 2 }}>{meta.label}</div>
            </div>
          );
        })}
      </div>

      {/* ========== Profit / Loss panel ========== */}
      {(() => {
        const profitLoss = kpiVal('ai_today_profit_loss');
        const stake = kpiVal('ai_stake_today');
        const profitRate = stake > 0 ? (profitLoss / stake) : 0;
        const isProfit = profitLoss > 0;
        const isLoss = profitLoss < 0;
        const color = isProfit ? 'var(--fqp-success)' : isLoss ? 'var(--fqp-red-neon)' : 'var(--fqp-text-muted)';
        const icon = isProfit ? '📈' : isLoss ? '📉' : '➖';

        return (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '10px 14px',
              background: isProfit ? 'rgba(34,197,94,0.06)' : isLoss ? 'rgba(239,68,68,0.06)' : 'var(--fqp-bg-glass)',
              borderRadius: 8,
              border: `1px solid ${
                isProfit ? 'rgba(34,197,94,0.15)' : isLoss ? 'rgba(239,68,68,0.15)' : 'var(--fqp-border-subtle)'
              }`,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 16 }}>{icon}</span>
              <div>
                <div style={{ fontSize: 11, color: 'var(--fqp-text-muted)' }}>AI 当日盈亏</div>
                <div style={{ fontSize: 18, fontWeight: 700, color }} className="fqp-mono">
                  {profitLoss >= 0 ? '+' : ''}<CountUp value={Math.abs(profitLoss)} />
                </div>
              </div>
            </div>
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: 11, color: 'var(--fqp-text-muted)' }}>盈亏率</div>
              <div style={{ fontSize: 18, fontWeight: 700, color }} className="fqp-mono">
                {profitRate >= 0 ? '+' : ''}{(profitRate * 100).toFixed(2)}%
              </div>
            </div>
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: 11, color: 'var(--fqp-text-muted)' }}>总投入</div>
              <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--fqp-text)' }} className="fqp-mono">
                ¥<CountUp value={stake} />
              </div>
            </div>
          </div>
        );
      })()}

      {/* ========== Distribution bar (only if total > 0) ========== */}
      {barTotal > 0 && (
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--fqp-text-muted)', marginBottom: 4 }}>
            <span>活动分布</span>
            <span>{barTotal.toLocaleString()} 总计</span>
          </div>
          <div
            style={{
              width: '100%', height: 8,
              background: 'var(--fqp-border-subtle)',
              borderRadius: 4, overflow: 'hidden',
              display: 'flex',
            }}
          >
            {barItems.map((item) => {
              if (item.value <= 0) return null;
              const pct = item.value / barTotal;
              return (
                <div
                  key={item.label}
                  style={{
                    width: `${pct * 100}%`, height: '100%',
                    background: item.color,
                    transition: 'width 0.6s ease',
                  }}
                  title={`${item.label}: ${item.value.toLocaleString()} (${(pct * 100).toFixed(1)}%)`}
                />
              );
            })}
          </div>
          <div style={{ display: 'flex', gap: 12, marginTop: 4, flexWrap: 'wrap' }}>
            {barItems.map((item) => (
              <span key={item.label} style={{ fontSize: 10, color: 'var(--fqp-text-muted)', display: 'flex', alignItems: 'center', gap: 3 }}>
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: item.color, display: 'inline-block' }} />
                {item.label} {item.value.toLocaleString()}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* ========== Divider ========== */}
      <div style={{ height: 1, background: 'var(--fqp-border-subtle)', margin: 0 }} />

      {/* ========== Bottom: Model status + Quick stats ========== */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        {/* Left: Models */}
        <div>
          <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--fqp-text-muted)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
            模型运行
          </div>
          {models.length === 0 ? (
            <div style={{ fontSize: 11, color: 'var(--fqp-text-muted)' }}>暂无模型</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {models.slice(0, 5).map((m) => (
                <div
                  key={m.model_version_id}
                  style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    padding: '4px 8px', background: 'var(--fqp-bg-glass)', borderRadius: 4, fontSize: 11,
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span
                      style={{
                        width: 6, height: 6, borderRadius: '50%',
                        background: m.sample_count > 0 ? 'var(--fqp-success)' : 'rgba(255,255,255,0.2)',
                        display: 'inline-block',
                      }}
                    />
                    <span style={{ color: 'var(--fqp-text)' }}>
                      {MODEL_LABELS[m.model_name] || m.model_name}
                    </span>
                  </div>
                  <span style={{ color: 'var(--fqp-text-muted)', fontSize: 10 }}>
                    v{m.version}
                    {m.hit_rate != null && <> · {(m.hit_rate * 100).toFixed(0)}%</>}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Right: Quick stats */}
        <div>
          <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--fqp-text-muted)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
            系统速览
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {pageStats ? (
              <>
                <MiniStat label="可分析比赛" value={pageStats.matchCount} unit="场" color="#3B82F6" />
                <MiniStat label="活跃推荐" value={pageStats.activeTicketCount} unit="张" color="#F5A524" />
                <MiniStat label="彩票记录" value={pageStats.ticketLedgerCount} unit="张" color="#22C55E" />
              </>
            ) : (
              <div style={{ fontSize: 11, color: 'var(--fqp-text-muted)' }}>暂无数据</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ---- Mini stat row ----
function MiniStat({ label, value, unit, color }: { label: string; value: number; unit: string; color: string }) {
  return (
    <div
      style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '3px 8px', borderRadius: 4, fontSize: 11,
        background: 'var(--fqp-bg-glass)',
      }}
    >
      <span style={{ color: 'var(--fqp-text-muted)' }}>{label}</span>
      <span style={{ color, fontWeight: 600 }} className="fqp-mono">
        <CountUp value={value} />{unit}
      </span>
    </div>
  );
}

// ---- Helper: hex → rgb(a) components ----
function hexToRgb(hex: string): string {
  const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
  if (!result) return '255,255,255';
  return `${parseInt(result[1], 16)},${parseInt(result[2], 16)},${parseInt(result[3], 16)}`;
}
