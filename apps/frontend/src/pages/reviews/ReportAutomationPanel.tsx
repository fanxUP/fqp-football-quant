import { useEffect, useState } from 'react';
import { api, type ReportAutomationState } from '../../core/apiClient';
import './ReportAutomationPanel.css';

export default function ReportAutomationPanel() {
  const [automation, setAutomation] = useState<ReportAutomationState | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.reportAutomation.get()
      .then((response) => setAutomation(response.automation))
      .catch((reason: Error) => setError(reason.message || '自动报告设置加载失败'))
      .finally(() => setLoading(false));
  }, []);

  const update = async (enabled: boolean) => {
    setSaving(true);
    setError(null);
    try {
      const response = await api.reportAutomation.save(enabled);
      setAutomation(response.automation);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '自动报告设置保存失败');
    } finally {
      setSaving(false);
    }
  };

  const enabled = Boolean(automation?.enabled);
  const canEnable = Boolean(automation?.agentReady);

  return (
    <section className="report-automation-panel" aria-labelledby="report-automation-title">
      <div className="report-automation-panel-copy">
        <h2 id="report-automation-title">自动赛后报告</h2>
        <p>在日报、周报、月报完成后，基于冻结材料生成一次待人工核验的解读；不会参与预测、投注、风控或结算。</p>
        {loading && <span className="report-automation-status" role="status">正在加载设置…</span>}
        {!loading && automation && (
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
          disabled={loading || saving || (!enabled && !canEnable)}
          onClick={() => void update(!enabled)}
        >
          {saving ? '保存中…' : enabled ? '关闭自动生成' : '开启自动生成'}
        </button>
        <span className="report-automation-note">模型输出需人工核验</span>
      </div>
    </section>
  );
}
