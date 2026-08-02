import { useEffect, useState } from 'react';
import { api, type AgentModelBinding, type ModelProviderConnection } from '../../core/apiClient';
import { toast } from '../../shared/components/Toast';
import AgentModelTrial from './AgentModelTrial';
import ModelInvocationAudit from './ModelInvocationAudit';

export default function AgentModelBindings({ providers }: { providers: ModelProviderConnection[] }) {
  const [bindings, setBindings] = useState<AgentModelBinding[]>([]);
  const [saving, setSaving] = useState<string | null>(null);
  const [auditVersion, setAuditVersion] = useState(0);
  const [providerChoices, setProviderChoices] = useState<Record<string, string>>({});
  const readyProviders = providers.filter((provider) => provider.enabled && provider.hasApiKey && provider.lastTestStatus === 'passed');

  useEffect(() => {
    api.modelProviders.bindings()
      .then((result) => {
        setBindings(result.bindings);
        setProviderChoices(Object.fromEntries(result.bindings
          .filter((binding) => binding.providerCode)
          .map((binding) => [binding.agentCode, binding.providerCode as string])));
      })
      .catch((error: Error) => toast.error(`代理模型配置加载失败：${error.message}`));
  }, []);

  const save = async (binding: AgentModelBinding, enabled: boolean, action: 'binding' | 'toggle') => {
    const provider = providerChoices[binding.agentCode] ?? binding.providerCode ?? readyProviders[0]?.providerCode;
    if (!provider) {
      toast.error('请先保存、启用并测试一个模型服务商');
      return;
    }
    setSaving(binding.agentCode);
    try {
      const result = await api.modelProviders.saveBinding(binding.agentCode, { providerCode: provider, enabled });
      setBindings((current) => current.map((item) => item.agentCode === binding.agentCode ? result.binding : item));
      setProviderChoices((current) => ({ ...current, [binding.agentCode]: provider }));
      toast.success(action === 'binding' ? `${binding.agentName} 的服务商已保存` : enabled ? `${binding.agentName} 已启用模型调用` : `${binding.agentName} 已关闭模型调用`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '保存失败');
    } finally {
      setSaving(null);
    }
  };

  return <section className="agent-model-bindings" aria-labelledby="agent-model-bindings-title">
    <div>
      <h3 id="agent-model-bindings-title">智能代理模型开关</h3>
      <p>仅允许任务编排、复盘与文档智能代理手动调用模型；每日推荐、风控和彩票结算不会使用外部模型。</p>
    </div>
    <div className="agent-model-binding-list">
      {bindings.map((binding) => <div className="agent-model-binding" key={binding.agentCode}>
        <div className="agent-model-binding-info"><strong>{binding.agentName}</strong><span>{binding.providerName ? `${binding.providerName} · ${binding.model}` : '尚未绑定服务商'}</span></div>
        <label className="agent-model-provider-select"><span>服务商</span><select className="fqp-input" aria-label={`${binding.agentName} 服务商`}
          value={providerChoices[binding.agentCode] ?? binding.providerCode ?? ''}
          disabled={saving === binding.agentCode || readyProviders.length === 0}
          onChange={(event) => setProviderChoices((current) => ({ ...current, [binding.agentCode]: event.target.value }))}>
          {!binding.providerCode && <option value="">请选择已测试服务商</option>}
          {binding.providerCode && !readyProviders.some((provider) => provider.providerCode === binding.providerCode) &&
            <option value={binding.providerCode}>当前服务商不可启用，请重新选择</option>}
          {readyProviders.map((provider) => <option key={provider.providerCode} value={provider.providerCode}>{provider.displayName} · {provider.defaultModel}</option>)}
        </select></label>
        <div className="agent-model-binding-actions">
          <button type="button" className="fqp-btn" disabled={saving === binding.agentCode || readyProviders.length === 0}
            onClick={() => void save(binding, binding.enabled, 'binding')}>保存服务商</button>
          <button type="button" className="fqp-btn" disabled={saving === binding.agentCode}
            onClick={() => void save(binding, !binding.enabled, 'toggle')}>
            {saving === binding.agentCode ? '保存中…' : binding.enabled ? '关闭调用' : '启用调用'}
          </button>
        </div>
      </div>)}
    </div>
    <AgentModelTrial
      bindings={bindings.filter((binding) => binding.enabled && readyProviders.some(
        (provider) => provider.providerCode === binding.providerCode,
      ))}
      onCompleted={() => setAuditVersion((version) => version + 1)}
    />
    <ModelInvocationAudit refreshToken={auditVersion} />
  </section>;
}
