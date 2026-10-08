import { useEffect, useRef, useState } from 'react';
import { api, type ModelProviderConnection, type ProviderConfigPayload, type ProviderLogin } from '../../core/apiClient';

type Props = { payload: ProviderConfigPayload; label: string; onConnected: (provider: ModelProviderConnection) => void };
const terminal = new Set(['connected', 'failed', 'cancelled', 'expired']);

export default function ProviderAccountLogin({ payload, label, onConnected }: Props) {
  const [login, setLogin] = useState<ProviderLogin | null>(null);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const id = useRef<string | null>(null);
  const mounted = useRef(true);
  const connected = useRef(onConnected);
  connected.current = onConnected;
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; if (id.current) void api.modelProviders.cancelLogin(id.current).catch(() => {}); };
  }, []);
  useEffect(() => {
    if (!login || terminal.has(login.status)) return;
    let cancelled = false;
    let timer: number;
    const poll = async () => {
      if (Date.now() / 1000 >= login.expiresAt) { id.current = null; setLogin({ ...login, status: 'expired', prompt: null }); return; }
      try {
        const next = await api.modelProviders.loginStatus(login.loginId);
        if (cancelled) return;
        setLogin(next);
        if (next.status === 'connected' && next.provider) { id.current = null; connected.current(next.provider); }
        else if (!terminal.has(next.status)) timer = window.setTimeout(() => void poll(), 1500);
      } catch (reason) {
        if (!cancelled) { setError(reason instanceof Error ? reason.message : '登录状态读取失败'); timer = window.setTimeout(() => void poll(), 3000); }
      }
    };
    timer = window.setTimeout(() => void poll(), 1000);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [login?.loginId, login?.status]);
  const start = async () => {
    setBusy(true); setError('');
    try {
      const result = await api.modelProviders.login(payload.providerCode, payload);
      if (!mounted.current) { void api.modelProviders.cancelLogin(result.loginId).catch(() => {}); return; }
      id.current = result.loginId; setLogin(result); setInput('');
    } catch (reason) { if (mounted.current) setError(reason instanceof Error ? reason.message : '登录启动失败'); }
    finally { if (mounted.current) setBusy(false); }
  };
  const submit = async () => {
    if (!login?.prompt) return;
    setBusy(true); setError('');
    try {
      const next = await api.modelProviders.loginInput(login.loginId, login.prompt.id, input);
      if (mounted.current) { setLogin(next); setInput(''); }
    } catch (reason) { if (mounted.current) setError(reason instanceof Error ? reason.message : '登录输入提交失败'); }
    finally { if (mounted.current) setBusy(false); }
  };
  const cancel = async () => {
    if (!login) return;
    setBusy(true);
    try { const result = await api.modelProviders.cancelLogin(login.loginId); if (mounted.current) { id.current = null; setLogin(result); setInput(''); } }
    catch (reason) { if (mounted.current) setError(reason instanceof Error ? reason.message : '取消失败'); }
    finally { if (mounted.current) setBusy(false); }
  };
  const active = login && !terminal.has(login.status);
  const authUrl = [...(login?.events ?? [])].reverse().find((event) => event.type === 'auth_url' && event.url);
  const device = [...(login?.events ?? [])].reverse().find((event) => event.type === 'device_code');
  return <div className="pi-account-login">
    <p>在供应商官网完成授权。服务器部署时，可将浏览器最后的回调地址复制到下方；无需在本系统填写账号密码。</p>
    {!active && <button type="button" className="fqp-btn fqp-btn-primary" disabled={busy || !payload.defaultModel} onClick={() => void start()}>{busy ? '启动登录…' : label}</button>}
    {active && <div aria-live="polite">
      <p>{login.status === 'waiting' ? '等待完成授权或输入' : '正在等待供应商授权…'} · 登录有效期 5 分钟</p>
      {authUrl?.url && <a href={authUrl.url} target="_blank" rel="noreferrer">打开供应商授权页面 ↗</a>}
      {device?.verificationUri && <p><a href={device.verificationUri} target="_blank" rel="noreferrer">打开设备授权页面 ↗</a> · 设备码 <strong>{device.userCode}</strong></p>}
      {authUrl?.instructions && <p>{authUrl.instructions}</p>}
      {login.prompt && <>
        <label htmlFor="pi-login-input" className="fqp-label">{login.prompt.message}</label>
        {login.prompt.type === 'select' ? <select id="pi-login-input" className="fqp-input" value={input} onChange={(event) => setInput(event.target.value)}>
          <option value="">请选择</option>{login.prompt.options.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
        </select> : <input id="pi-login-input" className="fqp-input" type={login.prompt.type === 'secret' ? 'password' : 'text'} autoComplete="off" value={input} maxLength={4096} onChange={(event) => setInput(event.target.value)} />}
        <button type="button" className="fqp-btn" disabled={busy || !input.trim()} onClick={() => void submit()}>提交授权信息</button>
      </>}
      <button type="button" className="fqp-btn" disabled={busy} onClick={() => void cancel()}>取消登录</button>
    </div>}
    {login?.status === 'connected' && <p role="status">账号已加密连接，请验证所选模型。</p>}
    {login?.status === 'failed' && <p role="alert">登录失败，原有凭据保留。请重新登录。</p>}
    {login?.status === 'expired' && <p role="alert">登录已过期，请重新开始。</p>}
    {error && <p role="alert">{error}</p>}
  </div>;
}
