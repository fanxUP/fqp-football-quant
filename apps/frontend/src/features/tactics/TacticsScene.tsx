import { useEffect, useMemo, useState } from 'react';
import { Canvas } from '@react-three/fiber';
import { CylinderGeometry, MeshBasicMaterial, MeshLambertMaterial, RingGeometry } from 'three';
import { CameraRig, Pitch, RenderCounters, useSceneColors } from '../command-center/PitchScene';
import type { SchematicNode } from './schematic';

type CameraAction = 'reset' | 'left' | 'right' | 'in' | 'out' | 'pan-up' | 'pan-down';
function Players({ nodes, selectedId, onSelect }: {nodes:SchematicNode[]; selectedId:number|null; onSelect:(id:number)=>void}) {
  const colors = useSceneColors();
  const geometries = useMemo(() => ({ token: new CylinderGeometry(2,2,2.6,20), ring: new RingGeometry(2.5,3.1,24) }), []);
  const materials = useMemo(() => ({ normal: new MeshLambertMaterial({color:colors.neutral}), selected: new MeshLambertMaterial({color:colors.accent}), ring: new MeshBasicMaterial({color:colors.accent}) }), [colors.neutral,colors.accent]);
  useEffect(() => () => Object.values(geometries).forEach(g => g.dispose()), [geometries]);
  useEffect(() => () => Object.values(materials).forEach(m => m.dispose()), [materials]);
  return <group dispose={null}>{nodes.map(node => <group key={node.player.player_id} position={node.position} onClick={event => {event.stopPropagation();onSelect(node.player.player_id);}}>
    <mesh geometry={geometries.token} material={node.player.player_id===selectedId?materials.selected:materials.normal}/>
    {node.player.player_id===selectedId && <mesh position={[0,-1.2,0]} rotation={[-Math.PI/2,0,0]} geometry={geometries.ring} material={materials.ring}/>}
  </group>)}</group>;
}
export default function TacticsScene({nodes,selectedId,onSelect,active,onFailure}:{nodes:SchematicNode[];selectedId:number|null;onSelect:(id:number)=>void;active:boolean;onFailure:()=>void}) {
  const colors = useSceneColors();
  const [view,setView] = useState<'top'|'angle'>('top');
  const [command,setCommand] = useState({action:'reset' as CameraAction,sequence:0});
  const [quality,setQuality] = useState(navigator.hardwareConcurrency <= 4 ? 1 : 1.5);
  const action=(value:CameraAction)=>setCommand(previous=>({action:value,sequence:previous.sequence+1}));
  return <div>
    <div className="te-scene-controls" aria-label="战术示意镜头控制">
      {([['top','俯视'],['angle','2.5D']] as const).map(([id,label])=><button type="button" key={id} aria-pressed={view===id} onClick={()=>{setView(id);action('reset');}}>{label}</button>)}
      <button type="button" onClick={()=>action('reset')}>重置</button>
      <label>画质<select aria-label="战术示意画质" value={quality} onChange={e=>setQuality(Number(e.target.value))}><option value={1}>低</option><option value={1.5}>标准</option><option value={2}>高</option></select></label>
    </div>
    <div className="te-canvas" role="img" aria-label="按位置类别分区的阵型示意；非真实坐标，使用下方二维名单完成键盘选择">
      <Canvas camera={{position:[0,130,0.1],fov:48,near:0.5,far:300}} dpr={quality} frameloop={active?'demand':'never'} gl={{antialias:true,powerPreference:'low-power'}}>
        <color attach="background" args={[colors.background]}/><ambientLight intensity={1.5}/><directionalLight position={[25,65,30]} intensity={2}/>
        <Pitch colors={colors}/><Players nodes={nodes} selectedId={selectedId} onSelect={onSelect}/>
        <CameraRig view={view} command={command} active={active} onFailure={onFailure}/><RenderCounters/>
      </Canvas>
    </div>
    <div className="te-scene-controls" aria-label="战术镜头键盘替代操作">{([['left','左旋'],['right','右旋'],['in','放大'],['out','缩小'],['pan-up','上移'],['pan-down','下移']] as const).map(([id,label])=><button type="button" key={id} onClick={()=>action(id)}>{label}</button>)}<span>按需渲染 · 无自动旋转</span></div>
  </div>;
}
