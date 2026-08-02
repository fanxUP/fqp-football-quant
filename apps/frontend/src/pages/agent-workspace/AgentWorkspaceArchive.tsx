import { useMemo, useState } from 'react';
import type { AgentWorkspaceTask } from '../../core/apiClient';

function formatTime(value: string | null) {
  return value ? new Intl.DateTimeFormat('zh-CN', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value)) : '时间未知';
}

function downloadTaskMarkdown(task: AgentWorkspaceTask) {
  const confirmation = task.reviewedAt ? `已人工确认：${formatTime(task.reviewedAt)}` : '待人工确认';
  const content = `# ${task.title}\n\n- 任务编号：${task.id}\n- Agent：${task.agentCode}\n- 模型：${task.providerCode} · ${task.model}\n- 创建时间：${formatTime(task.createdAt)}\n- 人工确认：${confirmation}\n\n> 模型输出为非可信内容，请人工核验后使用。\n\n## 任务材料\n\n${task.prompt}\n\n## 分析结果\n\n${task.response}\n`;
  const url = URL.createObjectURL(new Blob([content], { type: 'text/markdown;charset=utf-8' }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `智能工作台-${task.id}-${task.title.replace(/[^\u4e00-\u9fa5a-zA-Z0-9_-]/g, '_').slice(0, 32)}.md`;
  anchor.click();
  URL.revokeObjectURL(url);
}

interface Props {
  tasks: AgentWorkspaceTask[];
  totalItems: number;
  hasMore: boolean;
  loadingMore: boolean;
  reviewFilter: 'all' | 'reviewed' | 'pending';
  busyTaskId: number | null;
  onReviewFilterChange: (reviewFilter: 'all' | 'reviewed' | 'pending') => void;
  onLoadMore: () => void;
  onSetReviewed: (task: AgentWorkspaceTask) => void;
  onRemove: (task: AgentWorkspaceTask) => void;
}

export default function AgentWorkspaceArchive({
  tasks, totalItems, hasMore, loadingMore, reviewFilter, busyTaskId,
  onReviewFilterChange, onLoadMore, onSetReviewed, onRemove,
}: Props) {
  const [query, setQuery] = useState('');
  const visibleTasks = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    return tasks.filter((task) => {
      const reviewMatches = reviewFilter === 'all' || (reviewFilter === 'reviewed' ? Boolean(task.reviewedAt) : !task.reviewedAt);
      const keywordMatches = !keyword || [task.title, task.agentCode, task.providerCode, task.model, task.prompt, task.response]
        .some((value) => value.toLowerCase().includes(keyword));
      return reviewMatches && keywordMatches;
    });
  }, [query, reviewFilter, tasks]);

  return <section className="agent-workspace-archive" aria-labelledby="agent-workspace-archive-title">
    <div><h3 id="agent-workspace-archive-title">任务归档</h3><p>仅保存人工发起的分析材料与结果；模型输出始终需要人工核验。</p></div>
    {tasks.length === 0 ? <p className="agent-workspace-archive-empty" role="status">尚无归档任务。完成一次分析后会显示在这里。</p> : <>
      <div className="agent-workspace-archive-filters">
        <div><label className="fqp-label" htmlFor="workspace-archive-search">检索归档</label>
          <input id="workspace-archive-search" className="fqp-input" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="标题、Agent、材料或结果关键词" /></div>
        <div><label className="fqp-label" htmlFor="workspace-archive-review">核验状态</label>
          <select id="workspace-archive-review" className="fqp-input" value={reviewFilter} onChange={(event) => onReviewFilterChange(event.target.value as typeof reviewFilter)}>
            <option value="all">全部状态</option><option value="pending">待人工确认</option><option value="reviewed">已人工确认</option>
          </select></div>
      </div>
      <p className="agent-workspace-archive-count" role="status">已载入 {tasks.length} / {totalItems} 条{query.trim() ? '，关键词仅检索已载入任务' : ''}</p>
      {visibleTasks.length === 0 ? <p className="agent-workspace-archive-empty" role="status">没有符合条件的归档任务。</p> : <div className="agent-workspace-archive-list">
      {visibleTasks.map((task) => <article key={task.id} className="agent-workspace-archive-item">
        <header><div><strong>{task.title}</strong><span>{task.agentCode} · {task.providerCode} · {task.model}</span></div><time>{formatTime(task.createdAt)}</time></header>
        <details><summary>查看任务材料与分析结果</summary><div className="agent-workspace-archive-content"><h4>任务材料</h4><pre>{task.prompt}</pre><h4>分析结果</h4><pre>{task.response}</pre></div></details>
        <footer><span data-reviewed={Boolean(task.reviewedAt)}>{task.reviewedAt ? `已人工确认 · ${formatTime(task.reviewedAt)}` : '待人工确认'}</span><div>
          <button type="button" className="fqp-btn" disabled={busyTaskId === task.id} onClick={() => onSetReviewed(task)}>{task.reviewedAt ? '撤销确认' : '确认已核验'}</button>
          <button type="button" className="fqp-btn" onClick={() => downloadTaskMarkdown(task)}>导出 Markdown</button>
          <button type="button" className="fqp-btn fqp-btn-danger" disabled={busyTaskId === task.id} onClick={() => onRemove(task)}>删除</button>
        </div></footer>
      </article>)}</div>}
      {hasMore && <button type="button" className="fqp-btn agent-workspace-load-more" disabled={loadingMore} onClick={onLoadMore}>{loadingMore ? '正在加载…' : '加载更多归档任务'}</button>}
    </>}
  </section>;
}
