import type { AgentWorkspaceTask } from '../../core/apiClient';

function formatTime(value: string | null) {
  return value ? new Intl.DateTimeFormat('zh-CN', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value)) : '时间未知';
}

interface Props {
  tasks: AgentWorkspaceTask[];
  busyTaskId: number | null;
  onSetReviewed: (task: AgentWorkspaceTask) => void;
  onRemove: (task: AgentWorkspaceTask) => void;
}

export default function AgentWorkspaceArchive({ tasks, busyTaskId, onSetReviewed, onRemove }: Props) {
  return <section className="agent-workspace-archive" aria-labelledby="agent-workspace-archive-title">
    <div><h3 id="agent-workspace-archive-title">任务归档</h3><p>仅保存人工发起的分析材料与结果；模型输出始终需要人工核验。</p></div>
    {tasks.length === 0 ? <p className="agent-workspace-archive-empty" role="status">尚无归档任务。完成一次分析后会显示在这里。</p> : <div className="agent-workspace-archive-list">
      {tasks.map((task) => <article key={task.id} className="agent-workspace-archive-item">
        <header><div><strong>{task.title}</strong><span>{task.agentCode} · {task.providerCode} · {task.model}</span></div><time>{formatTime(task.createdAt)}</time></header>
        <details><summary>查看任务材料与分析结果</summary><div className="agent-workspace-archive-content"><h4>任务材料</h4><pre>{task.prompt}</pre><h4>分析结果</h4><pre>{task.response}</pre></div></details>
        <footer><span data-reviewed={Boolean(task.reviewedAt)}>{task.reviewedAt ? `已人工确认 · ${formatTime(task.reviewedAt)}` : '待人工确认'}</span><div>
          <button type="button" className="fqp-btn" disabled={busyTaskId === task.id} onClick={() => onSetReviewed(task)}>{task.reviewedAt ? '撤销确认' : '确认已核验'}</button>
          <button type="button" className="fqp-btn fqp-btn-danger" disabled={busyTaskId === task.id} onClick={() => onRemove(task)}>删除</button>
        </div></footer>
      </article>)}
    </div>}
  </section>;
}
