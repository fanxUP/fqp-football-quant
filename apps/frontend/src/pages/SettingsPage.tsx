import PageHeader from '../shared/components/PageHeader';
import AppearanceSettingsPanel from './settings/AppearanceSettingsPanel';
import LocalSettingsPanel from './settings/LocalSettingsPanel';

export default function SettingsPage() {
  return (
    <div className="settings-page">
      <PageHeader
        title="系统设置"
        subtitle="外观、显示与本地运行偏好"
      />
      <AppearanceSettingsPanel />
      <LocalSettingsPanel />
    </div>
  );
}
