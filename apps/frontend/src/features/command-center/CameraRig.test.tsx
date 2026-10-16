import { Children, isValidElement, type ReactNode } from 'react';
import { render } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PerspectiveCamera } from 'three';
import { CameraRig, Pitch } from './PitchScene';

const state = vi.hoisted(() => ({ current: {} as Record<string, unknown> }));
vi.mock('@react-three/fiber', () => ({
  Canvas: () => null,
  useFrame: () => undefined,
  useThree: () => state.current,
}));

afterEach(() => vi.restoreAllMocks());

function rig(canvas: HTMLCanvasElement) {
  state.current = { camera: new PerspectiveCamera(), gl: { domElement: canvas }, invalidate: vi.fn() };
  return render(<CameraRig view="top" command={{ action: 'reset', sequence: 0 }} active onFailure={() => undefined} />);
}

function tracker(root: Document | ShadowRoot) {
  const add = vi.spyOn(root, 'addEventListener');
  const remove = vi.spyOn(root, 'removeEventListener');
  return () => {
    const keys = [...add.mock.calls.entries()].filter(([index, [type]]) => add.mock.contexts[index] === root && (type === 'keydown' || type === 'keyup'));
    expect(keys.length).toBeGreaterThan(0);
    for (const [addedIndex, [type, listener]] of keys) {
      expect(remove.mock.calls.some(([removedType, removedListener, options], index) =>
        remove.mock.contexts[index] === root && remove.mock.invocationCallOrder[index] > add.mock.invocationCallOrder[addedIndex] && removedType === type && removedListener === listener && typeof options === 'object' && options?.capture === true,
      )).toBe(true);
    }
  };
}

describe('CameraRig with real pinned OrbitControls', () => {
  it('uses diffuse materials without a renderer-retaining global PBR lookup texture', () => {
    const types: unknown[] = [];
    const visit = (node: ReactNode) => Children.forEach(node, child => {
      if (!isValidElement<{ children?: ReactNode }>(child)) return;
      types.push(child.type);
      visit(child.props.children);
    });
    visit(Pitch({ colors: { background: '#000000', pitch: '#112233', stripe: '#223344', line: '#ffffff', accent: '#ff0000', neutral: '#cccccc' } }));
    expect(types).not.toContain('meshStandardMaterial');
    expect(types.filter(type => type === 'meshLambertMaterial')).toHaveLength(3);
  });

  it('releases document key listeners after the canvas has been detached', () => {
    const canvas = document.createElement('canvas');
    document.body.append(canvas);
    const verify = tracker(document);
    const view = rig(canvas);
    canvas.remove();
    expect(canvas.getRootNode()).toBe(canvas);
    view.unmount();
    verify();
  });

  it('releases listeners from the original shadow root after detachment', () => {
    const host = document.createElement('div');
    document.body.append(host);
    const root = host.attachShadow({ mode: 'open' });
    const canvas = document.createElement('canvas');
    root.append(canvas);
    const verify = tracker(root);
    const view = rig(canvas);
    canvas.remove();
    expect(canvas.getRootNode()).toBe(canvas);
    view.unmount();
    verify();
    host.remove();
  });

  it('releases Control keyup and every old keydown listener over 20 detached unmounts', () => {
    const verify = tracker(document);
    for (let i = 0; i < 20; i++) {
      const canvas = document.createElement('canvas');
      document.body.append(canvas);
      const view = rig(canvas);
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Control', ctrlKey: true }));
      canvas.remove();
      view.unmount();
    }
    verify();
  });
});
