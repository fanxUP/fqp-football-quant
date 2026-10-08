import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import SceneViewport from './SceneViewport';
describe('3D capability and failure isolation', () => {
  beforeEach(() => { localStorage.clear(); });
  afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
  it('never loads the renderer without WebGL2', async () => {
    vi.stubGlobal('WebGL2RenderingContext', undefined); const child = vi.fn();
    render(<SceneViewport fallback={<div>二维球场</div>}>{child}</SceneViewport>);
    expect(await screen.findByText(/浏览器无法使用 WebGL 2/)).toBeInTheDocument(); expect(child).not.toHaveBeenCalled();
  });
  it('persists explicit 2D mode and avoids capability probing', () => {
    localStorage.setItem('fqp.scene.enabled', 'false'); const child = vi.fn(); const getContext = vi.spyOn(HTMLCanvasElement.prototype, 'getContext');
    render(<SceneViewport fallback={<div>二维球场</div>}>{child}</SceneViewport>);
    expect(screen.getByRole('button', { name: '开启 3D' })).toHaveAttribute('aria-pressed', 'false');
    expect(child).not.toHaveBeenCalled(); expect(getContext).not.toHaveBeenCalled();
  });
  it('recovers to 2D after renderer context loss', async () => {
    vi.stubGlobal('WebGL2RenderingContext', class {});
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ getExtension: () => null } as unknown as WebGL2RenderingContext);
    render(<SceneViewport fallback={<div>二维球场</div>}>{(_active, fail) => <button onClick={fail}>模拟实际 context lost</button>}</SceneViewport>);
    fireEvent.click(await screen.findByRole('button', { name: '模拟实际 context lost' }));
    expect(screen.getByText(/3D 连接已中断/)).toBeInTheDocument(); expect(screen.getByText('二维球场')).toBeInTheDocument();
  });
  it('delays loading until the scene enters the viewport', async () => {
    vi.stubGlobal('WebGL2RenderingContext', class {}); let observeCallback!: IntersectionObserverCallback;
    vi.stubGlobal('IntersectionObserver', class { constructor(callback: IntersectionObserverCallback) { observeCallback = callback; } observe() {} disconnect() {} });
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ getExtension: () => null } as unknown as WebGL2RenderingContext);
    const child = vi.fn(() => <div>场景已加载</div>);
    render(<SceneViewport fallback={<div />}>{child}</SceneViewport>);
    expect(child).not.toHaveBeenCalled();
    const { act } = await import('@testing-library/react');
    act(() => observeCallback([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver));
    await waitFor(() => expect(child).toHaveBeenCalled());
  });
});
