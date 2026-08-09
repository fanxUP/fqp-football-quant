import { useEffect, useState } from 'react';
import { api } from '../core/apiClient';
import type { CalibrationProfile, CalibrationTrend, PredictionModelRuntimeState } from '../core/types';

type ModelDefinition = {
  code: string;
  title: string;
  summary: string;
  output: string;
  cadence: string;
  condition: string;
  role: string;
};

const MODEL_DEFINITIONS: ModelDefinition[] = [
  { code: 'market_baseline', title: '市场赔率基准', summary: '把体彩官方赔率换算为市场隐含胜平负概率。', output: '胜平负，以及由市场赔率推导的更多玩法概率。', cadence: '随官方赔率快照更新。', condition: '需要完整、在售的官方赔率。', role: '市场参照，用于衡量其他模型是否提供额外信息，不是独立信号。' },
  { code: 'elo_rating', title: 'Elo 实力评分', summary: '根据已结算赛果持续更新球队长期实力评分，并计入主场因素。', output: '胜平负概率。', cadence: '每日按新结算的官方赛果更新。', condition: '双方球队各至少需要 5 场有效历史。', role: '长期实力信号，避免单场结果过度影响判断。' },
  { code: 'maher_poisson', title: '马赫泊松进球模型', summary: '拟合球队进攻、防守、联赛平均进球与主场优势，估算双方预期进球。', output: '胜平负、比分、总进球数、半全场概率。', cadence: '每周用已结算官方赛果重新训练。', condition: '双方均需有足够历史样本与赛前特征。', role: '比分分布的基础模型，可解释预期进球来源。' },
  { code: 'dixon_coles', title: '迪克森-科尔斯比分模型', summary: '在泊松比分矩阵上修正低比分与平局附近的相关性。', output: '胜平负、比分、总进球数、半全场概率。', cadence: '随马赫泊松训练结果同步更新。', condition: '依赖有效的预期进球与历史低比分样本。', role: '专门校正 0–0、1–0、0–1、1–1 等低比分概率。' },
  { code: 'glicko2_rating', title: 'Glicko-2 强度评级', summary: '在球队评分外记录评分偏差和波动率，识别新赛季与样本不足的实力不确定性。', output: '带不确定性收缩的胜平负概率。', cadence: '每日按新结算的官方赛果更新。', condition: '双方各至少 8 场历史，且评分偏差处于稳定区间。', role: '当前处于影子验证，不参与推荐委员会，达到评估门槛后再单独启用。' },
  { code: 'bivariate_poisson', title: '双变量泊松进球模型', summary: '在双方预期进球上加入经历史赛果拟合的共享进球成分，刻画比分的相关性。', output: '带比分相关性的胜平负概率。', cadence: '每周随历史赛果重新拟合。', condition: '依赖已收敛的马赫泊松参数与足够历史赛果。', role: '当前处于影子验证，只记录评估结果，不参与推荐委员会。' },
  { code: 'xgboost_shadow', title: 'XGBoost 赛前特征模型', summary: '学习赛前阵容、休息、伤停、天气、战意和数据完整度等结构化特征的非线性关系。', output: '胜平负概率。', cadence: '每日在官方结算后重新训练。', condition: '至少 100 场训练样本和 25 场后续留出验证样本。', role: '当前处于影子验证，只记录独立留出评估，不参与推荐委员会、投注或风控。' },
  { code: 'logistic_shadow', title: '逻辑回归赛前特征模型', summary: '将赛前阵容、休息、伤停、天气和战意等特征作正则化线性组合，作为可解释基准。', output: '胜平负概率。', cadence: '每日在官方结算后重新训练。', condition: '至少 100 场训练样本和 25 场后续留出验证样本。', role: '当前处于影子验证，只用于和非线性模型交叉评估，不参与推荐委员会、投注或风控。' },
  { code: 'bayesian_form', title: '贝叶斯近期状态模型', summary: '对双方最近已结算赛果作贝叶斯收缩，保留主客方向并避免少量样本导致极端概率。', output: '胜平负概率。', cadence: '每次赛前预测时读取截至开赛前的官方已结算赛果。', condition: '双方各至少 6 场有效历史，最多采用最近 12 场。', role: '当前处于影子验证，只用于交叉评估，不参与推荐委员会、投注或风控。' },
  { code: 'random_forest_shadow', title: '随机森林赛前特征模型', summary: '通过多棵决策树学习赛前阵容、休息、伤停、天气与战意的非线性交互。', output: '胜平负概率。', cadence: '每日在官方结算后重新训练。', condition: '至少 100 场训练样本和 25 场后续留出验证样本。', role: '当前处于影子验证，只用于与线性、梯度提升模型交叉评估，不参与推荐委员会、投注或风控。' },
  { code: 'naive_bayes_shadow', title: '朴素贝叶斯赛前特征模型', summary: '以各赛前特征的类别条件分布形成轻量概率基准，用于发现复杂模型的过拟合偏差。', output: '胜平负概率。', cadence: '每日在官方结算后重新训练。', condition: '至少 100 场训练样本和 25 场后续留出验证样本。', role: '当前处于影子验证，只用于交叉评估，不参与推荐委员会、投注或风控。' },
  { code: 'svm_shadow', title: '支持向量机赛前特征模型', summary: '以 RBF 非线性边界识别赛前特征组合中的局部模式，并通过概率校准输出胜平负。', output: '胜平负概率。', cadence: '每日在官方结算后重新训练。', condition: '至少 100 场训练样本和 25 场后续留出验证样本。', role: '当前处于影子验证，只用于交叉评估，不参与推荐委员会、投注或风控。' },
];

