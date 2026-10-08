import PageHeader from '../shared/components/PageHeader';
import ModelProviderSettingsPanel from './settings/ModelProviderSettingsPanel';

/** Standalone workspace for configuring external language-model providers. */
export default function ModelProvidersPage() {
  return (
    <div className="settings-page">
      <PageHeader
        title="模型接入"
        subtitle="通过 Pi 连接模型供应商，管理账号授权、模型选择与代理绑定"
      />
      <ModelProviderSettingsPanel />
    </div>
  );
}
