import { Component, useEffect, useRef, useState, type ReactNode } from 'react';
export function supportsWebGL2(): boolean {
  if (typeof WebGL2RenderingContext === 'undefined') return false;
  try {
    const canvas = document.createElement('canvas');
    const context = canvas.getContext('webgl2', { failIfMajorPerformanceCaveat: true });
    context?.getExtension('WEBGL_lose_context')?.loseContext();
    return !!context;
  } catch { return false; }
}
class SceneBoundary extends Component<{ children: ReactNode; fallback: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? this.props.fallback : this.props.children; }
}
function initialEnabled() { try { return localStorage.getItem('fqp.scene.enabled') !== 'false'; } catch { return true; } }
export default function SceneViewport({ children, fallback }: { children: (active: boolean, onFailure: () => void) => ReactNode; fallback: ReactNode }) {
  const host = useRef<HTMLDivElement>(null);
  const [enabled, setEnabled] = useState(initialEnabled);
  const [supported, setSupported] = useState<boolean | null>(null);
  const [visible, setVisible] = useState(false);
  const [pageVisible, setPageVisible] = useState(document.visibilityState !== 'hidden');
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!enabled) return;
    setSupported(supportsWebGL2());
  }, [enabled, attempt]);
  useEffect(() => {
    const onVisibility = () => setPageVisible(document.visibilityState !== 'hidden');
    document.addEventListener('visibilitychange', onVisibility);
    const observer = typeof IntersectionObserver !== 'undefined' ? new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting), { threshold: 0.05 }) : null;
    if (observer && host.current) observer.observe(host.current); else setVisible(true);
    return () => { observer?.disconnect(); document.removeEventListener('visibilitychange', onVisibility); };
  }, []);
  useEffect(() => { if (enabled && supported && visible && pageVisible) setLoaded(true); }, [enabled, supported, visible, pageVisible]);
  const toggle = () => {
    setEnabled(previous => { const next = !previous; try { localStorage.setItem('fqp.scene.enabled', String(next)); } catch { /* Storage is optional. */ } return next; });
  };
  const retry = () => { setFailed(false); setLoaded(false); setSupported(null); setAttempt(value => value + 1); };
  const fallbackContent = <div className="cc-scene-fallback">{fallback}<p role="status">{!enabled ? '已关闭 3D，二维赛事与证据可继续使用' : failed ? '3D 连接已中断，已切换二维视图' : supported === false ? '浏览器无法使用 WebGL 2，已切换二维视图' : '场景将在可见时加载'}</p><button type="button" onClick={retry}>重试 3D</button></div>;
  return <div ref={host} className="cc-scene-viewport">
    <div className="cc-scene-mode"><button type="button" aria-pressed={enabled} onClick={toggle}>{enabled ? '关闭 3D' : '开启 3D'}</button><span>二维列表始终可用</span></div>
    {enabled && supported && loaded && !failed ? <SceneBoundary key={attempt} fallback={<div className="cc-scene-fallback">{fallback}<p role="status">3D 加载失败，二维赛事与证据可继续使用</p><button type="button" onClick={retry}>重试 3D</button></div>}>{children(visible && pageVisible, () => setFailed(true))}</SceneBoundary> : fallbackContent}
  </div>;
}
