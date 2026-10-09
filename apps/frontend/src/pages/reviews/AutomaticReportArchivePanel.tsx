import { api, type AgentWorkspaceTask } from '../../core/apiClient';
import useManualEvidence from '../useManualEvidence';
import ReadEvidenceStatus from '../ReadEvidenceStatus';
import '../BusinessEvidence.css';
import './AutomaticReportArchivePanel.css';

type ReportSourceType = 'post_daily' | 'post_weekly' | 'post_monthly';

export default function AutomaticReportArchivePanel(props: { sourceType: ReportSourceType; sourceRef: string }) {
  return <ArchiveQuery key={`${props.sourceType}:${props.sourceRef}`} {...props} />;
}

function checkedArchive(task: AgentWorkspaceTask | null, sourceType: ReportSourceType, sourceRef: string) {
  if (task === null) return { task };
  if (!task || !Number.isSafeInteger(task.id) || task.id <= 0 || typeof task.response !== 'string') throw new Error('报告归档格式不正确');
  if ((task.sourceType != null && task.sourceType !== sourceType) || (task.sourceRef != null && task.sourceRef !== sourceRef)) throw new Error('报告归档与所选期间不一致');
  return { task };
}
function ArchiveQuery({ sourceType, sourceRef }: { sourceType: ReportSourceType; sourceRef: string }) {
  const resource = useManualEvidence(async () => checkedArchive((await api.reportAutomation.archive(sourceType, sourceRef)).task, sourceType, sourceRef));
  const task = resource.data?.task;
  const status = <ReadEvidenceStatus resource={resource} label="刷新自动报告归档" note={`${{ post_daily: '日报', post_weekly: '周报', post_monthly: '月报' }[sourceType]} · ${sourceRef} · 只读取已归档文字`} />;
  if (!resource.data) return <div className="be-page">{status}</div>;
  if (!task) return <div className="be-page">{status}<p className="automatic-report-archive-status">本期暂无自动赛后报告</p></div>;

  return <section className="automatic-report-archive be-page" aria-labelledby={`automatic-report-${task.id}`}>
    {status}
    {(!task.sourceType || !task.sourceRef) && <p role="note" className="automatic-report-archive-status">历史归档缺少来源字段，无法完整核对期间；当前按所选期间接口读取。</p>}
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
