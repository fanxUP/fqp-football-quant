import { useEffect, useMemo, useState } from 'react';
import { Canvas } from '@react-three/fiber';
import { BoxGeometry, CylinderGeometry, MeshBasicMaterial, OctahedronGeometry, Quaternion, RingGeometry, SphereGeometry, Vector3 } from 'three';
import { CameraRig, RenderCounters, useSceneColors } from '../command-center/PitchScene';
import type { ResearchGraph, ResearchNode } from './research';

function Network({graph,selectedKey,onSelect}:{graph:ResearchGraph;selectedKey:string|null;onSelect:(key:string)=>void}) {
  const colors=useSceneColors();
  const geometry=useMemo(()=>({prediction:new CylinderGeometry(2.4,2.4,5,20),block:new BoxGeometry(4.4,2,4.4),llm:new SphereGeometry(3,20,14),agent:new OctahedronGeometry(3.5),edge:new CylinderGeometry(.13,.13,1,6),ring:new RingGeometry(3.5,4,28)}),[]);
  const material=useMemo(()=>({normal:new MeshBasicMaterial({color:colors.neutral}),selected:new MeshBasicMaterial({color:colors.accent}),edge:new MeshBasicMaterial({color:colors.line,transparent:true,opacity:.45}),config:new MeshBasicMaterial({color:colors.line,transparent:true,opacity:.55}),ring:new MeshBasicMaterial({color:colors.accent})}),[colors.neutral,colors.accent,colors.line]);
  useEffect(()=>()=>Object.values(geometry).forEach(value=>value.dispose()),[geometry]);
  useEffect(()=>()=>Object.values(material).forEach(value=>value.dispose()),[material]);
  const shape=(kind:ResearchNode['kind'])=>kind==='llm'?geometry.llm:kind==='agent'?geometry.agent:kind==='prediction'||kind==='version'?geometry.prediction:geometry.block;
  return <group dispose={null}>
    {graph.edges.flatMap(edge=>{
      const from=graph.nodes.find(row=>row.key===edge.source),to=graph.nodes.find(row=>row.key===edge.target);
      if(!from||!to)return [];
      const a=new Vector3(...from.position),b=new Vector3(...to.position),delta=b.clone().sub(a);
      const length=delta.length();
      const segments=edge.configured?8:1;
      return Array.from({length:segments},(_,i)=><mesh key={`${edge.source}:${edge.target}:${i}`} position={a.clone().addScaledVector(delta,(i+.5)/segments)} quaternion={new Quaternion().setFromUnitVectors(new Vector3(0,1,0),delta.clone().normalize())} scale={[1,length/segments*(edge.configured?.55:1),1]} geometry={geometry.edge} material={edge.configured?material.config:material.edge}/>);
    })}
    {graph.nodes.map(node=><group key={node.key} position={node.position} onClick={event=>{event.stopPropagation();onSelect(node.key);}}><mesh geometry={shape(node.kind)} material={node.key===selectedKey?material.selected:material.normal}/>{node.key===selectedKey&&<mesh position={[0,-3,0]} rotation={[-Math.PI/2,0,0]} geometry={geometry.ring} material={material.ring}/>}</group>)}
  </group>;
}
export default function ResearchScene({graph,selectedKey,onSelect,active,onFailure}:{graph:ResearchGraph;selectedKey:string|null;onSelect:(key:string)=>void;active:boolean;onFailure:()=>void}) {
  const colors=useSceneColors();
  const [view,setView]=useState<'top'|'angle'>('top');
  const [command,setCommand]=useState<{action:'reset'|'left'|'right'|'in'|'out'|'pan-up'|'pan-down';sequence:number}>({action:'reset',sequence:0});
  const [quality,setQuality]=useState(navigator.hardwareConcurrency<=4?1:1.5);
  const action=(value:typeof command.action)=>setCommand(previous=>({action:value,sequence:previous.sequence+1}));
  return <div><div className="mr-controls" aria-label="模型研究镜头控制">{([['top','俯视'],['angle','2.5D']] as const).map(([id,label])=><button type="button" key={id} aria-pressed={view===id} onClick={()=>{setView(id);action('reset');}}>{label}</button>)}<button type="button" onClick={()=>action('reset')}>重置</button><label>画质<select aria-label="模型研究画质" value={quality} onChange={event=>setQuality(Number(event.target.value))}><option value={1}>低</option><option value={1.5}>标准</option><option value={2}>高</option></select></label></div>
    <div className="mr-canvas" role="img" aria-label="模型版本与快照关系示意；使用下方二维节点完成键盘选择"><Canvas camera={{position:[0,130,.1],fov:48,near:.5,far:300}} dpr={quality} frameloop={active?'demand':'never'} gl={{antialias:true,powerPreference:'low-power'}}><color attach="background" args={[colors.background]}/><Network {...{graph,selectedKey,onSelect}}/><CameraRig {...{view,command,active,onFailure}}/><RenderCounters/></Canvas></div>
    <div className="mr-controls" aria-label="模型镜头键盘替代操作">{([['left','左旋'],['right','右旋'],['in','放大'],['out','缩小'],['pan-up','上移'],['pan-down','下移']] as const).map(([id,label])=><button type="button" key={id} onClick={()=>action(id)}>{label}</button>)}<span>按需渲染 · 无自动旋转</span></div>
  </div>;
}
