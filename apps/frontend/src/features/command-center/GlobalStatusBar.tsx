import { useEffect, useState } from 'react';
import { useLiveStatus } from './LiveStatus';
import { formatTime, freshness } from './presentation';
export default function GlobalStatusBar() {
  const { today, health, pipeline } = useLiveStatus();
  const [now, setNow] = useState(Date.now);
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now()), 30_000); return () => clearInterval(timer); }, []);
  const available = health.data?.status === 'ok' && !health.error && freshness(health.receivedAt, now) === '已获取';
  return <div className="cc-global-status" aria-label="全局系统状态">
    <span className={`cc-service ${available ? 'cc-service-ok' : ''}`}><i aria-hidden="true" />{available ? '服务可达' : health.loading ? '连接检测中' : '服务待确认'}</span>
    <span>业务日 <strong>{today.data?.businessDate || '—'}</strong></span>
    <span title={`来源：${today.data?.source ?? '未获取'}；响应生成：${formatTime(today.data?.responseTime)}。不是采集快照时间。`}>总览响应 {formatTime(today.data?.responseTime)} <small>{today.error ? today.data ? '刷新失败 · 保留旧值' : '总览未获取' : freshness(today.receivedAt, now)}</small></span>
    <a href="#/agents">报告运行 <strong>{pipeline.data?.running ?? '—'}</strong></a>
    <a href="#/data-health">告警 <strong>{pipeline.data?.alerts ?? '—'}</strong>{pipeline.error ? ' · 状态刷新失败' : freshness(pipeline.receivedAt, now) === '响应已过期' ? ' · 响应已过期' : ''}</a>
  </div>;
}
