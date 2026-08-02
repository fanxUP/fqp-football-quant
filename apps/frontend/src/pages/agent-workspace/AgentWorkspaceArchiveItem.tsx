import { useEffect, useState } from 'react';
import { api, type AgentWorkspaceComparison, type AgentWorkspaceReviewEvent, type AgentWorkspaceTask } from '../../core/apiClient';
import { toast } from '../../shared/components/Toast';
import { downloadTaskMarkdown, formatTime } from './archiveHelpers';

interface Props {
  task: AgentWorkspaceTask;
  busy: boolean;
  onSetReviewed: (task: AgentWorkspaceTask, reviewNote?: string) => void;
  onRemove: (task: AgentWorkspaceTask) => void;
}

export default function AgentWorkspaceArchiveItem({ task, busy, onSetReviewed, onRemove }: Props) {
  const [reviewNote, setReviewNote] = useState(task.reviewNote ?? '');
  const [history, setHistory] = useState<AgentWorkspaceReviewEvent[] | null>(null);
  const [comparisonTasks, setComparisonTasks] = useState<AgentWorkspaceTask[] | null>(null);
  const [comparison, setComparison] = useState<AgentWorkspaceComparison | null>(null);
  const [comparisonReviewNote, setComparisonReviewNote] = useState('');
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [loadingComparison, setLoadingComparison] = useState(false);
  const [savingComparisonReview, setSavingComparisonReview] = useState(false);
  const [exporting, setExporting] = useState(false);
  const reviewed = Boolean(task.reviewedAt);
  useEffect(() => {
    setReviewNote(task.reviewNote ?? '');
  }, [task.id, task.reviewNote, task.reviewedAt]);

  const loadHistory = async () => {
    setLoadingHistory(true);
    try { setHistory((await api.agentWorkspace.reviewHistory(task.id)).events); }
    catch (error) { toast.error(error instanceof Error ? error.message : '核验历史加载失败'); }
    finally { setLoadingHistory(false); }
  };
  const exportMarkdown = async () => {
    setExporting(true);
    try {
      const events = history ?? (await api.agentWorkspace.reviewHistory(task.id)).events;
      downloadTaskMarkdown(task, events);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '核验历史加载失败，暂无法导出');
    } finally {
      setExporting(false);
    }
  };
  const loadComparison = async () => {
    if (!task.comparisonId) return;
    setLoadingComparison(true);
    try {
      const result = await api.agentWorkspace.comparison(task.comparisonId);
      setComparison(result.comparison);
      setComparisonReviewNote(result.comparison?.reviewNote ?? '');
      setComparisonTasks(result.tasks);
    }
    catch (error) { toast.error(error instanceof Error ? error.message : '多模型对比加载失败'); }
    finally { setLoadingComparison(false); }
  };
  const saveComparisonReview = async () => {
    if (!task.comparisonId || !comparisonReviewNote.trim()) return;
    setSavingComparisonReview(true);
    try {
      const result = await api.agentWorkspace.setComparisonReview(task.comparisonId, comparisonReviewNote.trim());
      setComparison(result.comparison);
      toast.success('已保存本批人工结论');
    } catch (error) { toast.error(error instanceof Error ? error.message : '人工结论保存失败'); }
    finally { setSavingComparisonReview(false); }
  };

  return <article className="agent-workspace-archive-item">
    <header><div><strong>{task.title}</strong><span>{task.agentCode} · {task.providerCode} · {task.model}{task.comparisonId ? ' · 多模型对比' : ''}</span></div><time>{formatTime(task.createdAt)}</time></header>
    <details><summary>查看任务材料与分析结果</summary><div className="agent-workspace-archive-content"><h4>任务材料</h4><pre>{task.prompt}</pre><h4>分析结果</h4><pre>{task.response}</pre></div></details>
    {reviewed && task.reviewNote && <p className="agent-workspace-review-note"><b>核验备注：</b>{task.reviewNote}</p>}
    {!reviewed && <div className="agent-workspace-review-input"><label className="fqp-label" htmlFor={`workspace-review-note-${task.id}`}>核验备注（可选）</label>
      <textarea id={`workspace-review-note-${task.id}`} className="fqp-input" maxLength={2000} disabled={busy} value={reviewNote}
        onChange={(event) => setReviewNote(event.target.value)} placeholder="例如：已核对数据来源。请勿记录密钥或敏感信息。" /></div>}
    <footer><span data-reviewed={reviewed}>{reviewed ? `已人工确认 · ${formatTime(task.reviewedAt)}` : '待人工确认'}</span><div>
      <button type="button" className="fqp-btn" disabled={busy} onClick={() => { setHistory(null); onSetReviewed(task, reviewNote); }}>{reviewed ? '撤销确认' : '确认并归档'}</button>
      <button type="button" className="fqp-btn" disabled={loadingHistory || exporting} onClick={() => void loadHistory()}>{loadingHistory ? '加载历史…' : '核验历史'}</button>
      {task.comparisonId && <button type="button" className="fqp-btn" disabled={loadingComparison} onClick={() => void loadComparison()}>{loadingComparison ? '加载对比…' : '横向查看本批对比'}</button>}
      <button type="button" className="fqp-btn" disabled={busy || exporting} onClick={() => void exportMarkdown()}>{exporting ? '正在导出…' : '导出 Markdown'}</button>
      <button type="button" className="fqp-btn fqp-btn-danger" disabled={busy} onClick={() => onRemove(task)}>删除</button>
    </div></footer>
    {history && <ol className="agent-workspace-review-history" aria-label="核验历史">
      {history.length === 0 ? <li>尚无核验历史。</li> : history.map((event) => <li key={event.id}><b>{event.action === 'confirmed' ? '已确认' : '已撤销确认'}</b> · {formatTime(event.createdAt)}{event.reviewNote ? ` · ${event.reviewNote}` : ''}</li>)}
    </ol>}
    {comparisonTasks && <section className="agent-workspace-comparison-results" aria-label="同批模型结果">
      <h4>同批模型结果</h4><p>{comparison ? `已完成 · 成功 ${comparison.succeededCount} / ${comparison.requestedCount}，失败 ${comparison.failedCount}。` : '历史批次未保存汇总信息。'} 同一材料由不同模型独立生成，结论仍需人工核验。</p>
      <div>{comparisonTasks.map((comparisonTask) => <article key={comparisonTask.id}>
        <strong>{comparisonTask.agentCode}</strong><span>{comparisonTask.providerCode} · {comparisonTask.model}</span>
        <pre>{comparisonTask.response}</pre>
      </article>)}</div>
      {comparison && <div className="agent-workspace-comparison-review"><label className="fqp-label" htmlFor={`workspace-comparison-review-${task.id}`}>本批人工结论</label>
        <textarea id={`workspace-comparison-review-${task.id}`} className="fqp-input" maxLength={2000} disabled={savingComparisonReview} value={comparisonReviewNote} onChange={(event) => setComparisonReviewNote(event.target.value)} placeholder="仅记录人工核验后的结论，不要记录密钥或敏感信息。" />
        <button type="button" className="fqp-btn" disabled={savingComparisonReview || !comparisonReviewNote.trim()} onClick={() => void saveComparisonReview()}>{savingComparisonReview ? '正在保存…' : '保存人工结论'}</button>
      </div>}
    </section>}
  </article>;
}
