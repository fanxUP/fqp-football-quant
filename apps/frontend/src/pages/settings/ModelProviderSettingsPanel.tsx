import { useEffect, useMemo, useRef, useState } from 'react';
import { api, type ModelProviderConnection, type ModelProviderPreset, type ProviderConfigPayload } from '../../core/apiClient';
import Card from '../../shared/components/Card';
import { toast } from '../../shared/components/Toast';
import AgentModelBindings from './AgentModelBindings';
import ProviderAccountLogin from './ProviderAccountLogin';
import ProviderModelPicker from './ProviderModelPicker';

type Draft = {
  baseUrl: string; defaultModel: string; apiKey: string; apiKeyChanged: boolean; enabled: boolean;
  authType: 'api_key' | 'oauth' | 'none'; apiProtocol: string; providerEnv: string;
};
const legacyApis: Record<string, string> = {
  openai: 'openai-completions', perplexity: 'openai-completions', ollama: 'openai-completions',
  anthropic: 'anthropic-messages', gemini: 'google-generative-ai',
};
const apiLabels: Record<string, string> = {
  auto: '供应商默认接口', 'openai-completions': 'OpenAI Chat Completions',
  'openai-responses': 'OpenAI Responses', 'anthropic-messages': 'Anthropic Messages',
  'google-generative-ai': 'Google Gemini',
};
function initialDraft(preset: ModelProviderPreset, saved?: ModelProviderConnection): Draft {
  return {
    baseUrl: saved?.baseUrl ?? preset.defaultBaseUrl, defaultModel: saved?.defaultModel ?? preset.defaultModel,
    apiKey: saved?.apiKeyMask ?? '', apiKeyChanged: false, enabled: saved?.enabled ?? true,
    authType: saved?.authType ?? preset.authMethods?.[0] ?? (preset.requiresApiKey ? 'api_key' : 'none'),
    apiProtocol: saved?.apiProtocol ?? (saved ? legacyApis[preset.protocol] ?? 'auto' : 'auto'), providerEnv: '',
  };
}
function connected(provider?: ModelProviderConnection) {
  return Boolean(provider?.hasCredential ?? (provider?.hasApiKey || provider && !provider.requiresApiKey));
}

