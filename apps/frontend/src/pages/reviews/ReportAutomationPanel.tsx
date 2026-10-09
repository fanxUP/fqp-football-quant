import { useRef, useState } from 'react';
import { api, type ReportAutomationState } from '../../core/apiClient';
import useManualEvidence from '../useManualEvidence';
import ReadEvidenceStatus from '../ReadEvidenceStatus';
import '../BusinessEvidence.css';
import './ReportAutomationPanel.css';

function checkedAutomation(automation: ReportAutomationState) {
  if (!automation || typeof automation.enabled !== 'boolean' || typeof automation.agentReady !== 'boolean' || automation.agentCode !== 'post_match_report_agent') throw new Error('自动报告设置格式不正确');
  return automation;
}
export default function ReportAutomationPanel() {
  const resource = useManualEvidence(async () => checkedAutomation((await api.reportAutomation.get()).automation));
  const automation = resource.data;
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const writing = useRef(false);
  const update = async (enabled: boolean) => {
    if (writing.current || resource.isReading() || !automation || resource.error) return;
    writing.current = true;
    setSaving(true);
    setError(null);
    try {
      const response = checkedAutomation((await api.reportAutomation.save(enabled)).automation);
      if (response.enabled !== enabled) throw new Error('自动报告保存结果与所选状态不一致');
      resource.update(() => response);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '自动报告设置保存失败');
    } finally { writing.current = false; setSaving(false); }
  };

  const enabled = Boolean(automation?.enabled);
  const canEnable = Boolean(automation?.agentReady);

  return (
    <section className="report-automation-panel be-page" aria-labelledby="report-automation-title">
      <div className="report-automation-panel-copy">
        <h2 id="report-automation-title">自动赛后报告</h2>
        <p>在日报、周报、月报完成后，基于冻结材料生成一次待人工核验的解读；不会参与预测、投注、风控或结算。</p>
        <ReadEvidenceStatus resource={{ ...resource, loading: resource.loading || saving }} label="刷新自动报告设置" note="读取配置，不触发生成" />
        {automation && (
          <div className="report-automation-state" role="status">
            <strong>{enabled ? '自动生成已开启' : '自动生成已关闭'}</strong>
            {automation.providerName && automation.model && <span>{automation.providerName} · {automation.model}</span>}
            {!canEnable && <span>需先在模型接入中启用并测试“自动赛后报告 Agent”</span>}
          </div>
        )}
        {error && <span className="report-automation-error" role="alert">{error}</span>}
      </div>
      <div className="report-automation-actions">
        <button
          type="button"
          className={`fqp-btn${enabled ? ' fqp-btn-secondary' : ''}`}
          disabled={resource.loading || saving || !!resource.error || !automation || (!enabled && !canEnable)}
          onClick={() => void update(!enabled)}
        >
          {saving ? '保存中…' : enabled ? '关闭自动生成' : '开启自动生成'}
        </button>
        <span className="report-automation-note">模型输出需人工核验</span>
      </div>
    </section>
  );
}
