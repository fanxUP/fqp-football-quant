import { useState } from 'react';
import { api, type AgentModelBinding } from '../../core/apiClient';
import { toast } from '../../shared/components/Toast';

type ModelReply = {
  agentCode: string;
  providerCode: string;
  model: string;
  content: string;
};

const promptTemplates: Record<string, { label: string; prompt: string }[]> = {
  orchestrator_agent: [
    { label: '拆解任务', prompt: '请将以下任务拆解为可审计的执行步骤，列出依赖、风险与验收标准：\n\n' },
    { label: '梳理风险', prompt: '请评估以下工作项的执行风险，按高、中、低分级，并给出不涉及实际操作的缓解建议：\n\n' },
  ],
  review_agent: [
    { label: '结构化复盘', prompt: '请基于以下材料进行复盘，分别列出已知事实、合理假设、数据缺口和待验证项：\n\n' },
    { label: '检查缺口', prompt: '请检查以下结论是否有证据缺口或逻辑跳跃，并给出需要补充验证的信息：\n\n' },
  ],
  doc_agent: [
    { label: '整理说明', prompt: '请将以下内容整理为中文说明文档，包含标题、摘要、要点和待确认事项：\n\n' },
    { label: '生成摘要', prompt: '请将以下内容压缩为面向项目使用者的简明摘要，保留事实与不确定性：\n\n' },
  ],
};

export default function AgentModelTrial({ bindings, onCompleted }: { bindings: AgentModelBinding[]; onCompleted: () => void }) {
  const availableBindings = bindings.filter((binding) => binding.enabled && binding.providerEnabled);
  const [agentCode, setAgentCode] = useState('');
  const [prompt, setPrompt] = useState('');
  const [running, setRunning] = useState(false);
  const [reply, setReply] = useState<ModelReply | null>(null);

  const selected = availableBindings.find((binding) => binding.agentCode === agentCode) ?? availableBindings[0];
  const templates = selected ? promptTemplates[selected.agentCode] ?? [] : [];

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
      onCompleted();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '模型试运行失败');
      onCompleted();
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
      <div className="agent-model-template-group" aria-label="快捷任务模板">
        <span>快捷模板</span>
        <div className="agent-model-template-list">
          {templates.map((template) => <button key={template.label} type="button" className="agent-model-template"
            onClick={() => setPrompt(template.prompt)}>{template.label}</button>)}
        </div>
      </div>
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
