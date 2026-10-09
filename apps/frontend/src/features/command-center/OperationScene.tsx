import { useEffect, useMemo, useState } from 'react';
import { Canvas } from '@react-three/fiber';
import { CylinderGeometry, MeshBasicMaterial, Quaternion, SphereGeometry, Vector3 } from 'three';
import { CameraRig, RenderCounters, useSceneColors } from './PitchScene';
import { executionState, operationNodes, type ExecutionOverview } from './execution';
function Network({ overview, selectedId, fresh, now, onSelect, onAgentSelect, colors }: { overview: ExecutionOverview; selectedId: number | null; fresh: boolean; now: number; onSelect: (id: number) => void; onAgentSelect: (name: string) => void; colors: ReturnType<typeof useSceneColors> }) {
  const graph = useMemo(() => operationNodes(overview, selectedId), [overview, selectedId]);
  const resources = useMemo(() => ({ sphere: new SphereGeometry(2, 16, 12), job: new CylinderGeometry(1.8, 1.8, 3, 16), edge: new CylinderGeometry(.09, .09, 1, 6) }), []);
  const materials = useMemo(() => ({ accent: new MeshBasicMaterial({ color: colors.accent }), neutral: new MeshBasicMaterial({ color: colors.neutral }), muted: new MeshBasicMaterial({ color: colors.line }), edge: new MeshBasicMaterial({ color: colors.line, transparent: true, opacity: .3 }) }), [colors]);
  useEffect(() => () => Object.values(resources).forEach(resource => resource.dispose()), [resources]);
  useEffect(() => () => Object.values(materials).forEach(material => material.dispose()), [materials]);
  return <group dispose={null}>
    {graph.edges.map(edge => {
      const start = new Vector3(...graph.nodes.find(row => row.key === edge.source)!.position);
      const end = new Vector3(...graph.nodes.find(row => row.key === edge.target)!.position);
      const delta = end.clone().sub(start);
      return <mesh key={`${edge.source}-${edge.target}`} geometry={resources.edge} material={materials.edge} position={start.clone().add(end).multiplyScalar(.5)} quaternion={new Quaternion().setFromUnitVectors(new Vector3(0, 1, 0), delta.clone().normalize())} scale={[1, delta.length(), 1]} />;
    })}
    {graph.nodes.map(node => {
      const state = node.job ? executionState(node.job, fresh, overview.scheduler, now) : null;
      const material = node.job?.id === selectedId ? materials.accent : state?.tone === 'running' || node.kind === 'agent' ? materials.neutral : materials.muted;
      return <mesh key={node.key} position={node.position} geometry={node.kind === 'agent' ? resources.sphere : resources.job} material={material} onClick={event => { event.stopPropagation(); if (node.job) onSelect(node.job.id); else onAgentSelect(node.label); }} />;
    })}
  </group>;
}
export default function OperationScene({ overview, selectedId, fresh, now, onSelect, onAgentSelect, active, onFailure }: { overview: ExecutionOverview; selectedId: number | null; fresh: boolean; now: number; onSelect: (id: number) => void; onAgentSelect: (name: string) => void; active: boolean; onFailure: () => void }) {
  const colors = useSceneColors();
  const [view, setView] = useState<'angle' | 'top' | 'free'>('angle');
  const [command, setCommand] = useState<{ action: 'reset' | 'left' | 'right' | 'in' | 'out' | 'pan-up' | 'pan-down'; sequence: number }>({ action: 'reset', sequence: 0 });
  const action = (value: typeof command.action) => setCommand(previous => ({ action: value, sequence: previous.sequence + 1 }));
  return <div>
    <div className="cc-camera-toolbar" aria-label="Agent 视角控制">{(['angle', 'top', 'free'] as const).map((value, i) => <button key={value} type="button" aria-pressed={view === value} onClick={() => { setView(value); action('reset'); }}>{['2.5D', '俯视', '自由'][i]}</button>)}<button type="button" onClick={() => action('reset')}>重置</button></div>
    <div className="cc-canvas" role="img" aria-label="注册 Agent 与执行归属图；二维列表提供相同选择">
      <Canvas camera={{ position: [0, 85, 105], fov: 48, near: .5, far: 300 }} dpr={navigator.hardwareConcurrency <= 4 ? 1 : 1.5} frameloop={active ? 'demand' : 'never'} gl={{ antialias: true, powerPreference: 'low-power' }}>
        <color attach="background" args={[colors.background]} />
        <Network {...{ overview, selectedId, fresh, now, onSelect, onAgentSelect, colors }} />
        <CameraRig {...{ view, command, active, onFailure }} /><RenderCounters />
      </Canvas>
    </div>
    <div className="cc-camera-toolbar">{([['left', '左旋'], ['right', '右旋'], ['in', '放大'], ['out', '缩小'], ['pan-up', '上移'], ['pan-down', '下移']] as const).map(([id, label]) => <button key={id} type="button" onClick={() => action(id)}>{label}</button>)}</div>
  </div>;
}
