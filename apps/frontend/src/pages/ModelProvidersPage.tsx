import PageHeader from '../shared/components/PageHeader';
import ModelProviderSettingsPanel from './settings/ModelProviderSettingsPanel';

/** Standalone workspace for configuring external language-model providers. */
export default function ModelProvidersPage() {
  return (
    <div className="settings-page">
      <PageHeader
        title="模型接入"
        subtitle="统一配置模型服务商、默认模型与连接状态"
      />
      <ModelProviderSettingsPanel />
    </div>
  );
}
