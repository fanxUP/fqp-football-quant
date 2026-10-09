import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { Color, CylinderGeometry, MeshBasicMaterial, MeshStandardMaterial, RingGeometry, Spherical, Vector3 } from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import type { TodayMatch } from '../../core/types';
import { useTheme } from '../../app/ThemeContext';
import { sceneNodes } from './presentation';

type View = 'angle' | 'top' | 'free';
type CameraAction = 'reset' | 'left' | 'right' | 'in' | 'out' | 'pan-up' | 'pan-down';
type Colors = { background: string; pitch: string; stripe: string; line: string; accent: string; neutral: string };
export function RenderCounters() {
  const { gl } = useThree();
  const frame = useRef(0);
  const rendered = useRef(0);
  useFrame(({ scene }) => {
    rendered.current += 1;
    cancelAnimationFrame(frame.current);
    frame.current = requestAnimationFrame(() => {
      gl.domElement.dataset.sceneFrames = String(rendered.current);
      gl.domElement.dataset.sceneCalls = String(gl.info.render.calls);
      gl.domElement.dataset.sceneGeometries = String(gl.info.memory.geometries);
      gl.domElement.dataset.sceneTextures = String(gl.info.memory.textures);
      if (scene.background instanceof Color) gl.domElement.dataset.sceneBackground = `#${scene.background.getHexString()}`;
    });
  });
  useEffect(() => () => cancelAnimationFrame(frame.current), []);
  return null;
}
export function useSceneColors(): Colors {
  const { appearance } = useTheme();
  const read = () => {
    const styles = getComputedStyle(document.documentElement);
    const token = (name: string, fallback: string) => styles.getPropertyValue(name).trim() || fallback;
    return { background: token('--fqp-bg', '#0B0F16'), pitch: token('--fqp-panel-2', '#202837'), stripe: token('--fqp-panel', '#171D27'), line: token('--fqp-text-muted', '#ABB7C9'), accent: token('--fqp-accent', '#F34F62'), neutral: token('--fqp-info', '#548DFC') };
  };
  const [colors, setColors] = useState(read);
  useLayoutEffect(() => { const frame = requestAnimationFrame(() => setColors(read())); return () => cancelAnimationFrame(frame); }, [appearance]);
  return colors;
}
export function CameraRig({ view, command, active, onFailure }: { view: View; command: { action: CameraAction; sequence: number }; active: boolean; onFailure: () => void }) {
  const { camera, gl, invalidate } = useThree();
  const controls = useRef<OrbitControls | null>(null);
  const failureRef = useRef(onFailure); failureRef.current = onFailure;
  useEffect(() => {
    const orbit = new OrbitControls(camera, gl.domElement);
    orbit.enableDamping = false; orbit.minDistance = 40; orbit.maxDistance = 150;
    orbit.minPolarAngle = 0.01; orbit.maxPolarAngle = Math.PI / 2.2;
    const changed = () => {
      const bounded = orbit.target.clone(); bounded.x = Math.max(-24, Math.min(24, bounded.x)); bounded.z = Math.max(-36, Math.min(36, bounded.z)); bounded.y = 0;
      camera.position.add(bounded.clone().sub(orbit.target)); orbit.target.copy(bounded); invalidate();
    };
    const lost = (event: Event) => { event.preventDefault(); failureRef.current(); };
    orbit.addEventListener('change', changed); gl.domElement.addEventListener('webglcontextlost', lost);
    controls.current = orbit;
    return () => { controls.current = null; orbit.removeEventListener('change', changed); orbit.dispose(); gl.domElement.removeEventListener('webglcontextlost', lost); };
  }, [camera, gl, invalidate]);
  useEffect(() => { if (controls.current) controls.current.enabled = active; }, [active]);
  useEffect(() => {
    const orbit = controls.current;
    if (!orbit) return;
    if (command.action === 'reset') {
      const position = view === 'top' ? [0, 130, 0.1] : view === 'free' ? [80, 77, 90] : [0, 85, 105];
      camera.position.set(...position as [number, number, number]); orbit.target.set(0, 0, 0);
    } else if (command.action === 'in' || command.action === 'out') {
      const offset = camera.position.clone().sub(orbit.target);
      offset.setLength(Math.max(40, Math.min(150, offset.length() * (command.action === 'in' ? 0.85 : 1.15))));
      camera.position.copy(orbit.target).add(offset);
    } else if (command.action.startsWith('pan')) {
      const nextZ = Math.max(-36, Math.min(36, orbit.target.z + (command.action === 'pan-up' ? -5 : 5)));
      camera.position.z += nextZ - orbit.target.z; orbit.target.z = nextZ;
    } else {
      const spherical = new Spherical().setFromVector3(camera.position.clone().sub(orbit.target));
      spherical.theta += command.action === 'left' ? -0.2 : 0.2;
      camera.position.copy(orbit.target).add(new Vector3().setFromSpherical(spherical));
    }
    orbit.update(); invalidate();
  }, [camera, command, invalidate, view]);
  return null;
}
function RectLine({ width, depth, x = 0, z = 0, color }: { width: number; depth: number; x?: number; z?: number; color: string }) {
  return <group position={[x, 0.03, z]}>
    {[-1, 1].map(side => <mesh key={`h-${side}`} position={[0, 0, side * depth / 2]} rotation={[-Math.PI / 2, 0, 0]}><planeGeometry args={[width, 0.2]} /><meshBasicMaterial color={color} /></mesh>)}
    {[-1, 1].map(side => <mesh key={`v-${side}`} position={[side * width / 2, 0, 0]} rotation={[-Math.PI / 2, 0, 0]}><planeGeometry args={[0.2, depth]} /><meshBasicMaterial color={color} /></mesh>)}
  </group>;
}
function Pitch({ colors }: { colors: Colors }) {
  return <group>
    <mesh position={[0, -0.6, 0]}><boxGeometry args={[76, 1.2, 113]} /><meshStandardMaterial color={colors.pitch} roughness={0.9} /></mesh>
    {Array.from({ length: 10 }, (_, i) => <mesh key={i} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.01, -47.25 + i * 10.5]}><planeGeometry args={[68, 10.5]} /><meshBasicMaterial color={i % 2 ? colors.pitch : colors.stripe} /></mesh>)}
    <RectLine width={68} depth={105} color={colors.line} />
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.04, 0]}><planeGeometry args={[68, 0.2]} /><meshBasicMaterial color={colors.line} /></mesh>
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.04, 0]}><ringGeometry args={[9, 9.2, 64]} /><meshBasicMaterial color={colors.line} /></mesh>
    {[-1, 1].map(side => <group key={side}><RectLine width={40.3} depth={16.5} z={side * 44.25} color={colors.line} /><RectLine width={18.3} depth={5.5} z={side * 49.75} color={colors.line} /><mesh position={[0, 1.25, side * 54]}><boxGeometry args={[7.32, 2.5, 1.6]} /><meshStandardMaterial color={colors.line} wireframe /></mesh></group>)}
  </group>;
}
function MatchNodes({ matches, selectedId, onSelect, colors }: { matches: TodayMatch[]; selectedId: number | null; onSelect: (id: number) => void; colors: Colors }) {
  const nodes = useMemo(() => sceneNodes(matches, selectedId), [matches, selectedId]);
  const geometries = useMemo(() => ({ pillar: new CylinderGeometry(1.7, 1.7, 2, 24), ring: new RingGeometry(2.15, 2.7, 32) }), []);
  const materials = useMemo(() => ({
    selected: new MeshStandardMaterial({ color: colors.accent, emissive: colors.accent, emissiveIntensity: 0.3 }),
    neutral: new MeshStandardMaterial({ color: colors.neutral, emissive: colors.neutral, emissiveIntensity: 0.04 }),
    ringSelected: new MeshBasicMaterial({ color: colors.accent }),
    ringNeutral: new MeshBasicMaterial({ color: colors.line }),
  }), [colors.accent, colors.neutral, colors.line]);
  // These shared resources have a single owner; descendants must not dispose them.
  useEffect(() => () => { geometries.pillar.dispose(); geometries.ring.dispose(); }, [geometries]);
  useEffect(() => () => Object.values(materials).forEach(material => material.dispose()), [materials]);
  return <group dispose={null}>{nodes.map(({ match, position }) => <group key={match.match_id} position={position} onClick={event => { event.stopPropagation(); onSelect(match.match_id); }}>
    <mesh geometry={geometries.pillar} material={match.match_id === selectedId ? materials.selected : materials.neutral} />
    <mesh position={[0, -0.8, 0]} rotation={[-Math.PI / 2, 0, 0]} geometry={geometries.ring} material={match.match_id === selectedId ? materials.ringSelected : materials.ringNeutral} scale={match.match_id === selectedId ? 1 : 0.9} />
  </group>)}</group>;
}
export default function PitchScene({ matches, selectedId, onSelect, active, onFailure }: { matches: TodayMatch[]; selectedId: number | null; onSelect: (id: number) => void; active: boolean; onFailure: () => void }) {
  const colors = useSceneColors();
  const [view, setView] = useState<View>('angle');
  const [command, setCommand] = useState({ action: 'reset' as CameraAction, sequence: 0 });
  const [quality, setQuality] = useState(navigator.hardwareConcurrency <= 4 ? 1 : 1.5);
  const action = (value: CameraAction) => setCommand(previous => ({ action: value, sequence: previous.sequence + 1 }));
  return <div className="cc-pitch-scene">
    <div className="cc-camera-toolbar" aria-label="球场视角控制">
      {([['angle', '2.5D'], ['top', '俯视'], ['free', '自由']] as const).map(([id, label]) => <button type="button" key={id} aria-pressed={view === id} onClick={() => { setView(id); action('reset'); }}>{label}</button>)}
      <button type="button" onClick={() => action('reset')}>重置</button>
      <label>画质<select aria-label="3D 画质" value={quality} onChange={event => setQuality(Number(event.target.value))}><option value={1}>低</option><option value={1.5}>标准</option><option value={2}>高</option></select></label>
    </div>
    <div className="cc-canvas" role="img" aria-label="真实赛事空间导航球场；使用赛事列表完成键盘选择">
      <Canvas camera={{ position: [0, 85, 105], fov: 48, near: 0.5, far: 300 }} dpr={quality} frameloop={active ? 'demand' : 'never'} gl={{ antialias: true, powerPreference: 'low-power' }} onCreated={({ gl }) => { gl.setClearColor(new Color(colors.background)); }}>
        <color attach="background" args={[colors.background]} />
        <ambientLight intensity={1.5} /><directionalLight position={[25, 65, 30]} intensity={2} />
        <Pitch colors={colors} />
        <MatchNodes matches={matches} selectedId={selectedId} onSelect={onSelect} colors={colors} />
        <CameraRig view={view} command={command} active={active} onFailure={onFailure} />
        <RenderCounters />
      </Canvas>
    </div>
    <div className="cc-camera-toolbar cc-camera-secondary" aria-label="键盘替代镜头操作">
      {([['left', '左旋'], ['right', '右旋'], ['in', '放大'], ['out', '缩小'], ['pan-up', '上移'], ['pan-down', '下移']] as const).map(([id, label]) => <button type="button" key={id} onClick={() => action(id)}>{label}</button>)}
      <span>按需渲染 · 无自动旋转</span>
    </div>
  </div>;
}
