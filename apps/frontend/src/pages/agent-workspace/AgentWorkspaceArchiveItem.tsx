import { useState } from 'react';
import type { AgentWorkspaceTask } from '../../core/apiClient';
import { downloadTaskMarkdown, formatTime } from './archiveHelpers';

interface Props {
  task: AgentWorkspaceTask;
  busy: boolean;
  onSetReviewed: (task: AgentWorkspaceTask, reviewNote?: string) => void;
  onRemove: (task: AgentWorkspaceTask) => void;
}

export default function AgentWorkspaceArchiveItem({ task, busy, onSetReviewed, onRemove }: Props) {
  const [reviewNote, setReviewNote] = useState(task.reviewNote ?? '');
  const reviewed = Boolean(task.reviewedAt);

  return <article className="agent-workspace-archive-item">
    <header><div><strong>{task.title}</strong><span>{task.agentCode} · {task.providerCode} · {task.model}</span></div><time>{formatTime(task.createdAt)}</time></header>
    <details><summary>查看任务材料与分析结果</summary><div className="agent-workspace-archive-content"><h4>任务材料</h4><pre>{task.prompt}</pre><h4>分析结果</h4><pre>{task.response}</pre></div></details>
    {reviewed && task.reviewNote && <p className="agent-workspace-review-note"><b>核验备注：</b>{task.reviewNote}</p>}
    {!reviewed && <div className="agent-workspace-review-input"><label className="fqp-label" htmlFor={`workspace-review-note-${task.id}`}>核验备注（可选）</label>
      <textarea id={`workspace-review-note-${task.id}`} className="fqp-input" maxLength={2000} disabled={busy} value={reviewNote}
        onChange={(event) => setReviewNote(event.target.value)} placeholder="例如：已核对数据来源。请勿记录密钥或敏感信息。" /></div>}
    <footer><span data-reviewed={reviewed}>{reviewed ? `已人工确认 · ${formatTime(task.reviewedAt)}` : '待人工确认'}</span><div>
      <button type="button" className="fqp-btn" disabled={busy} onClick={() => onSetReviewed(task, reviewNote)}>{reviewed ? '撤销确认' : '确认并归档'}</button>
      <button type="button" className="fqp-btn" onClick={() => downloadTaskMarkdown(task)}>导出 Markdown</button>
      <button type="button" className="fqp-btn fqp-btn-danger" disabled={busy} onClick={() => onRemove(task)}>删除</button>
    </div></footer>
  </article>;
}
