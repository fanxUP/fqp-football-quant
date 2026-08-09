import { useEffect, useState } from 'react';
import { api } from '../core/apiClient';
import type { PredictionModelRuntimeState } from '../core/types';

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

  const load = () => {
    setLoading(true);
    setError(false);
    api.modelOverview().then((result) => setStates(result.models)).catch(() => setError(true)).finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);
  const stateByCode = new Map(states.map((state) => [state.code, state]));

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
          </article>;
        })}
      </div>
      <div className="prediction-model-flow" aria-label="预测到推荐的流程">官方赔率与历史赛果 <b>→</b> 四模型预测 <b>→</b> 共识、分歧与风控 <b>→</b> 推荐候选</div>
    </section>
  );
}
