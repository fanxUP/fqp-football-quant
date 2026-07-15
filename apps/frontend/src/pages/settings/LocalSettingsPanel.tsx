import Card from '../../shared/components/Card';
import { toast } from '../../shared/components/Toast';
import { useLocalSettings } from '../../shared/hooks/useLocalSettings';

export default function LocalSettingsPanel() {
  const { settings, updateSetting, resetSettings } = useLocalSettings();
  const reset = () => {
    resetSettings();
    toast.warning('本地业务设置已恢复默认');
  };

  return (
    <section className="local-settings-panel" aria-labelledby="local-settings-title">
      <div className="local-settings-heading">
        <h2 id="local-settings-title">本地业务设置</h2>
        <p>资金、安全和备份配置与外观设置相互独立。</p>
      </div>
      <div className="local-settings-grid">
        <Card title="资金与风控">
          <label className="fqp-label" htmlFor="daily-budget">每日预算（元）</label>
          <input id="daily-budget" className="fqp-input" type="number" min="0" step="10" value={settings.dailyBudget} onChange={(event) => updateSetting('dailyBudget', Number(event.target.value))} />
          <label className="fqp-label" htmlFor="risk-mode">风控模式</label>
          <select id="risk-mode" className="fqp-select" value={settings.riskMode} onChange={(event) => updateSetting('riskMode', event.target.value as typeof settings.riskMode)}>
            <option value="conservative">保守</option>
            <option value="balanced">平衡</option>
            <option value="aggressive">激进</option>
          </select>
        </Card>
        <Card title="安全与备份">
          <label className="appearance-checkbox-row">
            <input type="checkbox" checked={settings.pinEnabled} onChange={(event) => updateSetting('pinEnabled', event.target.checked)} />
            <span>启用本地 PIN 保护</span>
          </label>
          {settings.pinEnabled && (
            <input aria-label="PIN 码" className="fqp-input" type="password" maxLength={6} value={settings.pinCode} onChange={(event) => updateSetting('pinCode', event.target.value)} placeholder="4–6 位数字" />
          )}
          <label className="fqp-label" htmlFor="backup-path">备份路径</label>
          <input id="backup-path" className="fqp-input" value={settings.backupPath} onChange={(event) => updateSetting('backupPath', event.target.value)} />
        </Card>
      </div>
      <div className="local-settings-actions">
        <button type="button" className="fqp-btn fqp-btn-danger" onClick={reset}>恢复业务设置默认值</button>
      </div>
    </section>
  );
}
