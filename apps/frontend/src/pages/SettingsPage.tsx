import PageHeader from '../shared/components/PageHeader';
import LocalSettingsPanel from './settings/LocalSettingsPanel';
import PasswordChangePanel from './settings/PasswordChangePanel';

export default function SettingsPage() {
  return (
    <div className="settings-page">
      <PageHeader
        title="系统设置"
        subtitle="管理本地业务偏好与账户安全"
      />
      <LocalSettingsPanel />
      <PasswordChangePanel />
    </div>
  );
}