function formatTime(value: string | null) {
  return value ? value.replace('T', ' ').slice(0, 16) : '暂无有效预测';
}

function RuntimeStatus({ state }: { state?: PredictionModelRuntimeState }) {
  if (!state) return <span className="prediction-model-status" data-status="disabled">未配置</span>;
  return <span className="prediction-model-status" data-status={state.isActive ? 'enabled' : 'disabled'}>{state.isActive ? '已启用' : '未启用'}</span>;
}

export default function PredictionModelOverviewPanel() {
  const [states, setStates] = useState<PredictionModelRuntimeState[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [calibrationProfiles, setCalibrationProfiles] = useState<CalibrationProfile[]>([]);
  const [calibrationTrends, setCalibrationTrends] = useState<CalibrationTrend[]>([]);

  const load = () => {
    setLoading(true);
    setError(false);
    api.calibrationProfiles()
      .then((profiles) => {
        setCalibrationProfiles(profiles.profiles);
        setCalibrationTrends(profiles.trends);
      })
      .catch(() => {
        setCalibrationProfiles([]);
        setCalibrationTrends([]);
      });
    api.modelOverview()
      .then((overview) => setStates(overview.models))
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);
  const stateByCode = new Map(states.map((state) => [state.code, state]));
  const calibrationTrendByCode = new Map(calibrationTrends.map((trend) => [trend.modelCode, trend]));

  return (
    <section className="prediction-model-overview" aria-labelledby="prediction-model-overview-title">
      <div className="prediction-model-overview-heading">
        <div>
          <span className="appearance-eyebrow">预测体系</span>
          <h2 id="prediction-model-overview-title">预测模型说明</h2>
          <p>模型只提供概率信号；单一模型不会直接生成投注推荐。</p>
        </div>
        {error && <button type="button" className="fqp-btn fqp-btn-secondary" onClick={load}>重试状态加载</button>}
      </div>
      {error && <p className="prediction-model-runtime-message" role="status">运行状态暂时无法加载，以下模型说明仍可查看。</p>}
      {!loading && calibrationProfiles.length > 0 && <section className="prediction-calibration-monitor" aria-labelledby="prediction-calibration-monitor-title">
        <div>
          <h3 id="prediction-calibration-monitor-title">概率校准监测</h3>
          <p>仅用于影子评估；单次结果达到门槛仅表示具备人工评审基础，还须至少两期样本可比的校准记录，并且不会自动影响预测、推荐或风控。</p>
        </div>
        <div className="prediction-calibration-history" role="list">
          {calibrationProfiles.map((profile) => <div className="prediction-calibration-history-row" role="listitem" key={`${profile.modelCode}-${profile.version}`}>
            <strong>{MODEL_DEFINITIONS.find((model) => model.code === profile.modelCode)?.title ?? profile.modelCode}</strong>
            <span>验证 {profile.sampleCount} 场</span>
            <span>{profile.logLossBefore.toFixed(3)} → {profile.logLossAfter.toFixed(3)}</span>
            {calibrationTrendByCode.get(profile.modelCode) && <span className="prediction-calibration-trend" data-status={calibrationTrendByCode.get(profile.modelCode)?.status}>{calibrationTrendByCode.get(profile.modelCode)?.label}</span>}
            {calibrationTrendByCode.get(profile.modelCode) && <span className="prediction-calibration-comparison" data-status={calibrationTrendByCode.get(profile.modelCode)?.comparison.status}>{calibrationTrendByCode.get(profile.modelCode)?.comparison.label}</span>}
            <span className="prediction-calibration-review" data-status={profile.review.status}>{profile.review.label}</span>
          </div>)}
        </div>
      </section>}
      <div className="prediction-model-card-grid" aria-busy={loading}>
        {MODEL_DEFINITIONS.map((model) => {
          const state = stateByCode.get(model.code);
          return <article className="prediction-model-card" key={model.code}>
            <div className="prediction-model-card-heading">
              <h3>{model.title}</h3>
              {loading ? <span className="prediction-model-status">加载中</span> : <RuntimeStatus state={state} />}
            </div>
            <p>{model.summary}</p>
            <dl>
              <div><dt>产出范围</dt><dd>{model.output}</dd></div>
              <div><dt>更新频率</dt><dd>{model.cadence}</dd></div>
              <div><dt>出数条件</dt><dd>{model.condition}</dd></div>
              <div><dt>推荐角色</dt><dd>{model.role}</dd></div>
            </dl>
            {!loading && state && <div className="prediction-model-runtime">
              <span>版本 {state.version ?? '—'}</span><span>{state.validPredictionMatchCount} 场有效预测</span><span>最近：{formatTime(state.latestPredictionAt)}</span>
            </div>}
            {!loading && state?.calibration && <div className="prediction-model-calibration" role="status">
              <strong>概率校准：影子验证</strong>
              <span>验证样本 {state.calibration.sampleCount} 场</span>
              <span>温度 {state.calibration.temperature.toFixed(2)}</span>
              <span>对数损失 {state.calibration.logLossBefore.toFixed(3)} → {state.calibration.logLossAfter.toFixed(3)}</span>
            </div>}
          </article>;
        })}
      </div>
      <div className="prediction-model-flow" aria-label="预测到推荐的流程">官方赔率与历史赛果 <b>→</b> 多模型预测 <b>→</b> 共识、分歧与风控 <b>→</b> 推荐候选</div>
    </section>
  );
}
