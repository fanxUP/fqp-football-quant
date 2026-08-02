import { useMemo, useState } from 'react';
import type { AgentWorkspaceTask } from '../../core/apiClient';
import AgentWorkspaceArchiveItem from './AgentWorkspaceArchiveItem';

interface Props {
  tasks: AgentWorkspaceTask[];
  totalItems: number;
  hasMore: boolean;
  loadingMore: boolean;
  reviewFilter: 'all' | 'reviewed' | 'pending';
  busyTaskId: number | null;
  onReviewFilterChange: (reviewFilter: 'all' | 'reviewed' | 'pending') => void;
  onLoadMore: () => void;
  onSetReviewed: (task: AgentWorkspaceTask, reviewNote?: string) => void;
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
      {visibleTasks.map((task) => <AgentWorkspaceArchiveItem key={task.id} task={task} busy={busyTaskId === task.id}
        onSetReviewed={onSetReviewed} onRemove={onRemove} />)}</div>}
      {hasMore && <button type="button" className="fqp-btn agent-workspace-load-more" disabled={loadingMore} onClick={onLoadMore}>{loadingMore ? '正在加载…' : '加载更多归档任务'}</button>}
    </>}
  </section>;
}
