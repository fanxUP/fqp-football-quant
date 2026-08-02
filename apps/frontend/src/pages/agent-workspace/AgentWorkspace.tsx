import { useEffect, useMemo, useState } from 'react';
import { api, type AgentModelBinding } from '../../core/apiClient';
import { toast } from '../../shared/components/Toast';

type ModelReply = { agentCode: string; providerCode: string; model: string; content: string };

const taskTemplates: Record<string, { label: string; prompt: string; output: string }[]> = {
  orchestrator_agent: [
    { label: '拆解工作项', prompt: '请将以下工作拆解为可审计的执行步骤，列出依赖、风险和验收标准：\n\n', output: '执行步骤、依赖关系、风险及验收标准' },
    { label: '评估风险', prompt: '请评估以下工作项的执行风险，按高、中、低分级，并给出不涉及实际操作的缓解建议：\n\n', output: '风险分级与人工可执行的缓解建议' },
  ],
  review_agent: [
    { label: '结构化复盘', prompt: '请基于以下材料复盘，分别列出已知事实、合理假设、数据缺口和待验证项：\n\n', output: '事实、假设、数据缺口和待验证项' },
    { label: '检查证据', prompt: '请检查以下结论的证据缺口或逻辑跳跃，并列出需要补充验证的信息：\n\n', output: '证据缺口与验证清单' },
  ],
  doc_agent: [
    { label: '整理说明', prompt: '请将以下内容整理为中文说明文档，包含标题、摘要、要点和待确认事项：\n\n', output: '可直接审阅的中文说明' },
    { label: '生成摘要', prompt: '请将以下内容压缩为面向项目使用者的简明摘要，保留事实与不确定性：\n\n', output: '事实优先的简明摘要' },
  ],
};

export default function AgentWorkspace() {
  const [bindings, setBindings] = useState<AgentModelBinding[]>([]);
  const [loading, setLoading] = useState(true);
  const [agentCode, setAgentCode] = useState('');
  const [templateLabel, setTemplateLabel] = useState('');
  const [material, setMaterial] = useState('');
  const [running, setRunning] = useState(false);
  const [reply, setReply] = useState<ModelReply | null>(null);

  useEffect(() => {
    api.modelProviders.bindings()
      .then((result) => setBindings(result.bindings))
      .catch((error: Error) => toast.error(`智能工作台加载失败：${error.message}`))
      .finally(() => setLoading(false));
  }, []);

  const availableBindings = useMemo(() => bindings.filter(
    (binding) => binding.enabled && binding.providerEnabled && binding.providerTestStatus === 'passed',
  ), [bindings]);
  const selected = availableBindings.find((binding) => binding.agentCode === agentCode) ?? availableBindings[0];
  const templates = selected ? taskTemplates[selected.agentCode] ?? [] : [];
  const selectedTemplate = templates.find((template) => template.label === templateLabel) ?? templates[0];

  const chooseTemplate = (label: string) => {
    const template = templates.find((item) => item.label === label);
    if (!template) return;
    setTemplateLabel(template.label);
    setMaterial('');
  };

  const run = async () => {
    if (!selected || !selectedTemplate) {
      toast.error('请先在模型接入中启用并测试一个智能代理');
      return;
    }
    const materialText = material.trim();
    if (!materialText) {
      toast.error('请补充需要分析的材料');
      return;
    }
    setRunning(true);
    setReply(null);
    try {
      setReply(await api.modelProviders.invokeBinding(selected.agentCode, `${selectedTemplate.prompt}${materialText}`));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '模型任务执行失败');
    } finally {
      setRunning(false);
    }
  };

  if (loading) return <section className="agent-workspace" aria-busy="true"><p>正在加载可用的智能代理…</p></section>;

  return <section className="agent-workspace" aria-labelledby="agent-workspace-title">
    <div className="agent-workspace-heading">
      <div><span className="appearance-eyebrow">V2 · 人工任务工作流</span><h2 id="agent-workspace-title">新建分析任务</h2></div>
      <span className="agent-workspace-safety">不自动执行 · 不写入业务数据</span>
    </div>
    {availableBindings.length === 0 ? <div className="agent-workspace-empty" role="status">
      <strong>暂无可用模型</strong><p>请先在“模型接入”中保存服务商、完成连通性测试，并为至少一个 Agent 开启调用。</p>
    </div> : <div className="agent-workspace-grid">
      <div className="agent-workspace-form">
        <label className="fqp-label" htmlFor="workspace-agent">任务职责</label>
        <select id="workspace-agent" className="fqp-input" value={selected?.agentCode ?? ''}
          onChange={(event) => { setAgentCode(event.target.value); setTemplateLabel(''); setMaterial(''); setReply(null); }}>
          {availableBindings.map((binding) => <option key={binding.agentCode} value={binding.agentCode}>
            {binding.agentName} · {binding.providerName} · {binding.model}
          </option>)}
        </select>
        <div className="agent-workspace-template-list" aria-label="任务模板">
          {templates.map((template) => <button type="button" key={template.label}
            className="agent-workspace-template" data-selected={(selectedTemplate?.label === template.label) || undefined}
            onClick={() => chooseTemplate(template.label)}>{template.label}</button>)}
        </div>
        <label className="fqp-label" htmlFor="workspace-material">任务材料</label>
        <textarea id="workspace-material" className="fqp-input agent-workspace-input" maxLength={8000}
          value={material} onChange={(event) => setMaterial(event.target.value)}
          placeholder="选择任务模板后，粘贴需要分析的事实、数据摘要或草稿。" />
        <div className="agent-workspace-actions"><span>{material.length}/8000</span><button type="button" className="fqp-btn fqp-btn-primary" disabled={running} onClick={() => void run()}>{running ? '分析中…' : '运行分析'}</button></div>
      </div>
      <aside className="agent-workspace-brief" aria-label="任务边界">
        <h3>本次任务</h3>
        <dl><div><dt>调用对象</dt><dd>{selected?.agentName}</dd></div><div><dt>预期产出</dt><dd>{selectedTemplate?.output}</dd></div><div><dt>处理方式</dt><dd>仅在你点击后调用一次模型</dd></div></dl>
        <p>模型输出可能出错。请人工核验后，再自行使用其中的结论。</p>
      </aside>
    </div>}
    {reply && <div className="agent-workspace-result" role="status" aria-live="polite">
      <div><strong>分析结果</strong><span>{reply.providerCode} · {reply.model} · 非可信内容</span></div><pre>{reply.content}</pre>
      <p>本结果未保存，关闭或刷新页面后会清除。</p>
    </div>}
  </section>;
}
