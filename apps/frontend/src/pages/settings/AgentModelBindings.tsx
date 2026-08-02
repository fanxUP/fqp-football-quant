import { useEffect, useState } from 'react';
import { api, type AgentModelBinding, type ModelProviderConnection } from '../../core/apiClient';
import { toast } from '../../shared/components/Toast';

export default function AgentModelBindings({ providers }: { providers: ModelProviderConnection[] }) {
  const [bindings, setBindings] = useState<AgentModelBinding[]>([]);
  const [saving, setSaving] = useState<string | null>(null);

  useEffect(() => {
    api.modelProviders.bindings()
      .then((result) => setBindings(result.bindings))
      .catch((error: Error) => toast.error(`代理模型配置加载失败：${error.message}`));
  }, []);

  const save = async (binding: AgentModelBinding, enabled: boolean) => {
    const provider = binding.providerCode ?? providers.find((item) => item.enabled)?.providerCode;
    if (!provider) {
      toast.error('请先保存、启用并测试一个模型服务商');
      return;
    }
    setSaving(binding.agentCode);
    try {
      const result = await api.modelProviders.saveBinding(binding.agentCode, { providerCode: provider, enabled });
      setBindings((current) => current.map((item) => item.agentCode === binding.agentCode ? result.binding : item));
      toast.success(enabled ? `${binding.agentName} 已启用模型调用` : `${binding.agentName} 已关闭模型调用`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '保存失败');
    } finally {
      setSaving(null);
    }
  };

  return <section className="agent-model-bindings" aria-labelledby="agent-model-bindings-title">
    <div>
      <h3 id="agent-model-bindings-title">智能代理模型开关</h3>
      <p>仅允许任务编排、复盘与文档 Agent 手动调用模型；每日推荐、风控和彩票结算不会使用外部模型。</p>
    </div>
    <div className="agent-model-binding-list">
      {bindings.map((binding) => <div className="agent-model-binding" key={binding.agentCode}>
        <div><strong>{binding.agentName}</strong><span>{binding.providerName ? `${binding.providerName} · ${binding.model}` : '尚未绑定服务商'}</span></div>
        <button type="button" className="fqp-btn" disabled={saving === binding.agentCode}
          onClick={() => void save(binding, !binding.enabled)}>
          {saving === binding.agentCode ? '保存中…' : binding.enabled ? '关闭调用' : '启用调用'}
        </button>
      </div>)}
    </div>
  </section>;
}
