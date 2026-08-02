import PageHeader from '../shared/components/PageHeader';
import AppearanceSettingsPanel from './settings/AppearanceSettingsPanel';
import LocalSettingsPanel from './settings/LocalSettingsPanel';
import PasswordChangePanel from './settings/PasswordChangePanel';
import ModelProviderSettingsPanel from './settings/ModelProviderSettingsPanel';

export default function SettingsPage() {
  return (
    <div className="settings-page">
      <PageHeader
        title="系统设置"
        subtitle="外观、显示与本地运行偏好"
      />
      <AppearanceSettingsPanel />
      <LocalSettingsPanel />
      <ModelProviderSettingsPanel />
      <PasswordChangePanel />
    </div>
  );
}
