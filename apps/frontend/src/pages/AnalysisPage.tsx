import { useEffect, useState, useCallback } from 'react';
import { api } from '../core/apiClient';
import { ApiError } from '../core/types';
import type {
  ModelCompareItem,
  ModelPlayTypeRecommendation,
  RadarDimension,
  FeatureRanking,
  ShapEntry,
  ConditionSegment,
  ConditionPerformanceData,
  FeatureModelInfo,
} from '../core/types';
import PageHeader from '../shared/components/PageHeader';
import Card from '../shared/components/Card';
import ChartCard from '../shared/components/ChartCard';
import ErrorState from '../shared/components/ErrorState';
import DisclaimerBanner from '../shared/components/DisclaimerBanner';

// ---------------------------------------------------------------------------
// Tab definitions
// ---------------------------------------------------------------------------

type TabKey = 'compare' | 'importance' | 'shap' | 'condition';

const TABS: { key: TabKey; label: string; icon: string }[] = [
  { key: 'compare', label: '模型对比', icon: '📊' },
  { key: 'importance', label: '特征重要性', icon: '🔍' },
  { key: 'shap', label: 'SHAP 解释', icon: '💧' },
  { key: 'condition', label: '条件表现', icon: '🎯' },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Normalize a metric to 0-1 for radar chart. Invert if lower is better. */
function normalizeForRadar(
  value: number,
  allValues: number[],
  invert: boolean,
): number {
  const min = Math.min(...allValues);
  const max = Math.max(...allValues);
  if (max === min) return 0.5;
  const norm = (value - min) / (max - min);
  return invert ? 1 - norm : norm;
}

// ---------------------------------------------------------------------------
// Tab: 模型对比
// ---------------------------------------------------------------------------

function ModelCompareTab() {
  const [models, setModels] = useState<ModelCompareItem[]>([]);
  const [dimensions, setDimensions] = useState<RadarDimension[]>([]);
  const [recommendations, setRecommendations] = useState<ModelPlayTypeRecommendation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      api.analysis.modelCompare(),
      api.analysis.recommendations({ top_n: 6 }),
    ])
      .then(([res, recRes]) => {
        if (res.status === 'ok') {
          setModels(res.models);
          setDimensions(res.radar_dimensions);
        }
        setRecommendations(recRes.recommendations || []);
        setLoading(false);
      })
      .catch((e) => {
        setError(e instanceof ApiError ? e.message : '加载失败');
        setLoading(false);
      });
  }, []);

  // Build radar chart option
  const radarOption = buildRadarOption(models, dimensions);

  if (error) return <ErrorState message={error} />;
  if (loading) return <div style={{ padding: 32, color: 'var(--fqp-text-muted)' }}>加载模型对比数据...</div>;
  if (models.length === 0) {
    return (
      <Card title="模型对比">
        <div className="fqp-empty-state">
          <div className="fqp-empty-icon">📭</div>
          <div className="fqp-empty-title">暂无模型对比数据</div>
          <div className="fqp-empty-desc">需要先运行回测和模型评估任务</div>
        </div>
      </Card>
    );
  }

  // Play type display names
  const PLAY_TYPE_NAMES: Record<string, string> = {
    spf: '胜平负',
    rqspf: '让球胜平负',
    zjq: '总进球数',
    bf: '比分',
    bqc: '半全场',
    // legacy aliases (backward compat)
    total_goals: '总进球数',
    score: '比分',
    half_full: '半全场',
  };
  // Recommendation rank badges
  const RANK_BADGES = ['🥇', '🥈', '🥉', '4️⃣', '5️⃣', '6️⃣'];

  return (
    <div>
      {/* Top recommendations */}
      {recommendations.length > 0 && (
        <Card style={{ marginBottom: 20, borderColor: 'rgba(34,197,94,0.35)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
            <span style={{ fontSize: 18 }}>🏆</span>
            <span style={{ fontWeight: 700, fontSize: 15, color: 'var(--fqp-text)' }}>
              最佳 模型×玩法 组合推荐
            </span>
            <span style={{ fontSize: 11, color: 'var(--fqp-text-muted)', marginLeft: 4 }}>
              （按已结算比赛命中率排序）
            </span>
          </div>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
              gap: 12,
            }}
          >
            {recommendations.map((rec, i) => (
              <div
                key={`${rec.model_name}-${rec.play_type}`}
                style={{
                  padding: '14px 16px',
                  borderRadius: 'var(--fqp-radius-sm)',
                  background: i === 0 ? 'rgba(34,197,94,0.08)' : 'var(--fqp-panel)',
                  border: `1px solid ${i === 0 ? 'rgba(34,197,94,0.3)' : 'var(--fqp-border)'}`,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 12,
                }}
              >
                <span style={{ fontSize: 22, flexShrink: 0 }}>{RANK_BADGES[i]}</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--fqp-text)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {rec.model_name}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--fqp-text-muted)' }}>
                    {PLAY_TYPE_NAMES[rec.play_type] || rec.play_type}
                    <span style={{ marginLeft: 8 }}>
                      {rec.wins}/{rec.total} 场
                    </span>
                  </div>
                </div>
                <div
                  style={{
                    fontSize: 20,
                    fontWeight: 800,
                    fontFamily: 'var(--fqp-font-mono)',
                    flexShrink: 0,
                    color: rec.hit_rate >= 0.55 ? 'var(--fqp-success)'
                      : rec.hit_rate >= 0.45 ? 'var(--fqp-warning)'
                      : 'var(--fqp-red-neon)',
                  }}
                >
                  {(rec.hit_rate * 100).toFixed(0)}%
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Radar chart */}
      <ChartCard title="模型综合对比（雷达图）" option={radarOption} height={420} />

      {/* Ranking table */}
      <Card title="指标排名" style={{ marginTop: 20 }}>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px', minWidth: 900 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--fqp-border)' }}>
                <th style={thS}>排名</th>
                <th style={thS}>模型</th>
                <th style={thS}>评估数</th>
                <th style={thS}>Brier ↓</th>
                <th style={thS}>LogLoss ↓</th>
                <th style={thS}>ROI</th>
                <th style={thS}>胜率</th>
                <th style={thS}>夏普</th>
                <th style={thS}>最大回撤</th>
                <th style={thS}>盈利因子</th>
                <th style={thS}>总盈亏</th>
              </tr>
            </thead>
            <tbody>
              {models.map((m, i) => (
                <tr key={m.name} style={{ borderBottom: '1px solid var(--fqp-border-light)', backgroundColor: i === 0 ? 'rgba(34,197,94,0.05)' : undefined, animation: `fqpListItemEnter 0.25s ease both`, animationDelay: `${i * 40}ms` }}>
                  <td style={tdS}>
                    {i === 0 ? '🥇' : i === 1 ? '🥈' : i === 2 ? '🥉' : i + 1}
                  </td>
                  <td style={{ ...tdS, fontWeight: 600 }}>{m.name}</td>
                  <td style={{ ...tdS, textAlign: 'center' }} className="fqp-mono">{m.n_predictions}</td>
                  <td style={tdRight} className="fqp-mono">{m.brier.toFixed(4)}</td>
                  <td style={tdRight} className="fqp-mono">{m.log_loss.toFixed(4)}</td>
                  <td style={tdRight} className="fqp-mono">
                    <span style={{ color: (m.roi ?? 0) >= 0 ? 'var(--fqp-success)' : 'var(--fqp-red-neon)' }}>
                      {m.roi !== undefined ? `${((m.roi ?? 0) * 100).toFixed(1)}%` : '—'}
                    </span>
                  </td>
                  <td style={tdRight} className="fqp-mono">
                    {m.hit_rate !== undefined ? `${(m.hit_rate * 100).toFixed(1)}%` : '—'}
                  </td>
                  <td style={tdRight} className="fqp-mono">{m.sharpe?.toFixed(2) ?? '—'}</td>
                  <td style={tdRight} className="fqp-mono">
                    <span style={{ color: 'var(--fqp-red-neon)' }}>
                      {m.max_drawdown_pct !== undefined ? `${m.max_drawdown_pct.toFixed(1)}%` : '—'}
                    </span>
                  </td>
                  <td style={tdRight} className="fqp-mono">{m.profit_factor?.toFixed(2) ?? '—'}</td>
                  <td style={tdRight} className="fqp-mono">
                    <span style={{ color: (m.total_profit ?? 0) >= 0 ? 'var(--fqp-success)' : 'var(--fqp-red-neon)' }}>
                      {m.total_profit !== undefined ? `${m.total_profit >= 0 ? '+' : ''}${m.total_profit.toFixed(2)}` : '—'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

function buildRadarOption(models: ModelCompareItem[], dimensions: RadarDimension[]) {
  // Radar dimensions: brier (inv), log_loss (inv), roi, sharpe, hit_rate, profit_factor
  const radarKeys = ['brier', 'log_loss', 'roi', 'sharpe', 'hit_rate', 'profit_factor'] as const;
  const radarLabels = ['Brier ↓', 'LogLoss ↓', 'ROI', '夏普', '胜率', '盈利因子'];
  const invertFlags = [true, true, false, false, false, false];

  // Collect all values per dimension
  const allValues: Record<string, number[]> = {};
  for (let i = 0; i < radarKeys.length; i++) {
    const key = radarKeys[i];
    allValues[key] = models.map((m) => {
      const v = (m as Record<string, unknown>)[key];
      return typeof v === 'number' ? v : 0;
    });
  }

  const indicator = radarLabels.map((label, i) => ({
    name: label,
    max: 1,
    min: 0,
  }));

  const seriesData = models.map((m) => {
    const values = radarKeys.map((key, i) => {
      const v = (m as Record<string, unknown>)[key];
      const val = typeof v === 'number' ? v : 0;
      return normalizeForRadar(val, allValues[key], invertFlags[i]);
    });
    return { name: m.name, value: values };
  });

  // Color palette
  const colors = ['#22c55e', '#3b82f6', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4'];

  return {
    tooltip: {
      trigger: 'item',
    },
    legend: {
      bottom: 0,
      data: models.map((m) => m.name),
      textStyle: { color: '#C4C4CC', fontSize: 12 },
    },
    radar: {
      center: ['50%', '48%'],
      radius: '65%',
      indicator,
      axisName: { color: '#C4C4CC', fontSize: 12 },
      shape: 'polygon',
      splitArea: {
        areaStyle: { color: ['rgba(255,255,255,0.02)', 'rgba(255,255,255,0.04)'] },
      },
      axisLine: { lineStyle: { color: 'rgba(255,255,255,0.1)' } },
      splitLine: { lineStyle: { color: 'rgba(255,255,255,0.08)' } },
    },
    series: [
      {
        type: 'radar',
        data: seriesData,
        symbol: 'circle',
        symbolSize: 4,
        lineStyle: { width: 2 },
        areaStyle: { opacity: 0.08 },
        emphasis: { lineStyle: { width: 3 } },
        color: colors,
      },
    ],
  };
}

// ---------------------------------------------------------------------------
// Tab: 特征重要性
// ---------------------------------------------------------------------------

function FeatureImportanceTab() {
  const [rankings, setRankings] = useState<FeatureRanking[]>([]);
  const [modelInfo, setModelInfo] = useState<FeatureModelInfo | null>(null);
  const [method, setMethod] = useState<'permutation' | 'gain'>('permutation');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback((m: 'permutation' | 'gain') => {
    setLoading(true);
    setError(null);
    Promise.all([
      api.analysis.featureImportance({ method: m, top_n: 20 }),
      api.analysis.featureModelInfo(),
    ])
      .then(([impRes, infoRes]) => {
        if (impRes.status === 'ok') {
          const r = impRes.rankings as FeatureRanking[];
          setRankings(r);
        }
        if (infoRes.status === 'ok') {
          setModelInfo(infoRes);
        }
        setLoading(false);
      })
      .catch((e) => {
        setError(e instanceof ApiError ? e.message : '加载失败');
        setLoading(false);
      });
  }, []);

  useEffect(() => {
    fetchData(method);
  }, [method, fetchData]);

  if (error) return <ErrorState message={error} />;

  // Build horizontal bar chart
  const barOption = {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: { name: string; value: number }[]) => {
        const p = params[0];
        return `${p.name}<br/>重要性: ${p.value.toFixed(4)}`;
      },
    },
    grid: { left: 150, right: 50, top: 10, bottom: 30 },
    xAxis: {
      type: 'value',
      name: '重要性',
      nameTextStyle: { color: '#C4C4CC', fontSize: 12 },
      axisLabel: { color: '#C4C4CC', fontSize: 11 },
    },
    yAxis: {
      type: 'category',
      data: rankings.map((r) => r.label).reverse(),
      axisLabel: { color: '#C4C4CC', fontSize: 12, width: 135, overflow: 'truncate' },
      axisLine: { lineStyle: { color: 'rgba(255,255,255,0.1)' } },
    },
    series: [
      {
        type: 'bar',
        data: rankings
          .map((r) => ({
            name: r.label,
            value: r.importance,
            itemStyle: {
              color: `hsl(${220 - (r.importance / Math.max(...rankings.map((x) => x.importance))) * 180}, 70%, 55%)`,
            },
          }))
          .reverse(),
        barMaxWidth: 24,
        label: {
          show: true,
          position: 'right',
          formatter: (p: { value: number }) => p.value.toFixed(3),
          color: '#C4C4CC',
          fontSize: 11,
        },
      },
    ],
  };

  return (
    <div>
      {/* Method selector + model info */}
      <div style={{ display: 'flex', gap: 16, marginBottom: 20, alignItems: 'flex-start', flexWrap: 'wrap' }}>
        <Card title="方法" style={{ flex: '0 0 auto' }}>
          <div style={{ display: 'flex', gap: 8 }}>
            {(['permutation', 'gain'] as const).map((m) => (
              <button
                key={m}
                onClick={() => setMethod(m)}
                style={{
                  padding: '6px 16px',
                  borderRadius: 6,
                  border: `1px solid ${method === m ? 'var(--fqp-accent)' : 'var(--fqp-border)'}`,
                  background: method === m ? 'rgba(59,130,246,0.15)' : 'transparent',
                  color: method === m ? 'var(--fqp-accent)' : 'var(--fqp-text-muted)',
                  cursor: 'pointer',
                  fontWeight: method === m ? 600 : 400,
                  fontSize: 13,
                }}
              >
                {m === 'permutation' ? '排列重要性' : '增益重要性'}
              </button>
            ))}
          </div>
        </Card>

        {modelInfo && modelInfo.status === 'ok' && (
          <Card title="模型信息" style={{ flex: 1, minWidth: 280 }}>
            <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', fontSize: 13 }}>
              <div>
                <span style={{ color: 'var(--fqp-text-muted)' }}>训练样本：</span>
                <strong>{modelInfo.n_samples ?? '—'}</strong>
              </div>
              <div>
                <span style={{ color: 'var(--fqp-text-muted)' }}>特征数：</span>
                <strong>{modelInfo.n_features ?? '—'}</strong>
              </div>
              <div>
                <span style={{ color: 'var(--fqp-text-muted)' }}>训练准确率：</span>
                <strong style={{ color: 'var(--fqp-success)' }}>
                  {modelInfo.train_accuracy !== undefined ? `${(modelInfo.train_accuracy * 100).toFixed(1)}%` : '—'}
                </strong>
              </div>
              {modelInfo.class_distribution && (
                <div>
                  <span style={{ color: 'var(--fqp-text-muted)' }}>类别分布：</span>
                  <span className="fqp-mono" style={{ fontSize: 12 }}>
                    主胜 {modelInfo.class_distribution.home_win} / 平 {modelInfo.class_distribution.draw} / 客胜 {modelInfo.class_distribution.away_win}
                  </span>
                </div>
              )}
            </div>
          </Card>
        )}
      </div>

      {/* Bar chart */}
      {loading ? (
        <div style={{ padding: 32, color: 'var(--fqp-text-muted)' }}>训练 XGBoost 模型并计算特征重要性...</div>
      ) : rankings.length === 0 ? (
        <Card title="特征重要性">
          <div className="fqp-empty-state">
            <div className="fqp-empty-icon">🧪</div>
            <div className="fqp-empty-title">暂无特征重要性数据</div>
            <div className="fqp-empty-desc">
              需要 match_feature_snapshots 表中有已结算比赛的特征快照（至少50条）
            </div>
          </div>
        </Card>
      ) : (
        <ChartCard title={`特征重要性排名（${method === 'permutation' ? '排列重要性' : '增益重要性'}）`} option={barOption} height={520} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab: SHAP 解释
// ---------------------------------------------------------------------------

function ShapExplainTab() {
  const [matchIdInput, setMatchIdInput] = useState('');
  const [matchId, setMatchId] = useState<number | null>(null);
  const [shapEntries, setShapEntries] = useState<ShapEntry[]>([]);
  const [probs, setProbs] = useState<{ home: number; draw: number; away: number } | null>(null);
  const [homeTeam, setHomeTeam] = useState('');
  const [awayTeam, setAwayTeam] = useState('');
  const [baseValues, setBaseValues] = useState<number[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchExplanation = useCallback(() => {
    const id = parseInt(matchIdInput, 10);
    if (!id || id <= 0) {
      setError('请输入有效的比赛 ID');
      return;
    }
    setLoading(true);
    setError(null);
    api.analysis.shapExplanation(id, 15)
      .then((res) => {
        if (res.status === 'ok') {
          setMatchId(id);
          setShapEntries(res.shap_values);
          setProbs(res.predicted_probs);
          setHomeTeam(res.home_team);
          setAwayTeam(res.away_team);
          setBaseValues(res.base_values);
        } else {
          setError('SHAP 解释失败');
        }
        setLoading(false);
      })
      .catch((e) => {
        setError(e instanceof ApiError ? e.message : '加载失败');
        setLoading(false);
      });
  }, [matchIdInput]);

  // Build waterfall chart
  const waterfallOption = shapEntries.length > 0
    ? {
        tooltip: {
          trigger: 'axis',
          axisPointer: { type: 'shadow' },
          formatter: (params: { name: string; value: number; marker: string }[]) => {
            const p = params[0];
            return `${p.name}<br/>SHAP: ${p.value >= 0 ? '+' : ''}${p.value.toFixed(4)}`;
          },
        },
        grid: { left: 160, right: 50, top: 10, bottom: 30 },
        xAxis: {
          type: 'value',
          name: 'SHAP 值（主胜方向）',
          nameTextStyle: { color: '#C4C4CC', fontSize: 12 },
          axisLabel: { color: '#C4C4CC', fontSize: 11 },
        },
        yAxis: {
          type: 'category',
          data: shapEntries.map((e) => e.label),
          axisLabel: { color: '#C4C4CC', fontSize: 12, width: 145, overflow: 'truncate' },
          axisLine: { lineStyle: { color: 'rgba(255,255,255,0.1)' } },
        },
        series: [
          {
            type: 'bar',
            data: shapEntries.map((e) => ({
              name: e.label,
              value: e.shap_value,
              itemStyle: {
                color: e.shap_value >= 0 ? '#22c55e' : '#ef4444',
              },
            })),
            barMaxWidth: 20,
            label: {
              show: true,
              position: 'right',
              formatter: (p: { value: number }) => `${p.value >= 0 ? '+' : ''}${p.value.toFixed(3)}`,
              color: '#C4C4CC',
              fontSize: 11,
            },
          },
        ],
      }
    : {};

  return (
    <div>
      {/* Input */}
      <Card title="比赛 SHAP 解释" style={{ marginBottom: 20 }}>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <label style={{ fontSize: 13, color: 'var(--fqp-text-muted)', whiteSpace: 'nowrap' }}>
            比赛 ID：
          </label>
          <input
            type="number"
            value={matchIdInput}
            onChange={(e) => setMatchIdInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && fetchExplanation()}
            placeholder="输入 match_id..."
            style={{
              padding: '8px 12px',
              borderRadius: 6,
              border: '1px solid var(--fqp-border)',
              background: 'var(--fqp-bg-input)',
              color: 'var(--fqp-text)',
              fontSize: 14,
              width: 180,
            }}
          />
          <button
            onClick={fetchExplanation}
            disabled={loading}
            style={{
              padding: '8px 20px',
              borderRadius: 6,
              border: 'none',
              background: 'var(--fqp-accent)',
              color: '#fff',
              cursor: 'pointer',
              fontWeight: 600,
              fontSize: 13,
            }}
          >
            {loading ? '分析中...' : '分析'}
          </button>
        </div>
        <div style={{ fontSize: 11, color: 'var(--fqp-text-muted)', marginTop: 8 }}>
          输入已结算比赛的 ID，查看每个特征对主胜预测的贡献方向和大小
        </div>
      </Card>

      {error && <ErrorState message={error} />}

      {/* Results */}
      {matchId && probs && (
        <div style={{ animation: 'fqpSlideUpBounce 0.4s ease both' }}>
          {/* Prediction card */}
          <Card title={`${homeTeam} vs ${awayTeam}`} style={{ marginBottom: 20 }}>
            <div style={{ display: 'flex', gap: 32, flexWrap: 'wrap' }}>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 12, color: 'var(--fqp-text-muted)' }}>主胜概率</div>
                <div style={{ fontSize: 24, fontWeight: 700, color: '#22c55e' }}>
                  {(probs.home * 100).toFixed(1)}%
                </div>
              </div>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 12, color: 'var(--fqp-text-muted)' }}>平局概率</div>
                <div style={{ fontSize: 24, fontWeight: 700, color: '#f59e0b' }}>
                  {(probs.draw * 100).toFixed(1)}%
                </div>
              </div>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 12, color: 'var(--fqp-text-muted)' }}>客胜概率</div>
                <div style={{ fontSize: 24, fontWeight: 700, color: '#ef4444' }}>
                  {(probs.away * 100).toFixed(1)}%
                </div>
              </div>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 12, color: 'var(--fqp-text-muted)' }}>基准值</div>
                <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--fqp-text-muted)' }}>
                  {baseValues.length === 3
                    ? `${(baseValues[2] * 100).toFixed(1)}% / ${(baseValues[1] * 100).toFixed(1)}% / ${(baseValues[0] * 100).toFixed(1)}%`
                    : '—'}
                </div>
              </div>
            </div>
          </Card>

          {/* Waterfall chart */}
          {shapEntries.length > 0 && (
            <ChartCard title="SHAP 特征贡献（主胜方向）" option={waterfallOption} height={480} />
          )}

          {/* Feature table */}
          {shapEntries.length > 0 && (
            <Card title="特征贡献明细" style={{ marginTop: 20 }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--fqp-border)' }}>
                    <th style={thS}>特征</th>
                    <th style={thS}>特征值</th>
                    <th style={thS}>SHAP 贡献</th>
                    <th style={thS}>方向</th>
                  </tr>
                </thead>
                <tbody>
                  {shapEntries.map((e) => (
                    <tr key={e.feature} style={{ borderBottom: '1px solid var(--fqp-border-light)' }}>
                      <td style={tdS}>{e.label}</td>
                      <td style={{ ...tdS, textAlign: 'right' }} className="fqp-mono">
                        {e.feature_value}
                      </td>
                      <td style={{ ...tdS, textAlign: 'right' }} className="fqp-mono">
                        <span style={{ color: e.shap_value >= 0 ? 'var(--fqp-success)' : 'var(--fqp-red-neon)' }}>
                          {e.shap_value >= 0 ? '+' : ''}{e.shap_value.toFixed(4)}
                        </span>
                      </td>
                      <td style={tdS}>
                        <span
                          style={{
                            padding: '2px 8px',
                            borderRadius: 4,
                            fontSize: 11,
                            fontWeight: 600,
                            background: e.shap_value >= 0 ? 'rgba(34,197,94,0.15)' : 'rgba(239,68,68,0.15)',
                            color: e.shap_value >= 0 ? '#22c55e' : '#ef4444',
                          }}
                        >
                          {e.shap_value >= 0 ? '↑ 推高主胜' : '↓ 压低主胜'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          )}
        </div>
      )}

      {!matchId && !error && !loading && (
        <Card>
          <div className="fqp-empty-state">
            <div className="fqp-empty-icon">💡</div>
            <div className="fqp-empty-title">输入比赛 ID 查看 SHAP 解释</div>
            <div className="fqp-empty-desc">
              XGBoost 模型会为每场比赛的每个特征计算 SHAP 值，展示各特征如何影响主胜概率
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab: 条件表现
// ---------------------------------------------------------------------------

type ConditionDim = 'league' | 'odds_range' | 'confidence';

const CONDITION_LABELS: Record<ConditionDim, string> = {
  league: '联赛',
  odds_range: '赔率区间',
  confidence: '信心度',
};

function ConditionTab() {
  const [dimension, setDimension] = useState<ConditionDim>('league');
  const [data, setData] = useState<ConditionPerformanceData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    api.analysis.conditionPerformance(dimension)
      .then((res) => {
        if (res.status === 'ok') setData(res);
        setLoading(false);
      })
      .catch((e) => {
        setError(e instanceof ApiError ? e.message : '加载失败');
        setLoading(false);
      });
  }, [dimension]);

  // Pivot: segments -> {group: {model: brier}}
  const pivotData = pivotSegments(data?.segments ?? [], dimension);

  if (error) return <ErrorState message={error} />;

  // Build heatmap-style bar chart per group
  const groups = Object.keys(pivotData);
  const modelNames = [...new Set((data?.segments ?? []).map((s) => s.model_name))];

  return (
    <div>
      {/* Dimension selector */}
      <Card title="条件表现分析" style={{ marginBottom: 20 }}>
        <div style={{ display: 'flex', gap: 8 }}>
          {(Object.entries(CONDITION_LABELS) as [ConditionDim, string][]).map(([key, label]) => (
            <button
              key={key}
              onClick={() => setDimension(key)}
              style={{
                padding: '8px 20px',
                borderRadius: 6,
                border: `1px solid ${dimension === key ? 'var(--fqp-accent)' : 'var(--fqp-border)'}`,
                background: dimension === key ? 'rgba(59,130,246,0.15)' : 'transparent',
                color: dimension === key ? 'var(--fqp-accent)' : 'var(--fqp-text-muted)',
                cursor: 'pointer',
                fontWeight: dimension === key ? 600 : 400,
                fontSize: 13,
              }}
            >
              {label}
            </button>
          ))}
        </div>
        <div style={{ fontSize: 11, color: 'var(--fqp-text-muted)', marginTop: 8 }}>
          按{CONDITION_LABELS[dimension]}分组，展示各模型在不同条件下的 Brier Score 表现
        </div>
      </Card>

      {loading ? (
        <div style={{ padding: 32, color: 'var(--fqp-text-muted)' }}>加载条件表现数据...</div>
      ) : groups.length === 0 ? (
        <Card>
          <div className="fqp-empty-state">
            <div className="fqp-empty-icon">📭</div>
            <div className="fqp-empty-title">暂无该维度的数据</div>
            <div className="fqp-empty-desc">需要更多已结算的评估数据来生成条件表现分析</div>
          </div>
        </Card>
      ) : (
        <Card title={`按${CONDITION_LABELS[dimension]}分组的 Brier Score`} style={{ padding: 0, overflow: 'hidden' }}>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, minWidth: 600 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--fqp-border)' }}>
                  <th style={thS}>{CONDITION_LABELS[dimension]}</th>
                  {modelNames.map((name) => (
                    <th key={name} style={{ ...thS, textAlign: 'right' }}>{name}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {groups.map((group) => {
                  const row = pivotData[group];
                  const scores = modelNames.map((n) => row[n]?.brier ?? null).filter((v) => v !== null) as number[];
                  const bestScore = Math.min(...scores);
                  return (
                    <tr key={group} style={{ borderBottom: '1px solid var(--fqp-border-light)' }}>
                      <td style={{ ...tdS, fontWeight: 600 }}>{group}</td>
                      {modelNames.map((name) => {
                        const cell = row[name];
                        const isBest = cell?.brier !== undefined && cell.brier === bestScore && scores.length > 1;
                        return (
                          <td
                            key={name}
                            style={{
                              ...tdS,
                              textAlign: 'right',
                              background: isBest ? 'rgba(34,197,94,0.08)' : undefined,
                            }}
                            className="fqp-mono"
                          >
                            {cell ? (
                              <>
                                <span style={{ color: isBest ? 'var(--fqp-success)' : undefined, fontWeight: isBest ? 600 : 400 }}>
                                  {cell.brier.toFixed(4)}
                                </span>
                                <span style={{ fontSize: 10, color: 'var(--fqp-text-muted)', marginLeft: 4 }}>
                                  ({cell.n})
                                </span>
                              </>
                            ) : '—'}
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}

function pivotSegments(
  segments: ConditionSegment[],
  dimension: ConditionDim,
): Record<string, Record<string, { brier: number; n: number; logloss?: number }>> {
  const result: Record<string, Record<string, { brier: number; n: number; logloss?: number }>> = {};
  for (const s of segments) {
    const groupKey =
      dimension === 'league'
        ? (s.league_name ?? '未知')
        : dimension === 'odds_range'
          ? (s.odds_range ?? '未知')
          : (s.confidence_range ?? '未知');
    if (!result[groupKey]) result[groupKey] = {};
    result[groupKey][s.model_name] = {
      brier: s.avg_brier,
      n: s.n,
      logloss: s.avg_logloss,
    };
  }
  return result;
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function AnalysisPage() {
  const [activeTab, setActiveTab] = useState<TabKey>('compare');

  return (
    <div>
      <PageHeader title="数据分析" />
      <DisclaimerBanner
        text="特征分析和模型对比仅用于学术研究。历史表现不代表未来结果。"
        type="page"
      />

      {/* Tab bar */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 24, borderBottom: '1px solid var(--fqp-border)', paddingBottom: 0 }}>
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            style={{
              padding: '10px 20px',
              border: 'none',
              borderBottom: activeTab === tab.key ? '2px solid var(--fqp-accent)' : '2px solid transparent',
              background: 'transparent',
              color: activeTab === tab.key ? 'var(--fqp-accent)' : 'var(--fqp-text-muted)',
              cursor: 'pointer',
              fontWeight: activeTab === tab.key ? 600 : 400,
              fontSize: 14,
              marginBottom: -1,
            }}
          >
            <span style={{ marginRight: 6 }}>{tab.icon}</span>
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div key={activeTab} className="fqp-anim-fadeIn">
        {activeTab === 'compare' && <ModelCompareTab />}
        {activeTab === 'importance' && <FeatureImportanceTab />}
        {activeTab === 'shap' && <ShapExplainTab />}
        {activeTab === 'condition' && <ConditionTab />}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared styles
// ---------------------------------------------------------------------------

const thS: React.CSSProperties = {
  padding: '8px 12px',
  textAlign: 'left',
  fontWeight: 600,
  fontSize: 12,
  color: 'var(--fqp-text-muted)',
  textTransform: 'uppercase',
  whiteSpace: 'nowrap',
};

const tdS: React.CSSProperties = {
  padding: '8px 12px',
  whiteSpace: 'nowrap',
};

const tdRight: React.CSSProperties = {
  ...tdS,
  textAlign: 'right',
};
