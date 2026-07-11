import PageHeader from '../shared/components/PageHeader';
import Card from '../shared/components/Card';
import { useLocalSettings } from '../shared/hooks/useLocalSettings';
import { toast } from '../shared/components/Toast';
import { useTheme, type Theme } from '../app/ThemeContext';

const THEME_OPTIONS: { value: Theme; label: string; icon: string; desc: string }[] = [
  { value: 'dark',   label: '红黑科技',   icon: '🔴', desc: '暗色红黑电竞风格（默认）' },
  { value: 'light',  label: '亮色模式',   icon: '☀️', desc: '明亮清爽' },
  { value: 'matrix', label: '黑客帝国',   icon: '🟢', desc: '绿色代码雨，黑色背景' },
  { value: 'cyberpunk', label: '赛博朋克', icon: '🟣', desc: '霓虹紫黄，暗夜迷幻' },
  { value: 'anime',  label: '二次元',     icon: '🌸', desc: '樱花粉蓝，可爱治愈' },
  { value: 'ink',     label: '水墨风格',   icon: '🎨', desc: '黑白水墨，东方韵味' },
];

export default function SettingsPage() {
  const { settings, updateSetting, resetSettings } = useLocalSettings();
  const { theme, setTheme } = useTheme();

  const handleSave = () => {
    // Settings are auto-saved via useEffect in the hook, but we show confirmation
    toast.success('设置已保存');
  };

  const handleReset = () => {
    resetSettings();
    toast.warning('已恢复默认设置');
  };

  return (
    <div style={{ maxWidth: '700px' }}>
      <PageHeader title="本地设置" />

      {/* Budget */}
      <Card title="资金管理" style={{ marginBottom: '20px' }} entranceDelay={0}>
        <div className="fqp-form-row">
          <div className="fqp-form-group">
            <label className="fqp-label">每日预算 (¥)</label>
            <input
              className="fqp-input"
              type="number"
              min="0"
              step="10"
              value={settings.dailyBudget}
              onChange={(e) => updateSetting('dailyBudget', Number(e.target.value))}
            />
            <div className="fqp-form-error" style={{ color: 'var(--fqp-text-muted)', marginTop: '6px' }}>
              建议 500 元以内，单日亏损上限
            </div>
          </div>
          <div className="fqp-form-group">
            <label className="fqp-label">风控模式</label>
            <select
              className="fqp-select"
              value={settings.riskMode}
              onChange={(e) =>
                updateSetting('riskMode', e.target.value as 'conservative' | 'balanced' | 'aggressive')
              }
            >
              <option value="conservative">保守 — 低风险低回报</option>
              <option value="balanced">平衡 — 均衡风险收益</option>
              <option value="aggressive">激进 — 高风险高回报</option>
            </select>
          </div>
        </div>
      </Card>

      {/* Security */}
      <Card title="安全" style={{ marginBottom: '20px' }} entranceDelay={100}>
        <div className="fqp-form-row">
          <div className="fqp-form-group">
            <label className="fqp-label">本地PIN保护</label>
            <select
              className="fqp-select"
              value={settings.pinEnabled ? '1' : '0'}
              onChange={(e) => updateSetting('pinEnabled', e.target.value === '1')}
            >
              <option value="0">关闭</option>
              <option value="1">开启</option>
            </select>
          </div>
          {settings.pinEnabled && (
            <div className="fqp-form-group" style={{ animation: 'fqpSlideInRight 0.3s ease both' }}>
              <label className="fqp-label">PIN码 (4-6位数字)</label>
              <input
                className="fqp-input"
                type="password"
                maxLength={6}
                value={settings.pinCode}
                onChange={(e) => updateSetting('pinCode', e.target.value)}
                placeholder="输入4-6位数字"
              />
            </div>
          )}
        </div>
      </Card>

      {/* UI */}
      <Card title="界面" style={{ marginBottom: '20px' }} entranceDelay={200}>
        <div className="fqp-form-group" style={{ marginBottom: '20px' }}>
          <label className="fqp-label" style={{ marginBottom: '10px', display: 'block' }}>页面风格</label>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '8px' }}>
            {THEME_OPTIONS.map((opt) => (
              <div
                key={opt.value}
                onClick={() => setTheme(opt.value)}
                style={{
                  cursor: 'pointer',
                  padding: '12px 10px',
                  borderRadius: '10px',
                  textAlign: 'center',
                  border: theme === opt.value
                    ? '2px solid var(--fqp-accent)'
                    : '2px solid var(--fqp-border)',
                  background: theme === opt.value
                    ? 'var(--fqp-hover-bg)'
                    : 'transparent',
                  transition: 'all 0.15s ease',
                }}
              >
                <div style={{ fontSize: '22px', marginBottom: '4px' }}>{opt.icon}</div>
                <div style={{ fontSize: '12px', fontWeight: theme === opt.value ? 700 : 500, color: 'var(--fqp-text)' }}>
                  {opt.label}
                </div>
                <div style={{ fontSize: '10px', color: 'var(--fqp-text-muted)', marginTop: '2px', lineHeight: 1.3 }}>
                  {opt.desc}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="fqp-form-row">
          <div className="fqp-form-group">
            <label className="fqp-label">动画效果</label>
            <select
              className="fqp-select"
              value={settings.animationsEnabled ? '1' : '0'}
              onChange={(e) => updateSetting('animationsEnabled', e.target.value === '1')}
            >
              <option value="1">开启</option>
              <option value="0">关闭（减少动效）</option>
            </select>
          </div>
          <div className="fqp-form-group">
            <label className="fqp-label">侧边栏默认状态</label>
            <select
              className="fqp-select"
              value={settings.sidebarCollapsed ? '1' : '0'}
              onChange={(e) => updateSetting('sidebarCollapsed', e.target.value === '1')}
            >
              <option value="0">展开</option>
              <option value="1">折叠</option>
            </select>
          </div>
        </div>
      </Card>

      {/* Backup */}
      <Card title="备份" style={{ marginBottom: '20px' }} entranceDelay={300}>
        <div className="fqp-form-group">
          <label className="fqp-label">备份路径</label>
          <input
            className="fqp-input"
            value={settings.backupPath}
            onChange={(e) => updateSetting('backupPath', e.target.value)}
            placeholder="如: ~/fqp-backups"
          />
          <div className="fqp-form-error" style={{ color: 'var(--fqp-text-muted)', marginTop: '6px' }}>
            数据库备份文件的本地存储路径
          </div>
        </div>
      </Card>

      {/* Actions */}
      <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end' }}>
        <button className="fqp-btn fqp-btn-danger" onClick={handleReset}>
          恢复默认设置
        </button>
        <button className="fqp-btn fqp-btn-primary" onClick={handleSave}>
          保存设置
        </button>
      </div>
    </div>
  );
}
