import { useEffect, useState, useRef } from 'react';
import { api } from '../core/apiClient';
import { ApiError, type PoolAnalysis } from '../core/types';
import Card from '../shared/components/Card';
import StatusBadge from '../shared/components/StatusBadge';
import LoadingSpinner from '../shared/components/LoadingSpinner';
import ErrorState from '../shared/components/ErrorState';
import PageHeader from '../shared/components/PageHeader';
import TeamName from '../shared/components/TeamName';

// Count-up animation hook
function useCountUp(target: number, duration = 800) {
  const [val, setVal] = useState(0);
  const prevTarget = useRef(target);
  useEffect(() => {
    prevTarget.current = target;
    let rafId: number;
    const start = performance.now();
    const animate = (now: number) => {
      const t = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - t, 3);
      setVal(target * eased);
      if (t < 1) rafId = requestAnimationFrame(animate);
    };
    rafId = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(rafId);
  }, [target, duration]);
  return val;
}

const CLASS_LABELS: Record<string, string> = {
  dan: '胆',
  tuo: '拖',
  defense: '防守',
  normal: '普通',
};

const CLASS_COLORS: Record<string, string> = {
  dan: 'var(--fqp-success)',
  tuo: 'var(--fqp-text-muted)',
  defense: 'var(--fqp-warning)',
  normal: 'var(--fqp-text-muted)',
};

