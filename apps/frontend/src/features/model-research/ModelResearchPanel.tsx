import { lazy, Suspense, useEffect, useMemo, useState } from 'react';
import { api, type AgentModelBinding } from '../../core/apiClient';
import type { Prediction, PredictionModelOverview } from '../../core/types';
import SceneViewport from '../command-center/SceneViewport';
import useManualEvidence from '../../pages/useManualEvidence';
import { modelNameLabel, optionLabel, playTypeLabel } from '../../shared/constants';
import { bindingGraph, comparableRows, comparisonReason, evidenceReason, metric, predictionGraph } from './research';
import './ModelResearchPanel.css';
const ResearchScene = lazy(() => import('./ResearchScene'));

function checkedOverview(value: PredictionModelOverview) {
  if (!value || !Array.isArray(value.models) || value.models.length>200 || new Set(value.models.map(row=>row?.code)).size!==value.models.length || value.models.some(row=>!row||typeof row.code!=='string'||!row.code.trim())) throw new Error('模型目录身份或范围不正确');
  return value;
}
function checkedBindings(value: {bindings:AgentModelBinding[]}) {
  if (!value || !Array.isArray(value.bindings) || value.bindings.length>200 || new Set(value.bindings.map(row=>row?.agentCode)).size!==value.bindings.length || value.bindings.some(row=>!row||typeof row.agentCode!=='string'||!row.agentCode.trim()||typeof row.enabled!=='boolean'||typeof row.providerEnabled!=='boolean'||[row.providerCode,row.providerName,row.model,row.agentName].some(v=>v!=null&&typeof v!=='string'))) throw new Error('语言模型绑定身份或范围不正确');
  return value;
}
function ReadStatus({label,resource}:{label:string;resource:{loading:boolean;error:string|null;receivedAt:number|null;refresh:()=>unknown}}) {
  return <div className="mr-read-status"><span>{label} · {resource.loading?'读取中':resource.error?(resource.receivedAt?'读取失败，保留上次成功证据':'读取失败，尚无成功证据'):'已读取'}{resource.receivedAt?` · 本地接收 ${new Date(resource.receivedAt).toLocaleString('zh-CN',{hour12:false})}`:''}</span><button type="button" disabled={resource.loading} onClick={()=>void resource.refresh()}>刷新{label}</button>{resource.error&&<p role="alert">{label}读取失败：{resource.error}</p>}</div>;
}
export default function ModelResearchPanel({predictions,loading,error,receivedAt,total,onRefresh}:{predictions:Prediction[];loading:boolean;error:string|null;receivedAt:number|null;total:number|null;onRefresh:()=>void}) {
  const overview=useManualEvidence(async()=>checkedOverview(await api.modelOverview()));
  const bindings=useManualEvidence(async()=>checkedBindings(await api.modelProviders.bindings()));
  const [mode,setMode]=useState<'prediction'|'llm'>('prediction');
  const [predictionId,setPredictionId]=useState<number|null>(null);
  const [agentCode,setAgentCode]=useState<string|null>(null);
  const [nodeKey,setNodeKey]=useState<string|null>(null);
  const [page,setPage]=useState(0);
  const rows=predictions.slice(0,200);
  const selected=rows.find(row=>row.id===predictionId) ?? rows[0];
  const agent=bindings.data?.bindings.find(row=>row.agentCode===agentCode) ?? bindings.data?.bindings[0];
  const state=overview.data?.models.find(row=>row.code===selected?.model_name);
  const graph=useMemo(()=>mode==='prediction' ? selected ? predictionGraph(selected,state) : {nodes:[],edges:[]} : agent ? bindingGraph(agent) : {nodes:[],edges:[]},[mode,selected,state,agent]);
  const node=graph.nodes.find(row=>row.key===nodeKey) ?? graph.nodes.find(row=>row.kind==='output'||row.kind==='llm') ?? graph.nodes[0];
  const safePage=Math.min(page,Math.max(0,Math.ceil(rows.length/10)-1));
  useEffect(()=>{if (!rows.some(row=>row.id===predictionId)) {setPredictionId(null);setPage(0);}},[predictions,predictionId]);
  useEffect(()=>{if (!bindings.data?.bindings.some(row=>row.agentCode===agentCode)) setAgentCode(null);},[bindings.data,agentCode]);
  useEffect(()=>{setNodeKey(current=>graph.nodes.some(row=>row.key===current)?current:null);},[graph]);
  const comparable=selected ? comparableRows(selected,rows) : [];
  const reasons=selected ? [...new Set(rows.filter(row=>row.id!==selected.id).map(row=>comparisonReason(selected,row)).filter((reason):reason is string=>!!reason))] : [];
  const choosePrediction=(id:number)=>{setPredictionId(id);setNodeKey(null);};
  return <section className="mr-panel" aria-labelledby="model-research-title">
    <header><div><span className="appearance-eyebrow">模型研究</span><h2 id="model-research-title">模型关系与证据</h2></div><p>节点大小与位置仅用于导航；概率、命中率、Brier、LogLoss 与样本保留二维展示。ROI 与回撤使用独立回测口径；本场景不合成覆盖率或排名。</p></header>
    <div className="mr-modes" aria-label="模型研究数据类型"><button type="button" aria-pressed={mode==='prediction'} onClick={()=>{setMode('prediction');setNodeKey(null);}}>统计预测记录</button><button type="button" aria-pressed={mode==='llm'} onClick={()=>{setMode('llm');setNodeKey(null);}}>语言模型绑定</button></div>
    <p><a href="#/backtest">查看回测 ROI 与回撤</a> · <a href="#/analysis?section=models">打开单场解释与特征分析</a></p>
    <ReadStatus label="预测记录" resource={{loading,error,receivedAt,refresh:onRefresh}}/>
    <ReadStatus label="模型目录" resource={overview}/><ReadStatus label="语言模型绑定" resource={bindings}/>
    <p>已获取 {rows.length} 条预测 / 全部 {total??'—'} 条；最多展示最近 200 条，仅在这些记录内寻找可比证据。快照未记录时区时保持原始业务时刻。</p>
    <div className="mr-layout"><div>
      {mode==='prediction' ? <><h3>二维预测选择</h3><div className="mr-list" aria-label="研究预测记录">{rows.slice(safePage*10,safePage*10+10).map(row=><button type="button" key={row.id} aria-pressed={row.id===selected?.id} onClick={()=>choosePrediction(row.id)}><strong>{modelNameLabel(row.model_name)} · #{row.id}</strong><span>{row.home_team} — {row.away_team} · {playTypeLabel(row.play_type)} · {optionLabel(row.play_type,row.option_code)}</span><small>{row.predict_time}</small></button>)}</div>{rows.length===0&&<p>{loading?'正在读取预测记录':error?'预测证据未知，请重试':'暂无预测记录'}</p>}<nav className="mr-controls" aria-label="预测记录分页"><button type="button" disabled={safePage===0} onClick={()=>setPage(safePage-1)}>上一页</button><span>{safePage+1} / {Math.max(1,Math.ceil(rows.length/10))}</span><button type="button" disabled={(safePage+1)*10>=rows.length} onClick={()=>setPage(safePage+1)}>下一页</button></nav></> : <><h3>二维语言模型绑定</h3><label>Agent<select aria-label="研究Agent绑定" value={agent?.agentCode??''} onChange={event=>{setAgentCode(event.target.value);setNodeKey(null);}}>{bindings.data?.bindings.map(row=><option key={row.agentCode} value={row.agentCode}>{row.agentName||row.agentCode}</option>)}</select></label>{!agent&&<p>{bindings.error?'绑定证据未知':'暂无绑定配置'}</p>}<p>球形语言模型节点来自当前 Pi/Agent 绑定配置；启用与测试状态不代表实际模型调用或预测成功。</p></>}
    </div><div>
      <p className="mr-legend">方柱：预测模型/版本 · 扁块：快照、特征类别与输出 · 球形：语言模型 · 菱形：Agent · 虚线：当前配置说明 · 描边：已选择</p>
      {graph.nodes.length>0 ? <SceneViewport subject="模型研究" fallback={<p>使用二维节点和预测记录继续研究</p>}>{(active,onFailure)=><Suspense fallback={<p>正在加载模型关系场景，二维研究可继续使用</p>}><ResearchScene graph={graph} selectedKey={node?.key??null} onSelect={key=>{if(graph.nodes.some(row=>row.key===key))setNodeKey(key);}} active={active} onFailure={onFailure}/></Suspense>}</SceneViewport> : <p role="status">{mode==='prediction'&&selected?`场景未加载：${evidenceReason(selected)}`:'缺少完整关联证据，使用二维记录查看'}</p>}
      <div className="mr-nodes" aria-label="二维关系节点">{graph.nodes.map(row=><button type="button" key={row.key} aria-pressed={row.key===node?.key} onClick={()=>setNodeKey(row.key)}>{row.label}</button>)}</div>
      {node&&<div className="mr-selection" role="status"><strong>已选择：{node.label}</strong><p>{node.detail}</p></div>}
      {selected&&mode==='prediction'&&<><p>当前模型目录版本 {state?.version??'未读取'} 仅作配置参考；历史预测使用记录中的真实版本。实际推荐与彩票策略关联：证据未提供。</p><table aria-label="选中预测指标"><thead><tr><th>原始概率</th><th>最终概率</th><th>市场概率</th><th>EV</th><th>置信度</th></tr></thead><tbody><tr><td>{metric(selected.raw_model_probability,true)}</td><td>{metric(selected.model_probability,true)}</td><td>{metric(selected.market_probability,true)}</td><td>{metric(selected.ev)}</td><td>{metric(selected.confidence,true)}</td></tr></tbody></table></>}
    </div></div>
    {mode==='prediction'&&selected&&<section className="mr-comparison" aria-labelledby="mr-comparison-title"><h3 id="mr-comparison-title">同口径输出对照</h3><p>仅对照同赛事、玩法、原始选项、预测时刻、特征与赔率快照；保留返回顺序，不据此产生模型排名或投注建议。</p>{comparable.length>0?<div className="mr-table-scroll"><table aria-label="同口径模型概率"><thead><tr><th>模型</th><th>记录/版本</th><th>最终概率</th></tr></thead><tbody>{comparable.map(row=><tr key={row.id}><th>{modelNameLabel(row.model_name)}</th><td>#{row.id} / {row.research_evidence?.model_version}</td><td>{metric(row.model_probability,true)}</td></tr>)}</tbody></table></div>:<p role="status">不可比较：{evidenceReason(selected)||'缺少至少两个模型的唯一同口径输出，或存在重复模型记录'}。</p>}{reasons.length>0&&<p>其他已获取记录的不可比原因：{reasons.join('；')}。</p>}</section>}
  </section>;
}
