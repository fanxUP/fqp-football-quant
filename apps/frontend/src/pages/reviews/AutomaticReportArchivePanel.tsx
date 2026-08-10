import { useEffect, useState } from 'react';
import { api, type AgentWorkspaceTask } from '../../core/apiClient';
import './AutomaticReportArchivePanel.css';

type ReportSourceType = 'post_daily' | 'post_weekly' | 'post_monthly';

export default function AutomaticReportArchivePanel({
  sourceType, sourceRef,
}: { sourceType: ReportSourceType; sourceRef: string }) {
  const [task, setTask] = useState<AgentWorkspaceTask | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setFailed(false);
    api.reportAutomation.archive(sourceType, sourceRef)
      .then((response) => { if (active) setTask(response.task); })
      .catch(() => { if (active) { setTask(null); setFailed(true); } })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [sourceType, sourceRef]);

  if (loading) return <p className="automatic-report-archive-status" role="status">正在读取自动赛后报告…</p>;
  if (failed) return <p className="automatic-report-archive-status" role="alert">自动赛后报告读取失败，请稍后重试。</p>;
  if (!task) return <p className="automatic-report-archive-status">本期暂无自动赛后报告</p>;

  return <section className="automatic-report-archive" aria-labelledby={`automatic-report-${task.id}`}>
    <div className="automatic-report-archive-heading">
      <div>
        <h3 id={`automatic-report-${task.id}`}>自动赛后报告</h3>
        <p>{task.providerCode} · {task.model} · 已归档至智能工作台 #{task.id}</p>
      </div>
      <a className="fqp-btn fqp-btn-secondary" href="#/agent-workspace">前往智能工作台核验</a>
    </div>
    <p className="automatic-report-archive-safety">模型输出仅供人工核验</p>
    <pre>{task.response}</pre>
  </section>;
}
