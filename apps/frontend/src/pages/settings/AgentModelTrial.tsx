import { useState } from 'react';
import { api, type AgentModelBinding } from '../../core/apiClient';
import { toast } from '../../shared/components/Toast';

type ModelReply = {
  agentCode: string;
  providerCode: string;
  model: string;
  content: string;
};

export default function AgentModelTrial({ bindings }: { bindings: AgentModelBinding[] }) {
  const availableBindings = bindings.filter((binding) => binding.enabled && binding.providerEnabled);
  const [agentCode, setAgentCode] = useState('');
  const [prompt, setPrompt] = useState('');
  const [running, setRunning] = useState(false);
  const [reply, setReply] = useState<ModelReply | null>(null);

  const selected = availableBindings.find((binding) => binding.agentCode === agentCode) ?? availableBindings[0];

  const run = async () => {
    if (!selected) {
      toast.error('请先启用并测试一个智能代理模型');
      return;
    }
    if (!prompt.trim()) {
      toast.error('请输入试运行内容');
      return;
    }
    setRunning(true);
    setReply(null);
    try {
      const result = await api.modelProviders.invokeBinding(selected.agentCode, prompt.trim());
      setReply(result);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '模型试运行失败');
    } finally {
      setRunning(false);
    }
  };

  return <section className="agent-model-trial" aria-labelledby="agent-model-trial-title">
    <div>
      <h4 id="agent-model-trial-title">手动试运行</h4>
      <p>仅在你点击后发起一次模型调用，可能产生服务商费用；结果仅供查看，不会写入比赛、推荐、风控或彩票数据。</p>
    </div>
    {availableBindings.length === 0 ? <p className="agent-model-trial-empty" role="status">暂无可试运行的 Agent。请先保存服务商、测试连接，并启用对应 Agent。</p> : <>
      <label className="fqp-label" htmlFor="agent-model-trial-agent">调用 Agent</label>
      <select id="agent-model-trial-agent" className="fqp-input" value={selected?.agentCode ?? ''}
        onChange={(event) => setAgentCode(event.target.value)}>
        {availableBindings.map((binding) => <option value={binding.agentCode} key={binding.agentCode}>
          {binding.agentName} · {binding.providerName} · {binding.model}
        </option>)}
      </select>
      <label className="fqp-label" htmlFor="agent-model-trial-prompt">试运行内容</label>
      <textarea id="agent-model-trial-prompt" className="fqp-input agent-model-trial-input" maxLength={8000}
        value={prompt} onChange={(event) => setPrompt(event.target.value)}
        placeholder="例如：用三条要点总结本周数据质量检查需要关注的项目。" />
      <div className="agent-model-trial-actions">
        <span>{prompt.length}/8000</span>
        <button type="button" className="fqp-btn fqp-btn-primary" disabled={running} onClick={() => void run()}>
          {running ? '调用中…' : '开始试运行'}
        </button>
      </div>
    </>}
    {reply && <div className="agent-model-reply" role="status" aria-live="polite">
      <div><strong>模型输出</strong><span>{reply.providerCode} · {reply.model} · 非可信内容</span></div>
      <pre>{reply.content}</pre>
    </div>}
  </section>;
}
