import { useEffect, useMemo, useState } from 'react';
import { api, type AgentModelBinding, type AgentWorkspaceTask } from '../../core/apiClient';
import { toast } from '../../shared/components/Toast';
import AgentWorkspaceArchive from './AgentWorkspaceArchive';

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
  const [taskTitle, setTaskTitle] = useState('');
  const [material, setMaterial] = useState('');
  const [running, setRunning] = useState(false);
  const [tasks, setTasks] = useState<AgentWorkspaceTask[]>([]);
  const [busyTaskId, setBusyTaskId] = useState<number | null>(null);

  useEffect(() => {
    Promise.all([api.modelProviders.bindings(), api.agentWorkspace.list()])
      .then(([bindingResult, taskResult]) => { setBindings(bindingResult.bindings); setTasks(taskResult.tasks); })
      .catch((error: Error) => toast.error(`智能工作台加载失败：${error.message}`))
      .finally(() => setLoading(false));
  }, []);

  const availableBindings = useMemo(() => bindings.filter(
    (binding) => binding.enabled && binding.providerEnabled && binding.providerTestStatus === 'passed',
  ), [bindings]);
  const selected = availableBindings.find((binding) => binding.agentCode === agentCode) ?? availableBindings[0];
  const templates = selected ? taskTemplates[selected.agentCode] ?? [] : [];
  const selectedTemplate = templates.find((template) => template.label === templateLabel) ?? templates[0];
  const taskStats = useMemo(() => ({
    total: tasks.length,
    pending: tasks.filter((task) => !task.reviewedAt).length,
    reviewed: tasks.filter((task) => Boolean(task.reviewedAt)).length,
  }), [tasks]);

  const chooseTemplate = (label: string) => {
    const template = templates.find((item) => item.label === label);
    if (!template) return;
    setTemplateLabel(template.label);
    setTaskTitle(template.label);
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
    try {
      const result = await api.agentWorkspace.create({
        agentCode: selected.agentCode,
        title: taskTitle.trim() || selectedTemplate.label,
        prompt: `${selectedTemplate.prompt}${materialText}`,
      });
      setTasks((current) => [result.task, ...current]);
      setMaterial('');
      setTaskTitle('');
      toast.success('分析已归档，等待人工核验');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '模型任务执行失败');
    } finally {
      setRunning(false);
    }
  };

  const setReviewed = async (task: AgentWorkspaceTask) => {
    setBusyTaskId(task.id);
    try {
      const result = await api.agentWorkspace.setReviewed(task.id, !task.reviewedAt);
      setTasks((current) => current.map((item) => item.id === task.id ? result.task : item));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '更新确认状态失败');
    } finally { setBusyTaskId(null); }
  };

  const removeTask = async (task: AgentWorkspaceTask) => {
    if (!window.confirm(`确认删除“${task.title}”的归档任务吗？此操作无法恢复。`)) return;
    setBusyTaskId(task.id);
    try {
      await api.agentWorkspace.remove(task.id);
      setTasks((current) => current.filter((item) => item.id !== task.id));
      toast.success('归档任务已删除');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '删除归档任务失败');
    } finally { setBusyTaskId(null); }
  };

  if (loading) return <section className="agent-workspace" aria-busy="true"><p>正在加载可用的智能代理…</p></section>;

  return <section className="agent-workspace" aria-labelledby="agent-workspace-title">
    <div className="agent-workspace-heading">
      <div><span className="appearance-eyebrow">V2 · 人工任务工作流</span><h2 id="agent-workspace-title">新建分析任务</h2></div>
      <span className="agent-workspace-safety">不自动执行 · 不写入业务数据</span>
    </div>
    <div className="agent-workspace-stats" aria-label="归档任务概览">
      <span><b>{taskStats.total}</b>归档任务</span><span><b>{taskStats.pending}</b>待人工确认</span><span><b>{taskStats.reviewed}</b>已人工确认</span>
    </div>
    {availableBindings.length === 0 ? <div className="agent-workspace-empty" role="status">
      <strong>暂无可用模型</strong><p>请先在“模型接入”中保存服务商、完成连通性测试，并为至少一个 Agent 开启调用。</p>
    </div> : <div className="agent-workspace-grid">
      <div className="agent-workspace-form">
        <label className="fqp-label" htmlFor="workspace-agent">任务职责</label>
        <select id="workspace-agent" className="fqp-input" value={selected?.agentCode ?? ''}
          onChange={(event) => { setAgentCode(event.target.value); setTemplateLabel(''); setTaskTitle(''); setMaterial(''); }}>
          {availableBindings.map((binding) => <option key={binding.agentCode} value={binding.agentCode}>
            {binding.agentName} · {binding.providerName} · {binding.model}
          </option>)}
        </select>
        <div className="agent-workspace-template-list" aria-label="任务模板">
          {templates.map((template) => <button type="button" key={template.label}
            className="agent-workspace-template" data-selected={(selectedTemplate?.label === template.label) || undefined}
            onClick={() => chooseTemplate(template.label)}>{template.label}</button>)}
        </div>
        <label className="fqp-label" htmlFor="workspace-title">归档标题</label>
        <input id="workspace-title" className="fqp-input" maxLength={120} value={taskTitle}
          onChange={(event) => setTaskTitle(event.target.value)} placeholder={`默认：${selectedTemplate?.label ?? '任务名称'}`} />
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
    <AgentWorkspaceArchive tasks={tasks} busyTaskId={busyTaskId} onSetReviewed={(task) => void setReviewed(task)} onRemove={(task) => void removeTask(task)} />
  </section>;
}
