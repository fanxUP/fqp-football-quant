import { lazy, Suspense, useEffect, useState } from 'react';
import { api, type AgentModelBinding } from '../../core/apiClient';
import { agentLabel } from '../../shared/constants';
import { executionState, observationFresh, parseDetail, parseOverview, referenceRows, type Execution, type ExecutionOverview, type References } from './execution';
import { formatTime } from './presentation';
import SceneViewport from './SceneViewport';
import useReadOnlyResource from './useReadOnlyResource';
const OperationScene = lazy(() => import('./OperationScene'));
function ReferenceTable({ refs }: { refs: References }) {
  const rows = referenceRows(refs);
  return rows.length ? <dl className="cc-reference-list">{rows.map(row => <div key={row.key}><dt>{row.key}</dt><dd>{row.value}</dd></div>)}</dl> : <p className="cc-empty">没有可公开展示的结构化引用</p>;
}
function ExecutionEvidence({ job, historical }: { job: Execution; historical: boolean }) {
  return historical ? <aside className="cc-panel cc-evidence" aria-label="执行详情"><h3>历史列表记录 #{job.id}</h3><p>状态：{job.status}</p><p>开始 {formatTime(job.started_at)} · 结束 {formatTime(job.finished_at)}</p><p className="cc-muted">冻结列表没有归档输入、输出引用。返回实时观测可读取当前存储详情；不将后续读取冒充历史快照。</p></aside> : <CurrentEvidence key={job.id} job={job} />;
}
function CurrentEvidence({ job }: { job: Execution }) {
  const detail = useReadOnlyResource(async () => parseDetail(await api.executions.detail(job.id), job.id), 15_000);
  const data = detail.data;
  const dependencies = data?.input_refs.dependencies;
  return <aside className="cc-panel cc-evidence" aria-label="执行详情">
    <div className="cc-panel-heading"><span className="cc-eyebrow">EXECUTION EVIDENCE</span><span>#{job.id}</span></div><h3>{job.job_name}</h3><p className="cc-muted">{job.job_code} · {agentLabel(job.owner_agent)}</p>
    <button type="button" className="cc-operation-button" onClick={() => void detail.refresh()}>刷新详情</button>
    {detail.error && <p role="status">{detail.error}{data && ' · 保留上次成功数据'}</p>}{detail.loading && <p role="status">加载执行详情…</p>}
    {data && <><p>记录状态：{data.status} · 重试 {data.retry_count}</p><p className="cc-muted">开始 {formatTime(data.started_at)}<br />结束 {formatTime(data.finished_at)}<br />耗时 {data.duration_ms === null ? '未记录' : `${data.duration_ms} ms`}<br />查询时间 {formatTime(data.observed_at)}</p>
      {data.has_error && <p className="cc-error">执行记录含错误；原始日志仅供服务器审查</p>}
      <h4>作业代码依赖</h4>{Array.isArray(dependencies) && dependencies.length ? <div className="cc-dependency-chain">{dependencies.map(code => <span key={code}>{code}<span aria-hidden="true"> → </span>{data.job_code}</span>)}</div> : <p className="cc-empty">没有记录作业依赖</p>}
      <p className="cc-muted">代码依赖声明，不代表关联到某次上游执行。没有产物消费证据，不播放传输动画。</p>
      <h4>输入引用 / 计数</h4><ReferenceTable refs={data.input_refs} /><h4>输出引用 / 计数</h4><ReferenceTable refs={data.output_refs} />
      <p className="cc-muted">{data.trace_gap}</p><p className="cc-muted">模型版本、快照或批次未记录时保留缺口，不使用当前版本补齐。</p>
    </>}
    <a className="cc-detail-link" href="#/feature-snapshots">查看特征快照</a><a className="cc-detail-link" href="#/models">进入模型中心</a>
  </aside>;
}
export default function ExecutionCenter() {
  const [historical, setHistorical] = useState<{ data: ExecutionOverview; receivedAt: number | null; bindings: AgentModelBinding[] | null } | null>(null);
  const resource = useReadOnlyResource(async () => parseOverview(await api.executions.overview()), 30_000, !historical);
  const bindings = useReadOnlyResource(async () => {
    const response = await api.modelProviders.bindings();
    if (!Array.isArray(response.bindings)) throw new Error('模型绑定格式异常');
    return response.bindings;
  }, 60_000, !historical);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [owner, setOwner] = useState('');
  const [filter, setFilter] = useState('');
  const [now, setNow] = useState(Date.now);
  useEffect(() => { const timer = window.setInterval(() => { if (document.visibilityState !== 'hidden') setNow(Date.now()); }, 5_000); return () => clearInterval(timer); }, []);
  const data = historical?.data ?? resource.data;
  const fresh = !historical && observationFresh(resource.receivedAt, resource.data?.observed_at, resource.error, now);
  const jobs = (data?.jobs ?? []).filter(job => (!owner || job.owner_agent === owner) && `${job.job_code} ${job.job_name} ${job.id}`.toLowerCase().includes(filter.toLowerCase()));
  const selected = jobs.find(job => job.id === selectedId) ?? jobs[0];
  const select = (id: number) => { setOwner(''); setFilter(''); setSelectedId(id); };
  const index = selected ? jobs.findIndex(job => job.id === selected.id) : -1;
  return <section className="cc-execution-center" aria-label="Agent 与任务管线">
    <div className="cc-operation-header cc-panel"><div><span className="cc-eyebrow">AGENT OPERATIONS</span><h3>Agent 与任务管线</h3><p className="cc-muted">注册对象、定时作业、协作任务分别展示。LLM 分析归档在工作空间查看，归档不代表当前任务运行。</p></div>
      <div className="cc-camera-toolbar"><button type="button" disabled={!resource.data && !historical} onClick={() => { if (historical) setHistorical(null); else if (resource.data) setHistorical({ data: resource.data, receivedAt: resource.receivedAt, bindings: bindings.data }); }}>{historical ? '返回实时观测' : '冻结为历史列表'}</button><button type="button" disabled={!!historical} onClick={() => void resource.refresh()}>刷新概览</button></div>
      <p className="cc-muted" role="status">{historical ? `历史列表 · 冻结于 ${formatTime(historical.data.observed_at)}；逐条查看已存记录，不重建历史运行态` : resource.error ? `${resource.error}${data ? ' · 保留上次成功数据，观测过期' : ''}` : resource.loading ? '加载执行概览…' : fresh ? `最近观测 ${formatTime(data?.observed_at)}` : '观测过期；运行状态未经新鲜观测确认'}</p>
    </div>
    <div className="cc-workbench">
      <div className="cc-panel"><h3>执行记录</h3><p className="cc-muted">最近最多 {data?.limit ?? '—'} 条作业；不是完整历史或全部运行任务</p>
        <label className="cc-label">责任 Agent<select className="fqp-select" value={owner} onChange={event => setOwner(event.target.value)}><option value="">全部责任对象</option>{Array.from(new Set([...(data?.agents.map(agent => agent.agent_name) ?? []), ...(data?.jobs.map(job => job.owner_agent) ?? [])])).map(name => <option key={name} value={name}>{agentLabel(name)}</option>)}</select></label>
        <label className="cc-label">查找执行<input type="search" value={filter} onChange={event => setFilter(event.target.value)} placeholder="任务名称、代码或 ID" /></label>
        <div className="cc-match-scroll">{jobs.map(job => { const state = executionState(job, fresh, data!.scheduler, now); return <button type="button" key={job.id} className="cc-match" aria-pressed={job.id === selected?.id} onClick={() => setSelectedId(job.id)}><strong>#{job.id} {job.job_name}</strong><span className={`cc-execution-state is-${state.tone}`}>{historical ? `历史记录 · ${job.status}` : state.label}</span><span className="cc-match-meta">{job.owner_agent} · {formatTime(job.started_at)}</span></button>; })}{data && !jobs.length && <p className="cc-empty">没有符合条件的执行记录</p>}</div>
        {historical && <div className="cc-camera-toolbar" aria-label="历史记录步进"><button type="button" disabled={index <= 0} onClick={() => setSelectedId(jobs[index - 1].id)}>上一条</button><button type="button" disabled={index < 0 || index >= jobs.length - 1} onClick={() => setSelectedId(jobs[index + 1].id)}>下一条</button><span>{index + 1} / {jobs.length}</span></div>}
      </div>
      <div className="cc-panel cc-stage"><div className="cc-panel-heading"><span className="cc-eyebrow">REGISTRY NETWORK</span><span>{historical ? '历史列表' : '数据库记录观测'}</span></div><h3>Agent 状态网络</h3>
        <SceneViewport subject="任务与引用" fallback={<p>注册对象与执行归属可在下方及左侧查看</p>}>{(active, onFailure) => data ? <Suspense fallback={<p role="status">加载 Agent 场景…</p>}><OperationScene overview={data} selectedId={selected?.id ?? null} fresh={fresh} now={historical ? Date.parse(historical.data.observed_at) : now} onSelect={select} onAgentSelect={setOwner} {...{ active, onFailure }} /></Suspense> : <p className="cc-empty">等待真实注册与执行数据</p>}</SceneViewport>
        <p className="cc-scene-caption">球形＝注册 Agent，柱形＝执行记录；最多各 24 个。连线仅表示记录中的责任归属，不是数据传输。颜色高亮不代表作业心跳。</p>
        <div className="cc-agent-registry" aria-label="已注册 Agent">{data?.agents.map(agent => <button type="button" key={agent.id} className="cc-operation-button" aria-pressed={owner === agent.agent_name} onClick={() => setOwner(owner === agent.agent_name ? '' : agent.agent_name)}>{agentLabel(agent.agent_name)}<small>{agent.agent_type} · 注册 #{agent.id}</small></button>)}</div>{data && !data.agents.length && <p className="cc-empty">没有注册 Agent</p>}
        <a className="cc-detail-link" href="#/agents">Agent 任务管理</a><a className="cc-detail-link" href="#/agent-workspace">LLM 分析与归档</a>
      </div>
      {selected ? <ExecutionEvidence key={`${selected.id}-${historical ? 'history' : 'live'}`} job={selected} historical={!!historical} /> : <aside className="cc-panel cc-evidence"><h3>执行详情</h3><p className="cc-empty">选择真实执行记录后查看输入、输出证据</p></aside>}
    </div>
    <section className="cc-panel cc-llm-bindings" aria-label="LLM 角色配置"><h3>LLM 角色与模型绑定</h3><p className="cc-muted">Pi 当前配置，不是某次执行的模型版本或运行状态。LLM 分析归档独立于定时作业。</p>{bindings.error && !historical && <p role="status">模型绑定读取失败；保留上次配置</p>}<div className="cc-human-tasks">{(historical ? historical.bindings : bindings.data)?.map(binding => <article key={binding.agentCode}><strong>{binding.agentName}</strong><p>{binding.providerName || '未绑定供应商'} · {binding.model || '未绑定模型'}</p><p>{binding.enabled && binding.providerEnabled ? '配置已启用' : '配置未启用'} · 更新 {formatTime(binding.updatedAt)}</p></article>)}</div><a className="cc-detail-link" href="#/model-providers">管理模型接入</a></section>
    <section className="cc-panel" aria-label="协作任务记录"><h3>协作任务记录</h3><p className="cc-muted">最近最多 50 条。任务状态与定时作业、LLM 归档独立；协作任务没有作业心跳。</p><div className="cc-human-tasks">{data?.tasks.map(task => <article key={task.id}><strong>#{task.id} {task.task_title}</strong><p>{task.task_code} · {agentLabel(task.owner_agent)}</p><p>记录状态：{task.status} · {task.human_review_required ? '需人工审核' : '未要求人工审核'} · 更新 {formatTime(task.updated_at)}</p></article>)}</div>{data && !data.tasks.length && <p className="cc-empty">没有协作任务记录</p>}</section>
  </section>;
}
