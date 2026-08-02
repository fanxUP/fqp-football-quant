import { useEffect, useMemo, useState } from 'react';
import { api, type ModelProviderConnection, type ModelProviderPreset } from '../../core/apiClient';
import Card from '../../shared/components/Card';
import { toast } from '../../shared/components/Toast';
import AgentModelBindings from './AgentModelBindings';

type Draft = { baseUrl: string; defaultModel: string; apiKey: string; enabled: boolean };

const capabilityLabels: Record<string, string> = {
  analysis: '分析', coding: '代码', vision: '图像',
};

function initialDraft(preset: ModelProviderPreset, saved?: ModelProviderConnection): Draft {
  return {
    baseUrl: saved?.baseUrl ?? preset.defaultBaseUrl,
    defaultModel: saved?.defaultModel ?? preset.defaultModel,
    apiKey: '',
    enabled: saved?.enabled ?? false,
  };
}

export default function ModelProviderSettingsPanel() {
  const [catalog, setCatalog] = useState<ModelProviderPreset[]>([]);
  const [connections, setConnections] = useState<ModelProviderConnection[]>([]);
  const [selectedCode, setSelectedCode] = useState('openai');
  const [draft, setDraft] = useState<Draft | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);

  const selected = useMemo(
    () => catalog.find((item) => item.providerCode === selectedCode),
    [catalog, selectedCode],
  );
  const saved = useMemo(
    () => connections.find((item) => item.providerCode === selectedCode),
    [connections, selectedCode],
  );

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.modelProviders.catalog(), api.modelProviders.list()])
      .then(([catalogResult, connectionsResult]) => {
        if (cancelled) return;
        setCatalog(catalogResult.providers);
        setConnections(connectionsResult.providers);
        const first = catalogResult.providers.find((item) => item.providerCode === 'openai') ?? catalogResult.providers[0];
        if (first) {
          setSelectedCode(first.providerCode);
          setDraft(initialDraft(first, connectionsResult.providers.find((item) => item.providerCode === first.providerCode)));
        }
      })
      .catch((error: Error) => toast.error(`模型接入配置加载失败：${error.message}`))
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  const chooseProvider = (provider: ModelProviderPreset) => {
    setSelectedCode(provider.providerCode);
    setDraft(initialDraft(provider, connections.find((item) => item.providerCode === provider.providerCode)));
  };

  const updateDraft = (patch: Partial<Draft>) => setDraft((current) => current ? { ...current, ...patch } : current);

  const save = async () => {
    if (!selected || !draft) return;
    setSaving(true);
    try {
      const result = await api.modelProviders.save(selected.providerCode, {
        providerCode: selected.providerCode,
        baseUrl: draft.baseUrl,
        defaultModel: draft.defaultModel,
        apiKey: draft.apiKey || undefined,
        enabled: draft.enabled,
      });
      setConnections((current) => [...current.filter((item) => item.providerCode !== selected.providerCode), result.provider]);
      setDraft((current) => current ? { ...current, apiKey: '' } : current);
      toast.success('模型服务商配置已加密保存');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const test = async () => {
    if (!selected) return;
    setTesting(true);
    try {
      const result = await api.modelProviders.test(selected.providerCode);
      setConnections((current) => current.map((item) => item.providerCode === selected.providerCode
        ? { ...item, lastTestStatus: result.status, lastTestMessage: result.message, lastTestAt: result.testedAt } : item));
      result.status === 'passed' ? toast.success(result.message) : toast.error(result.message);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '测试失败');
    } finally {
      setTesting(false);
    }
  };

  return (
    <section className="model-provider-panel" aria-labelledby="model-provider-title">
      <div className="local-settings-heading">
        <div>
          <span className="appearance-eyebrow">MODEL GATEWAY</span>
          <h2 id="model-provider-title">模型接入中心</h2>
          <p>预置服务商统一接入；密钥仅加密保存在服务器，页面不会回显。</p>
        </div>
        <span className="appearance-live-status"><i />按能力路由准备就绪</span>
      </div>

      {loading ? <p className="model-provider-state">正在加载服务商配置…</p> : (
        <>
          <div className="model-provider-layout">
            <div className="model-provider-list" role="list" aria-label="模型服务商">
            {catalog.map((provider) => {
              const connection = connections.find((item) => item.providerCode === provider.providerCode);
              return (
                <button key={provider.providerCode} type="button" className="model-provider-item"
                  data-selected={provider.providerCode === selectedCode} onClick={() => chooseProvider(provider)}>
                  <strong>{provider.displayName}</strong>
                  <span>{connection?.enabled ? '已启用' : connection?.hasApiKey ? '已保存' : '未配置'}</span>
                </button>
              );
            })}
            </div>

            {selected && draft && <Card title={selected.displayName} className="model-provider-editor">
            <div className="model-provider-meta">
              {selected.capabilities.map((capability) => <span key={capability}>{capabilityLabels[capability] ?? capability}</span>)}
              {saved?.lastTestStatus && <span data-status={saved.lastTestStatus}>{saved.lastTestStatus === 'passed' ? '最近测试通过' : '最近测试失败'}</span>}
            </div>
            <label className="fqp-label" htmlFor="model-base-url">服务地址</label>
            <input id="model-base-url" className="fqp-input" value={draft.baseUrl} onChange={(event) => updateDraft({ baseUrl: event.target.value })} />
            <label className="fqp-label" htmlFor="model-default">默认模型</label>
            <input id="model-default" className="fqp-input" value={draft.defaultModel} onChange={(event) => updateDraft({ defaultModel: event.target.value })} placeholder="例如 gpt-5.2" list="model-recommendations" />
            <datalist id="model-recommendations">
              {selected.recommendedModels.map((model) => <option key={model} value={model} />)}
            </datalist>
            {selected.recommendedModels.length > 0 && <div className="model-provider-models" aria-label="推荐模型">
              <span>推荐模型</span>
              <div>
                {selected.recommendedModels.map((model) => <button key={model} type="button" className="model-provider-model"
                  data-selected={draft.defaultModel === model} onClick={() => updateDraft({ defaultModel: model })}>{model}</button>)}
              </div>
            </div>}
            {selected.requiresApiKey && <>
              <label className="fqp-label" htmlFor="model-api-key">API 密钥 {saved?.hasApiKey ? '（已保存；留空则保持不变）' : ''}</label>
              <input id="model-api-key" className="fqp-input" type="password" autoComplete="off" value={draft.apiKey} onChange={(event) => updateDraft({ apiKey: event.target.value })} placeholder={saved?.hasApiKey ? '留空则保留已保存密钥' : '仅在保存时上传到服务器'} />
            </>}
            <label className="appearance-checkbox-row model-provider-enabled">
              <input type="checkbox" checked={draft.enabled} onChange={(event) => updateDraft({ enabled: event.target.checked })} />
              <span>启用此服务商参与模型路由</span>
            </label>
            <div className="model-provider-actions">
              <button type="button" className="fqp-btn" disabled={saving} onClick={() => void save()}>{saving ? '保存中…' : '加密保存'}</button>
              <button type="button" className="fqp-btn fqp-btn-primary" disabled={testing || !saved?.hasApiKey && selected.requiresApiKey} onClick={() => void test()}>{testing ? '测试中…' : '测试连接'}</button>
            </div>
            {saved?.lastTestMessage && <p className="model-provider-test-message" data-status={saved.lastTestStatus ?? undefined}>{saved.lastTestMessage}</p>}
            <a className="model-provider-docs" href={selected.documentationUrl} target="_blank" rel="noreferrer">查看官方接入文档 ↗</a>
            </Card>}
          </div>
          <AgentModelBindings providers={connections} />
        </>
      )}
    </section>
  );
}