export default function PoolPage() {
  const [analysis, setAnalysis] = useState<PoolAnalysis | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [budget, setBudget] = useState(256);
  const [strategy, setStrategy] = useState<'balanced' | 'conservative' | 'aggressive'>('balanced');
  const [activeTab, setActiveTab] = useState<'14场' | '任九' | '分析'>('14场');

  const isDataPending = error !== null && (error.includes('模型预测') || error.includes('官方14场彩池'));
  const dataPendingMessage = error?.includes('模型预测')
    ? `${error}。官方赔率和预测数据齐全后会自动生成方案。`
    : '官方彩池已经更新，正在等待完整赔率和预测数据。数据齐全后会自动生成方案。';

  const loadAnalysis = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.pool.analyze({ budget, strategy });
      setAnalysis(data);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAnalysis();
  }, []);

  const formatPct = (v: number) => (v * 100).toFixed(2) + '%';
  const formatProb = (v: number) => (v * 100).toFixed(1) + '%';

  // Count-up animated values
  const hit14Count = useCountUp(analysis ? analysis.monte_carlo.hit14_prob * 100 : 0, 1000);
  const hit13Count = useCountUp(analysis ? analysis.monte_carlo.hit13_prob * 100 : 0, 900);
  const rx9Count = useCountUp(analysis ? analysis.monte_carlo.rx9_prob * 100 : 0, 900);
  const comboCost = useCountUp(analysis ? analysis.full_combinations.total_cost : 0, 800);
  const simCount = useCountUp(analysis ? analysis.monte_carlo.simulations : 0, 600);

  return (
    <div>
      <PageHeader
        title="传统足彩 14场/任九"
        lastUpdated={loading ? '加载中…' : analysis?.generated_at || '暂无可用分析'}
      />

      {/* Controls */}
      <Card style={{ marginBottom: '20px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px', flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <label style={{ fontSize: '13px', color: 'var(--fqp-text-muted)' }}>策略</label>
            <select
              value={strategy}
              onChange={(e) => setStrategy(e.target.value as typeof strategy)}
              style={{
                padding: '6px 12px',
                background: 'var(--fqp-panel)',
                color: 'var(--fqp-text)',
                border: '1px solid var(--fqp-border)',
                borderRadius: '4px',
                fontSize: '13px',
              }}
            >
              <option value="conservative">保守</option>
              <option value="balanced">均衡</option>
              <option value="aggressive">激进</option>
            </select>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <label style={{ fontSize: '13px', color: 'var(--fqp-text-muted)' }}>预算</label>
            <input
              type="number"
              value={budget}
              onChange={(e) => setBudget(Number(e.target.value))}
              min={2}
              max={10000}
              step={2}
              style={{
                width: '80px',
                padding: '6px 12px',
                background: 'var(--fqp-panel)',
                color: 'var(--fqp-text)',
                border: '1px solid var(--fqp-border)',
                borderRadius: '4px',
                fontSize: '13px',
              }}
            />
            <span style={{ fontSize: '13px', color: 'var(--fqp-text-muted)' }}>元</span>
          </div>
          <button
            onClick={loadAnalysis}
            disabled={loading}
            style={{
              marginLeft: 'auto',
              padding: '8px 20px',
              background: 'var(--fqp-accent)',
              color: '#fff',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer',
              fontSize: '13px',
              fontWeight: 600,
            }}
          >
            {loading ? '分析中...' : '刷新分析'}
          </button>
        </div>
      </Card>

      {loading && <LoadingSpinner text="正在运行蒙特卡洛模拟..." size="lg" />}
      {error && isDataPending && (
        <div
          role="status"
          style={{
            padding: '24px',
            marginBottom: '20px',
            background: 'rgba(252, 186, 3, 0.08)',
            border: '1px solid rgba(252, 186, 3, 0.28)',
            borderRadius: '8px',
          }}
        >
          <div style={{ fontSize: '16px', fontWeight: 600, color: 'var(--fqp-warning)' }}>
            推荐方案准备中
          </div>
          <div style={{ marginTop: '8px', color: 'var(--fqp-text-muted)', fontSize: '13px', lineHeight: 1.6 }}>
            {dataPendingMessage}
          </div>
          <button className="fqp-btn fqp-btn-secondary" onClick={loadAnalysis} style={{ marginTop: '16px' }}>
            刷新数据
          </button>
        </div>
      )}
      {error && !isDataPending && <ErrorState message={error} onRetry={loadAnalysis} />}

      {analysis && !loading && (
        <>
          <div
            role="status"
            style={{
              padding: '14px 18px',
              marginBottom: '20px',
              background: analysis.analysis_mode === 'historical'
                ? 'rgba(252, 186, 3, 0.08)'
                : 'rgba(34, 197, 94, 0.08)',
              border: `1px solid ${analysis.analysis_mode === 'historical'
                ? 'rgba(252, 186, 3, 0.3)'
                : 'rgba(34, 197, 94, 0.3)'}`,
              borderRadius: '8px',
            }}
          >
            <div
              style={{
                fontSize: '15px',
                fontWeight: 700,
                color: analysis.analysis_mode === 'historical'
                  ? 'var(--fqp-warning)'
                  : 'var(--fqp-success)',
              }}
            >
              {analysis.analysis_mode === 'historical' ? '历史期次复盘' : '当前在售期次'}
            </div>
            <div style={{ marginTop: '5px', color: 'var(--fqp-text-muted)', fontSize: '13px', lineHeight: 1.6 }}>
              {analysis.analysis_mode === 'historical'
                ? `第 ${analysis.issue.issue_no} 期已停售，本页仅用于检验模型与组合逻辑，不是当前投注推荐。`
                : `第 ${analysis.issue.issue_no} 期正在销售，方案基于当前官方期次数据生成。`}
            </div>
          </div>

          {/* Monte Carlo summary cards — staggered entrance */}
          <div className="fqp-grid-4" style={{ marginBottom: '20px' }}>
            <Card title="命中14场概率" entranceDelay={0}>
              <div className="fqp-stat-card" style={{ padding: 0 }}>
                <div className="fqp-stat-value" style={{ color: 'var(--fqp-success)' }}>
                  {hit14Count.toFixed(2)}%
                </div>
                <div className="fqp-stat-sub">
                  {simCount.toLocaleString(undefined, { maximumFractionDigits: 0 })} 次模拟
                </div>
              </div>
            </Card>
            <Card title="命中13场概率" entranceDelay={80}>
              <div className="fqp-stat-card" style={{ padding: 0 }}>
                <div className="fqp-stat-value" style={{ color: 'var(--fqp-accent)' }}>
                  {hit13Count.toFixed(2)}%
                </div>
                <div className="fqp-stat-sub">至少命中13场</div>
              </div>
            </Card>
            <Card title="任九命中概率" entranceDelay={160}>
              <div className="fqp-stat-card" style={{ padding: 0 }}>
                <div className="fqp-stat-value" style={{ color: 'var(--fqp-accent)' }}>
                  {rx9Count.toFixed(2)}%
                </div>
                <div className="fqp-stat-sub">9场单选命中</div>
              </div>
            </Card>
            <Card title="组合成本" entranceDelay={240}>
              <div className="fqp-stat-card" style={{ padding: 0 }}>
                <div className="fqp-stat-value">
                  ¥{comboCost.toFixed(0)}
                </div>
                <div className="fqp-stat-sub">
                  {analysis.full_combinations.count} 注 × ¥2
                </div>
              </div>
            </Card>
          </div>

          {/* Warnings — slide in from top */}
          {analysis.warnings.length > 0 && (
            <div style={{ marginBottom: '20px' }}>
              {analysis.warnings.map((w, i) => (
                <div
                  key={i}
                  style={{
                    padding: '8px 16px',
                    background: 'rgba(252, 186, 3, 0.1)',
                    border: '1px solid rgba(252, 186, 3, 0.3)',
                    borderRadius: '4px',
                    fontSize: '13px',
                    color: 'var(--fqp-warning)',
                    marginBottom: '4px',
                    animation: `fqpSlideUpBounce 0.4s ease both`,
                    animationDelay: `${i * 80}ms`,
                  }}
                >
                  ⚠ {w}
                </div>
              ))}
            </div>
          )}

          {/* Tab navigation */}
          <div style={{ display: 'flex', gap: '4px', marginBottom: '0' }}>
            {['14场', '任九', '分析'].map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab as typeof activeTab)}
                style={{
                  padding: '10px 20px',
                  background: activeTab === tab ? 'var(--fqp-panel)' : 'transparent',
                  color: activeTab === tab ? 'var(--fqp-text)' : 'var(--fqp-text-muted)',
                  border: `1px solid ${activeTab === tab ? 'var(--fqp-border)' : 'transparent'}`,
                  borderBottom: 'none',
                  borderRadius: '4px 4px 0 0',
                  cursor: 'pointer',
                  fontSize: '13px',
                  fontWeight: activeTab === tab ? 600 : 400,
                }}
              >
                {tab}
              </button>
            ))}
          </div>

          <Card style={activeTab === '14场' ? { borderTopLeftRadius: '0' } : undefined}>
            {/* Tab content with transition */}
            <div key={activeTab} className="fqp-anim-fadeIn">
            {/* 14场 tab */}
            {activeTab === '14场' && (
              <>
                {/* Classification summary */}
                <div style={{ display: 'flex', gap: '16px', marginBottom: '16px', flexWrap: 'wrap' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <span style={{ fontSize: '12px', color: 'var(--fqp-text-muted)' }}>胆</span>
                    <StatusBadge status="ok" label={`${analysis.classification.dan.length} 场`} dot />
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <span style={{ fontSize: '12px', color: 'var(--fqp-text-muted)' }}>拖</span>
                    <StatusBadge status="warning" label={`${analysis.classification.tuo.length} 场`} dot />
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <span style={{ fontSize: '12px', color: 'var(--fqp-text-muted)' }}>防守</span>
                    <StatusBadge status="error" label={`${analysis.classification.defense.length} 场`} dot />
                  </div>
                </div>

                {/* Match table */}
                <div className="fqp-data-table" style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid var(--fqp-border)' }}>
                        <th style={{ padding: '10px 8px', textAlign: 'left', color: 'var(--fqp-text-muted)', fontWeight: 400, fontSize: '11px' }}>#</th>
                        <th style={{ padding: '10px 8px', textAlign: 'left', color: 'var(--fqp-text-muted)', fontWeight: 400, fontSize: '11px' }}>比赛</th>
                        <th style={{ padding: '10px 8px', textAlign: 'center', color: 'var(--fqp-text-muted)', fontWeight: 400, fontSize: '11px' }}>联赛</th>
                        <th style={{ padding: '10px 8px', textAlign: 'center', color: 'var(--fqp-text-muted)', fontWeight: 400, fontSize: '11px' }}>主胜</th>
                        <th style={{ padding: '10px 8px', textAlign: 'center', color: 'var(--fqp-text-muted)', fontWeight: 400, fontSize: '11px' }}>平局</th>
                        <th style={{ padding: '10px 8px', textAlign: 'center', color: 'var(--fqp-text-muted)', fontWeight: 400, fontSize: '11px' }}>主负</th>
                        <th style={{ padding: '10px 8px', textAlign: 'center', color: 'var(--fqp-text-muted)', fontWeight: 400, fontSize: '11px' }}>首选</th>
                        <th style={{ padding: '10px 8px', textAlign: 'center', color: 'var(--fqp-text-muted)', fontWeight: 400, fontSize: '11px' }}>冷门指数</th>
                        <th style={{ padding: '10px 8px', textAlign: 'center', color: 'var(--fqp-text-muted)', fontWeight: 400, fontSize: '11px' }}>分类</th>
                      </tr>
                    </thead>
                    <tbody>
                      {analysis.matches.map((m, i) => (
                        <tr
                          key={i}
                          className="fqp-anim-listItemEnter"
                          style={{
                            borderBottom: '1px solid var(--fqp-border-light)',
                            background: i % 2 === 0 ? 'transparent' : 'var(--fqp-border-light)',
                            animationDelay: `${i * 40}ms`,
                          }}
                        >
                          <td style={{ padding: '10px 8px', color: 'var(--fqp-text-muted)', fontSize: '12px' }}>
                            {i + 1}
                          </td>
                          <td style={{ padding: '10px 8px' }}>
                            <TeamName name={m.home_team} style={{ fontWeight: 600 }} />
                            <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: '11px', color: 'var(--fqp-text-muted)' }}>
                              <span>vs</span><TeamName name={m.away_team} size={16} />
                            </div>
                          </td>
                          <td style={{ padding: '10px 8px', textAlign: 'center', fontSize: '12px', color: 'var(--fqp-text-muted)' }}>
                            {m.league}
                          </td>
                          <td style={{ padding: '10px 8px', textAlign: 'center' }}>
                            <span style={{
                              fontWeight: m.max_prob_option === '3' ? 700 : 400,
                              color: m.max_prob_option === '3' ? 'var(--fqp-success)' : 'var(--fqp-text)',
                            }}>
                              {formatProb(m.prob_home)}
                            </span>
                          </td>
                          <td style={{ padding: '10px 8px', textAlign: 'center' }}>
                            <span style={{
                              fontWeight: m.max_prob_option === '1' ? 700 : 400,
                              color: m.max_prob_option === '1' ? 'var(--fqp-warning)' : 'var(--fqp-text)',
                            }}>
                              {formatProb(m.prob_draw)}
                            </span>
                          </td>
                          <td style={{ padding: '10px 8px', textAlign: 'center' }}>
                            <span style={{
                              fontWeight: m.max_prob_option === '0' ? 700 : 400,
                              color: m.max_prob_option === '0' ? 'var(--fqp-red-neon)' : 'var(--fqp-text)',
                            }}>
                              {formatProb(m.prob_away)}
                            </span>
                          </td>
                          <td style={{ padding: '10px 8px', textAlign: 'center' }}>
                            <span style={{
                              display: 'inline-block',
                              padding: '2px 8px',
                              borderRadius: '3px',
                              background: 'rgba(99,102,241,0.2)',
                              color: 'var(--fqp-accent)',
                              fontWeight: 700,
                              fontSize: '12px',
                            }}>
                              {m.max_prob_option}
                            </span>
                          </td>
                          <td style={{ padding: '10px 8px', textAlign: 'center' }}>
                            <div style={{
                              display: 'inline-block',
                              padding: '2px 6px',
                              borderRadius: '3px',
                              fontSize: '12px',
                              color: m.cold_gate_index > 0.4 ? 'var(--fqp-warning)' : 'var(--fqp-text-muted)',
                              background: m.cold_gate_index > 0.4 ? 'rgba(252,186,3,0.15)' : 'transparent',
                            }}>
                              {(m.cold_gate_index * 100).toFixed(1)}%
                            </div>
                          </td>
                          <td style={{ padding: '10px 8px', textAlign: 'center' }}>
                            <span style={{
                              display: 'inline-block',
                              padding: '2px 8px',
                              borderRadius: '3px',
                              fontSize: '11px',
                              fontWeight: 600,
                              color: CLASS_COLORS[m.classification] || 'var(--fqp-text-muted)',
                              background: m.classification === 'defense'
                                ? 'rgba(252,186,3,0.15)'
                                : m.classification === 'dan'
                                  ? 'rgba(52,211,153,0.15)'
                                  : 'transparent',
                            }}>
                              {CLASS_LABELS[m.classification] || m.classification}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* Combinations preview */}
                {analysis.full_combinations.combinations.length > 0 && (
                  <div style={{ marginTop: '20px' }}>
                    <h4 style={{ fontSize: '14px', marginBottom: '12px', color: 'var(--fqp-text-muted)' }}>
                      组合预览（前 {Math.min(analysis.full_combinations.combinations.length, 10)} / {analysis.full_combinations.count} 注）
                    </h4>
                    <div className="fqp-data-table" style={{ overflowX: 'auto' }}>
                      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
                        <thead>
                          <tr style={{ borderBottom: '1px solid var(--fqp-border)' }}>
                            <th style={{ padding: '8px', textAlign: 'left', color: 'var(--fqp-text-muted)', fontWeight: 400 }}>#</th>
                            <th style={{ padding: '8px', textAlign: 'left', color: 'var(--fqp-text-muted)', fontWeight: 400 }}>选项</th>
                            <th style={{ padding: '8px', textAlign: 'center', color: 'var(--fqp-text-muted)', fontWeight: 400 }}>命中概率</th>
                            <th style={{ padding: '8px', textAlign: 'center', color: 'var(--fqp-text-muted)', fontWeight: 400 }}>冷门覆盖</th>
                          </tr>
                        </thead>
                        <tbody>
                          {analysis.full_combinations.combinations.slice(0, 10).map((c, i) => (
                            <tr key={i} style={{ borderBottom: '1px solid var(--fqp-border-light)' }}>
                              <td style={{ padding: '8px', color: 'var(--fqp-text-muted)' }}>{i + 1}</td>
                              <td style={{ padding: '8px', fontFamily: 'monospace', letterSpacing: '4px' }}>
                                {c.selections.join(' ')}
                              </td>
                              <td style={{ padding: '8px', textAlign: 'center', color: 'var(--fqp-accent)' }}>
                                {formatPct(c.estimated_hit_prob)}
                              </td>
                              <td style={{ padding: '8px', textAlign: 'center' }}>
                                {formatPct(c.cold_gate_coverage)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </>
            )}

            {/* 任九 tab */}
            {activeTab === '任九' && (
              <>
                <div style={{ marginBottom: '16px' }}>
                  <h4 style={{ fontSize: '14px', marginBottom: '8px', color: 'var(--fqp-text)' }}>
                    任九选场（从14场中自动筛选9场）
                  </h4>
                  <p style={{ fontSize: '12px', color: 'var(--fqp-text-muted)' }}>
                    按数据质量和不确定性排序，排除最不确定的5场
                  </p>
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginBottom: '16px' }}>
                  {analysis.rx9.selected_matches.map((m, i) => (
                    <span
                      key={i}
                      style={{
                        padding: '6px 12px',
                        background: 'rgba(99,102,241,0.1)',
                        border: '1px solid rgba(99,102,241,0.3)',
                        borderRadius: '4px',
                        fontSize: '13px',
                        color: 'var(--fqp-accent)',
                        animation: `fqpPopIn 0.3s cubic-bezier(0.34,1.56,0.64,1) both`,
                        animationDelay: `${i * 60}ms`,
                      }}
                    >
                      {i + 1}. {m}
                    </span>
                  ))}
                </div>
                <div className="fqp-grid-2">
                  <Card title="任九组合统计">
                    <div style={{ padding: '8px 0' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                        <span style={{ color: 'var(--fqp-text-muted)', fontSize: '13px' }}>组合注数</span>
                        <span className="fqp-mono" style={{ fontSize: '13px' }}>{analysis.rx9.combinations_count}</span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                        <span style={{ color: 'var(--fqp-text-muted)', fontSize: '13px' }}>总成本</span>
                        <span className="fqp-mono" style={{ fontSize: '13px' }}>¥{analysis.rx9.total_cost}</span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                        <span style={{ color: 'var(--fqp-text-muted)', fontSize: '13px' }}>命中概率</span>
                        <span className="fqp-mono" style={{ fontSize: '13px', color: 'var(--fqp-accent)' }}>
                          {formatPct(analysis.monte_carlo.rx9_prob)}
                        </span>
                      </div>
                    </div>
                  </Card>
                  <Card title="任九说明">
                    <div style={{ fontSize: '13px', color: 'var(--fqp-text-muted)', lineHeight: '1.6' }}>
                      <p>任选九场是从14场比赛中选出9场进行投注的玩法。</p>
                      <p>本系统自动排除不确定性最高、数据质量最低的比赛，保留最可靠的9场进行胆拖优化。</p>
                      <p style={{ marginTop: '8px', color: 'var(--fqp-warning)', fontSize: '12px' }}>
                        ⚠ 任九不支持复式过关，每场单选一个结果。
                      </p>
                    </div>
                  </Card>
                </div>
              </>
            )}

            {/* 分析 tab */}
            {activeTab === '分析' && (
              <>
                <div className="fqp-grid-2" style={{ marginBottom: '16px' }}>
                  <Card title="胆拖防守分布">
                    <div style={{ padding: '8px 0' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
                        <div style={{ flex: 1 }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', marginBottom: '4px' }}>
                            <span style={{ color: 'var(--fqp-success)' }}>胆 ({analysis.classification.dan.length})</span>
                          </div>
                          <div style={{ height: '6px', background: 'var(--fqp-panel)', borderRadius: '3px', overflow: 'hidden' }}>
                            <div style={{
                              height: '100%',
                              width: `${(analysis.classification.dan.length / 14) * 100}%`,
                              background: 'var(--fqp-success)',
                              borderRadius: '3px',
                              transition: 'width 0.8s cubic-bezier(0.34,1.56,0.64,1)',
                            }} />
                          </div>
                        </div>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
                        <div style={{ flex: 1 }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', marginBottom: '4px' }}>
                            <span style={{ color: 'var(--fqp-text-muted)' }}>拖 ({analysis.classification.tuo.length})</span>
                          </div>
                          <div style={{ height: '6px', background: 'var(--fqp-panel)', borderRadius: '3px', overflow: 'hidden' }}>
                            <div style={{
                              height: '100%',
                              width: `${(analysis.classification.tuo.length / 14) * 100}%`,
                              background: 'var(--fqp-border)',
                              borderRadius: '3px',
                              transition: 'width 0.8s cubic-bezier(0.34,1.56,0.64,1)',
                            }} />
                          </div>
                        </div>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <div style={{ flex: 1 }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', marginBottom: '4px' }}>
                            <span style={{ color: 'var(--fqp-warning)' }}>防守 ({analysis.classification.defense.length})</span>
                          </div>
                          <div style={{ height: '6px', background: 'var(--fqp-panel)', borderRadius: '3px' }}>
                            <div style={{
                              height: '100%',
                              width: `${(analysis.classification.defense.length / 14) * 100}%`,
                              background: 'var(--fqp-warning)',
                              borderRadius: '3px',
                            }} />
                          </div>
                        </div>
                      </div>
                    </div>
                  </Card>

                  <Card title="蒙特卡洛模拟详情">
                    <div style={{ padding: '8px 0' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                        <span style={{ color: 'var(--fqp-text-muted)', fontSize: '13px' }}>模拟次数</span>
                        <span className="fqp-mono" style={{ fontSize: '13px' }}>
                          {analysis.monte_carlo.simulations.toLocaleString()}
                        </span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                        <span style={{ color: 'var(--fqp-text-muted)', fontSize: '13px' }}>命中14场概率</span>
                        <span className="fqp-mono" style={{ fontSize: '13px', color: 'var(--fqp-success)' }}>
                          {formatPct(analysis.monte_carlo.hit14_prob)}
                        </span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                        <span style={{ color: 'var(--fqp-text-muted)', fontSize: '13px' }}>命中13场概率</span>
                        <span className="fqp-mono" style={{ fontSize: '13px', color: 'var(--fqp-accent)' }}>
                          {formatPct(analysis.monte_carlo.hit13_prob)}
                        </span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                        <span style={{ color: 'var(--fqp-text-muted)', fontSize: '13px' }}>任九命中概率</span>
                        <span className="fqp-mono" style={{ fontSize: '13px', color: 'var(--fqp-accent)' }}>
                          {formatPct(analysis.monte_carlo.rx9_prob)}
                        </span>
                      </div>
                    </div>
                  </Card>
                </div>

                {/* Dan/Tuo/Defense detail */}
                <Card title="胆拖防守明细">
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '16px', fontSize: '13px' }}>
                    <div>
                      <h5 style={{ color: 'var(--fqp-success)', marginBottom: '8px', fontSize: '13px' }}>
                        🎯 胆 ({analysis.classification.dan.length} 场)
                      </h5>
                      {analysis.classification.dan.map((m, i) => (
                        <div key={i} style={{ padding: '4px 0', color: 'var(--fqp-text)' }}>{m}</div>
                      ))}
                    </div>
                    <div>
                      <h5 style={{ color: 'var(--fqp-text-muted)', marginBottom: '8px', fontSize: '13px' }}>
                        📋 拖 ({analysis.classification.tuo.length} 场)
                      </h5>
                      {analysis.classification.tuo.map((m, i) => (
                        <div key={i} style={{ padding: '4px 0', color: 'var(--fqp-text)' }}>{m}</div>
                      ))}
                    </div>
                    <div>
                      <h5 style={{ color: 'var(--fqp-warning)', marginBottom: '8px', fontSize: '13px' }}>
                        🛡️ 防守 ({analysis.classification.defense.length} 场)
                      </h5>
                      {analysis.classification.defense.map((m, i) => (
                        <div key={i} style={{ padding: '4px 0', color: 'var(--fqp-text)' }}>{m}</div>
                      ))}
                    </div>
                  </div>
                </Card>
              </>
            )}
            </div>
          </Card>
        </>
      )}
    </div>
  );
}
