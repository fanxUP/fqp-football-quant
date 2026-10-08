import { useEffect, useState } from 'react';
import { api, type ProviderModel } from '../../core/apiClient';

type Props = { providerCode: string; value: string; onChange: (value: string) => void; allowCustom: boolean };

export default function ProviderModelPicker({ providerCode, value, onChange, allowCustom }: Props) {
  const [query, setQuery] = useState('');
  const [offset, setOffset] = useState(0);
  const [models, setModels] = useState<ProviderModel[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let cancelled = false;
    const timer = window.setTimeout(() => {
      setLoading(true); setError('');
      api.modelProviders.models(providerCode, query, offset).then((result) => {
        if (cancelled) return;
        setModels(result.models); setTotal(result.total);
      }).catch((reason: Error) => { if (!cancelled) setError(reason.message); })
        .finally(() => { if (!cancelled) setLoading(false); });
    }, query ? 250 : 0);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [providerCode, query, offset, retry]);
  const selected = models.find((model) => model.id === value);
  return <section className="pi-model-picker" aria-label="Pi 模型目录">
    <label className="fqp-label" htmlFor="pi-model-search">搜索模型</label>
    <input id="pi-model-search" type="search" className="fqp-input" value={query} placeholder="按模型名称或 ID 搜索"
      onChange={(event) => { setQuery(event.target.value); setOffset(0); }} />
    {error ? <p role="alert">模型目录加载失败：{error} <button className="fqp-btn" onClick={() => setRetry((n) => n + 1)}>重试目录</button></p>
      : loading ? <p role="status">正在读取模型目录…</p> : <>
        <label className="fqp-label" htmlFor="pi-model-select">目录模型 · {total} 个</label>
        <select id="pi-model-select" className="fqp-input" value={selected ? value : ''} onChange={(event) => { if (event.target.value) onChange(event.target.value); }}>
          <option value="">{value ? `当前：${value}` : '请选择模型'}</option>
          {models.map((model) => <option key={model.id} value={model.id}>{model.name} · {model.id}</option>)}
        </select>
        {total > 100 && <div className="pi-catalog-pages">
          <button className="fqp-btn" disabled={offset === 0} onClick={() => setOffset((n) => Math.max(0, n - 100))}>上一页模型</button>
          <span>{offset + 1}–{Math.min(offset + 100, total)} / {total}</span>
          <button className="fqp-btn" disabled={offset + 100 >= total} onClick={() => setOffset((n) => n + 100)}>下一页模型</button>
        </div>}
        {!models.length && <p className="model-provider-state">没有匹配的模型{allowCustom ? '，可填写自定义模型 ID。' : '，请调整搜索词。'}</p>}
      </>}
    <label className="fqp-label" htmlFor="model-default">默认模型{allowCustom ? ' ID' : ''}</label>
    <input id="model-default" className="fqp-input" value={value} readOnly={!allowCustom} maxLength={160}
      onChange={(event) => onChange(event.target.value)} placeholder="选择目录模型或填写兼容服务的模型 ID" />
    {selected && <div className="pi-model-details">
      <span>{selected.reasoning ? '支持推理' : '文本生成'}</span>
      <span>{selected.input.includes('image') ? '文本与图像' : '文本输入'}</span>
      {selected.contextWindow && <span>上下文 {selected.contextWindow.toLocaleString()} tokens</span>}
      {selected.maxTokens && <span>最大输出 {selected.maxTokens.toLocaleString()} tokens</span>}
    </div>}
  </section>;
}
