import { useEffect, useState } from 'react';
import { api, type ModelInvocationAudit as Invocation } from '../../core/apiClient';
import { toast } from '../../shared/components/Toast';
import { agentLabel } from '../../shared/constants';

function formatTime(value: string | null) {
  return value ? new Intl.DateTimeFormat('zh-CN', { dateStyle: 'short', timeStyle: 'medium' }).format(new Date(value)) : '—';
}

const errorLabels: Record<string, string> = {
  MODEL_TIMEOUT: '调用超时',
  MODEL_AUTH_FAILED: '鉴权失败',
  MODEL_NOT_FOUND: '模型不存在',
  MODEL_RATE_LIMITED: '额度或频率受限',
  MODEL_PROVIDER_UNAVAILABLE: '服务商不可用',
  MODEL_NETWORK_ERROR: '网络异常',
  MODEL_INVALID_RESPONSE: '返回格式异常',
  MODEL_EMPTY_RESPONSE: '返回内容为空',
  MODEL_REQUEST_REJECTED: '请求被拒绝',
  MODEL_CONFIG_ERROR: '配置异常',
  MODEL_CALL_FAILED: '模型调用失败',
};

export default function ModelInvocationAudit({ refreshToken }: { refreshToken: number }) {
  const [items, setItems] = useState<Invocation[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.modelProviders.invocations()
      .then((result) => { if (!cancelled) setItems(result.invocations); })
      .catch((error: Error) => toast.error(`模型调用审计加载失败：${error.message}`))
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [refreshToken]);

  return <section className="model-invocation-audit" aria-labelledby="model-invocation-audit-title">
    <div>
      <h4 id="model-invocation-audit-title">调用审计</h4>
      <p>仅保留调用元数据，不保存提示词、模型回复或密钥。</p>
    </div>
    {loading ? <p role="status">正在加载调用记录…</p> : items.length === 0 ? <p className="agent-model-trial-empty" role="status">暂时没有模型调用记录。</p> : <div className="model-invocation-list" role="list">
      {items.map((item, index) => <div className="model-invocation-item" role="listitem" key={`${item.createdAt}-${index}`}>
        <div><strong>{agentLabel(item.agentCode)}</strong><span>{item.providerCode ?? '未识别服务商'} · {item.model ?? '—'}</span></div>
        <div className="model-invocation-meta"><b data-status={item.status}>{item.status === 'succeeded' ? '成功' : errorLabels[item.errorCode ?? ''] ?? '失败'}</b><span>{item.durationMs} ms · {formatTime(item.createdAt)}</span></div>
      </div>)}
    </div>}
  </section>;
}
