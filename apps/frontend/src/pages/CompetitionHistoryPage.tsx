import { useEffect, useState } from 'react';
import { api } from '../core/apiClient';
import { navigate } from '../core/router';
import type { CompetitionRound, CompetitionSummary } from '../core/types';
import { ApiError } from '../core/types';
import PageHeader from '../shared/components/PageHeader';
import ErrorState from '../shared/components/ErrorState';
import LoadingSpinner from '../shared/components/LoadingSpinner';
import EmptyState from '../shared/components/EmptyState';

function formatPct(v: number): string {
  const pct = v * 100;
  return `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`;
}

function roiColor(v: number): string {
  if (v > 0) return 'var(--fqp-ok, #22c55e)';
  if (v < 0) return 'var(--fqp-error, #ef4444)';
  return 'var(--fqp-text-muted, #888)';
}

export default function CompetitionHistoryPage() {
  const [rounds, setRounds] = useState<CompetitionRound[]>([]);
  const [summary, setSummary] = useState<CompetitionSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = () => {
    setLoading(true);
    setError(null);
    Promise.all([
      api.competition.rounds({ limit: 50 }),
      api.competition.summary(),
    ])
      .then(([roundsRes, summaryRes]) => {
        setRounds(roundsRes.rounds);
        setSummary(summaryRes);
        setLoading(false);
      })
      .catch((e) => {
        setError(e instanceof ApiError ? e.message : '加载失败');
        setLoading(false);
      });
  };

  useEffect(() => { fetchData(); }, []);

  if (loading) return <LoadingSpinner text="加载历史竞赛..." size="lg" />;
  if (error) return (
    <div>
      <PageHeader title="竞赛历史" />
      <ErrorState message={error} onRetry={fetchData} />
    </div>
  );

  return (
    <div>
      <PageHeader
        title="竞赛历史"
        subtitle={summary
          ? `${summary.total_rounds} 轮 · Agent ${summary.agent_wins} 胜 · 用户 ${summary.user_wins} 胜 · 平局 ${summary.draws}`
          : undefined}
      />

      {/* Summary bar — staggered entrance */}
      {summary && (
        <div style={{
          display: 'flex', gap: '16px', marginBottom: '20px',
          flexWrap: 'wrap',
        }}>
          {[
            { label: '总轮次', value: summary.total_rounds, color: 'var(--fqp-text)', borderColor: 'transparent' },
            { label: '🤖 Agent 胜', value: summary.agent_wins, color: '#3b82f6', borderColor: 'rgba(59,130,246,0.3)' },
            { label: '🧑 用户 胜', value: summary.user_wins, color: '#f59e0b', borderColor: 'rgba(245,158,11,0.3)' },
            { label: '🤝 平局', value: summary.draws, color: 'var(--fqp-text)', borderColor: 'transparent' },
          ].map((tile, i) => (
            <div key={tile.label} style={{
              flex: 1, minWidth: '120px', background: 'var(--fqp-panel)',
              borderRadius: '8px', padding: '14px', textAlign: 'center',
              border: `1px solid ${tile.borderColor}`,
              animation: `fqpPopIn 0.35s cubic-bezier(0.34,1.56,0.64,1) both`,
              animationDelay: `${i * 80}ms`,
            }}>
              <div style={{ fontSize: '12px', color: 'var(--fqp-text-muted)' }}>{tile.label}</div>
              <div style={{ fontSize: '20px', fontWeight: 700, color: tile.color }}>{tile.value}</div>
            </div>
          ))}
        </div>
      )}

      {/* Rounds table */}
      {rounds.length > 0 ? (
        <div className="fqp-card" style={{ padding: 0, overflow: 'hidden' }}>
          <table className="fqp-table" style={{ width: '100%', fontSize: '13px' }}>
            <thead>
              <tr>
                <th>轮次</th>
                <th>周期</th>
                <th>🤖 Agent ROI</th>
                <th>🧑 用户 ROI</th>
                <th>胜者</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              {rounds.map((r, i) => (
                <tr
                  key={r.id}
                  onClick={() => navigate(`/competition`)}
                  className="fqp-anim-listItemEnter"
                  style={{ cursor: 'pointer', animationDelay: `${i * 40}ms` }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = 'rgba(255,255,255,0.03)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = 'transparent';
                  }}
                >
                  <td style={{ fontWeight: 600 }}>{r.round_label}</td>
                  <td style={{ fontSize: '12px' }}>{r.round_start} → {r.round_end}</td>
                  <td className="fqp-mono" style={{ color: roiColor(r.agent_roi), fontWeight: 600 }}>
                    {formatPct(r.agent_roi)}
                  </td>
                  <td className="fqp-mono" style={{ color: roiColor(r.user_roi), fontWeight: 600 }}>
                    {formatPct(r.user_roi)}
                  </td>
                  <td>
                    {r.winner === 'agent' ? '🤖 Agent' :
                     r.winner === 'user' ? '🧑 用户' :
                     r.winner === 'draw' ? '🤝 平局' :
                     r.status === 'active' ? '—' : '—'}
                  </td>
                  <td>
                    <span style={{
                      display: 'inline-block', padding: '2px 8px', borderRadius: '10px',
                      fontSize: '11px', fontWeight: 500,
                      background: r.status === 'active' ? 'rgba(34,197,94,0.15)' : 'rgba(255,255,255,0.06)',
                      color: r.status === 'active' ? 'var(--fqp-ok, #22c55e)' : 'var(--fqp-text-muted)',
                    }}>
                      {r.status === 'active' ? '进行中' : '已结束'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState icon="📜" title="暂无历史记录" description="竞赛数据将在每轮结束后保存" />
      )}

      <div style={{ marginTop: '16px', textAlign: 'center' }}>
        <button
          className="fqp-btn fqp-btn-ghost"
          onClick={() => navigate('/competition')}
        >
          ⚔️ 查看当前竞赛 →
        </button>
      </div>
    </div>
  );
}