export default function ModelProviderSettingsPanel() {
  const [catalog, setCatalog] = useState<ModelProviderPreset[]>([]);
  const [connections, setConnections] = useState<ModelProviderConnection[]>([]);
  const [selectedCode, setSelectedCode] = useState('openai');
  const [draft, setDraft] = useState<Draft | null>(null);
  const [query, setQuery] = useState('');
  const [onlyConnected, setOnlyConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  const selection = useRef(selectedCode);
  selection.current = selectedCode;
  const selected = useMemo(() => catalog.find((item) => item.providerCode === selectedCode), [catalog, selectedCode]);
  const saved = useMemo(() => connections.find((item) => item.providerCode === selectedCode), [connections, selectedCode]);
  const visible = catalog.filter((provider) => `${provider.providerCode} ${provider.displayName}`.toLowerCase().includes(query.toLowerCase())
    && (!onlyConnected || connected(connections.find((item) => item.providerCode === provider.providerCode))));

  useEffect(() => {
    let cancelled = false;
    setLoading(true); setError('');
    Promise.all([api.modelProviders.catalog(), api.modelProviders.list()]).then(([catalogResult, connectionsResult]) => {
      if (cancelled) return;
      setCatalog(catalogResult.providers); setConnections(connectionsResult.providers);
      const first = catalogResult.providers.find((item) => item.providerCode === 'openai') ?? catalogResult.providers[0];
      if (first) { setSelectedCode(first.providerCode); setDraft(initialDraft(first, connectionsResult.providers.find((item) => item.providerCode === first.providerCode))); }
    }).catch((reason: Error) => { if (!cancelled) setError(reason.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [reload]);

  const chooseProvider = (provider: ModelProviderPreset) => {
    setSelectedCode(provider.providerCode); setDraft(initialDraft(provider, connections.find((item) => item.providerCode === provider.providerCode)));
  };
  const updateDraft = (patch: Partial<Draft>) => setDraft((current) => current ? { ...current, ...patch } : current);
  const acceptConnection = (provider: ModelProviderConnection) => {
    setConnections((current) => [...current.filter((item) => item.providerCode !== provider.providerCode), provider]);
    const preset = catalog.find((item) => item.providerCode === provider.providerCode);
    if (selection.current === provider.providerCode && preset) setDraft(initialDraft(preset, provider));
  };
  const payload: ProviderConfigPayload | null = selected && draft ? {
    providerCode: selected.providerCode, baseUrl: draft.baseUrl, defaultModel: draft.defaultModel,
    authType: draft.authType, apiProtocol: draft.apiProtocol, enabled: draft.enabled,
  } : null;
  const dirty = Boolean(saved && draft && (draft.baseUrl !== saved.baseUrl || draft.defaultModel !== saved.defaultModel
    || draft.authType !== (saved.authType ?? 'api_key') || draft.enabled !== saved.enabled
    || draft.apiKeyChanged || draft.providerEnv.trim()
    || draft.apiProtocol !== (saved.apiProtocol ?? legacyApis[selected?.protocol ?? ''] ?? 'auto')));

  const save = async () => {
    if (!selected || !draft || !payload) return;
    setSaving(true);
    try {
      const providerEnv = draft.providerEnv.trim() ? JSON.parse(draft.providerEnv) as Record<string, string> : undefined;
      if (providerEnv && (typeof providerEnv !== 'object' || Array.isArray(providerEnv))) throw new Error('附加配置必须是 JSON 对象');
      const result = await api.modelProviders.save(selected.providerCode, {
        ...payload, apiKey: draft.authType === 'api_key' && draft.apiKeyChanged && draft.apiKey ? draft.apiKey : undefined, providerEnv,
      });
      acceptConnection(result.provider); toast.success('模型服务商配置已加密保存');
    } catch (reason) { toast.error(reason instanceof Error ? reason.message : '保存失败'); }
    finally { setSaving(false); }
  };
  const test = async () => {
    if (!selected) return;
    const code = selected.providerCode;
    setTesting(true);
    try {
      const result = await api.modelProviders.test(code);
      setConnections((current) => current.map((item) => item.providerCode === code
        ? { ...item, lastTestStatus: result.status, lastTestMessage: result.message, lastTestAt: result.testedAt } : item));
      result.status === 'passed' ? toast.success(result.message) : toast.error(result.message);
    } catch (reason) { toast.error(reason instanceof Error ? reason.message : '测试失败'); }
    finally { setTesting(false); }
  };
  const disconnect = async () => {
    if (!selected || !saved) return;
    const code = selected.providerCode;
    setSaving(true);
    try {
      await api.modelProviders.disconnect(code);
      acceptConnection({ ...saved, enabled: false, hasApiKey: false, apiKeyMask: null, hasCredential: false, lastTestAt: null, lastTestStatus: null, lastTestMessage: null });
      toast.success('已移除接入凭据并停用该服务商的代理调用');
    } catch (reason) { toast.error(reason instanceof Error ? reason.message : '断开失败'); }
    finally { setSaving(false); }
  };
  const authMethods = selected?.authMethods ?? (selected?.requiresApiKey ? ['api_key'] : ['none']);
  return <section className="model-provider-panel" aria-labelledby="model-provider-title">
    <div className="local-settings-heading">
      <div><span className="appearance-eyebrow">PI · 统一模型接入</span><h2 id="model-provider-title">模型接入中心</h2>
        <p>连接供应商，选择模型，验证后绑定智能代理。凭据仅在服务器加密保存。</p></div>
      <span className="appearance-live-status"><i />{connections.filter(connected).length} 个已接入 · {catalog.length} 个供应商</span>
    </div>
    <ol className="pi-connect-steps" aria-label="模型接入步骤"><li>1 连接供应商</li><li>2 选择模型</li><li>3 验证并绑定</li></ol>
    {loading ? <p className="model-provider-state">正在加载 Pi 供应商目录…</p>
      : error ? <div role="alert"><p>模型接入配置加载失败：{error}</p><button className="fqp-btn" onClick={() => setReload((n) => n + 1)}>重新加载</button></div>
        : <>
          <div className="model-provider-layout">
            <aside className="pi-provider-sidebar">
              <label className="fqp-label" htmlFor="pi-provider-search">搜索供应商</label>
              <input id="pi-provider-search" type="search" className="fqp-input" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="名称或供应商 ID" />
              <label className="appearance-checkbox-row"><input type="checkbox" checked={onlyConnected} onChange={(event) => setOnlyConnected(event.target.checked)} /><span>仅显示已接入</span></label>
              <div className="model-provider-list" role="group" aria-label="模型服务商">
                {visible.map((provider) => {
                  const connection = connections.find((item) => item.providerCode === provider.providerCode);
                  const configured = connected(connection);
                  const ready = configured && connection?.enabled && connection.lastTestStatus === 'passed';
                  const status = ready ? 'ready' : connection?.enabled && configured ? 'testing' : configured ? 'saved' : 'unconfigured';
                  return <button key={provider.providerCode} type="button" className="model-provider-item" aria-pressed={provider.providerCode === selectedCode}
                    data-selected={provider.providerCode === selectedCode} onClick={() => chooseProvider(provider)}>
                    <strong>{provider.displayName}</strong><span data-status={status}>{ready ? '已就绪' : connection?.enabled && configured ? '待测试' : configured ? '已停用' : '未配置'}</span>
                  </button>;
                })}
                {!visible.length && <p role="status">没有匹配的供应商</p>}
              </div>
            </aside>
            {selected && draft && payload && <Card title={selected.displayName} className="model-provider-editor">
              <fieldset className="pi-auth-methods"><legend>连接方式</legend>
                {authMethods.map((method) => <label key={method}><input type="radio" name="pi-auth-method" value={method} checked={draft.authType === method}
                  onChange={() => updateDraft({ authType: method as Draft['authType'] })} />{method === 'oauth' ? '账号登录' : method === 'none' ? '本地 / 无密钥' : 'API Key'}</label>)}
              </fieldset>
              {draft.authType === 'oauth' ? <ProviderAccountLogin key={`login-${selectedCode}`} payload={payload} label={connected(saved) && saved?.authType === 'oauth' ? '重新登录账号' : selected.oauthLabel ?? '登录供应商账号'} onConnected={acceptConnection} />
                : <>
                  <label className="fqp-label" htmlFor="model-base-url">服务地址</label>
                  <input id="model-base-url" className="fqp-input" value={draft.baseUrl} maxLength={300} onChange={(event) => updateDraft({ baseUrl: event.target.value })} />
                  {draft.authType === 'api_key' && <>
                    <label className="fqp-label" htmlFor="model-api-key">API 密钥 {saved?.hasApiKey ? '（已保存；留空则保持不变）' : ''}</label>
                    <input id="model-api-key" className="fqp-input" type="password" autoComplete="off" maxLength={4096} value={draft.apiKey}
                      onFocus={() => { if (!draft.apiKeyChanged && saved?.hasApiKey) updateDraft({ apiKey: '' }); }}
                      onChange={(event) => updateDraft({ apiKey: event.target.value, apiKeyChanged: true })}
                      onBlur={() => { if (!draft.apiKeyChanged && saved?.apiKeyMask) updateDraft({ apiKey: saved.apiKeyMask }); }}
                      placeholder={saved?.hasApiKey ? '直接输入可替换密钥' : '仅在保存时上传到服务器'} />
                  </>}
                  <details className="pi-advanced"><summary>兼容接口与附加配置</summary>
                    <label className="fqp-label" htmlFor="pi-api">接口类型</label><select id="pi-api" className="fqp-input" value={draft.apiProtocol} onChange={(event) => updateDraft({ apiProtocol: event.target.value })}>
                      {Object.entries(apiLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                    </select>
                    {draft.authType === 'api_key' && <><label className="fqp-label" htmlFor="pi-env">供应商附加配置（JSON）</label>
                      <textarea id="pi-env" className="fqp-input" value={draft.providerEnv} onChange={(event) => updateDraft({ providerEnv: event.target.value })} placeholder={'例如 {"CLOUDFLARE_ACCOUNT_ID":"…"}；留空保留已保存配置'} maxLength={12000} />
                      <p className="model-provider-test-note">适用于云区域、项目或网关标识。与密钥一起加密保存；填入空对象可清除附加配置。</p></>}
                  </details>
                </>}
              <ProviderModelPicker key={`models-${selectedCode}`} providerCode={selectedCode} value={draft.defaultModel} onChange={(defaultModel) => updateDraft({ defaultModel })} allowCustom={draft.authType !== 'oauth'} />
              <label className="appearance-checkbox-row model-provider-enabled"><input type="checkbox" checked={draft.enabled} onChange={(event) => updateDraft({ enabled: event.target.checked })} /><span>启用此服务商，允许已通过测试的智能代理调用</span></label>
              <div className="model-provider-actions">
                {connected(saved) && <button type="button" className="fqp-btn" disabled={saving || testing} onClick={() => void disconnect()}>断开接入</button>}
                <button type="button" className="fqp-btn" disabled={saving || testing || draft.authType === 'oauth' && (!connected(saved) || saved?.authType !== 'oauth')} onClick={() => void save()}>{saving ? '保存中…' : '加密保存'}</button>
                <button type="button" className="fqp-btn fqp-btn-primary" disabled={saving || testing || dirty || !connected(saved)} onClick={() => void test()}>{testing ? '验证中…' : '验证模型'}</button>
              </div>
              <p className="model-provider-test-note">{dirty ? '配置已修改，请先保存再验证。' : '验证会发送一次简短模型请求，可能产生少量供应商费用。'}</p>
              {saved?.lastTestMessage && <p className="model-provider-test-message" data-status={saved.lastTestStatus ?? undefined}>{saved.lastTestMessage}</p>}
              <a className="model-provider-docs" href={selected.documentationUrl} target="_blank" rel="noreferrer">查看接入文档 ↗</a>
            </Card>}
          </div>
          <AgentModelBindings providers={connections} />
        </>}
  </section>;
}
