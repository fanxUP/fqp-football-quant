import { lazy, Suspense, useEffect, useMemo, useState } from 'react';
import { api, type AgentModelBinding } from '../../core/apiClient';
import type { Prediction, PredictionGroupFeatureContext, PredictionModelOverview } from '../../core/types';
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
function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}
function hasExactKeys(value: Record<string, unknown>, keys: string[]) {
  const actual=Object.keys(value).sort();
  const expected=keys.slice().sort();
  return actual.length===expected.length && actual.every((key,index)=>key===expected[index]);
}
function checkedPredictionGroupContext(
  value: PredictionGroupFeatureContext,
  expected: {groupId:string;matchId:number;modelVersionId:number;playType:string;predictTime:string;featureSnapshotId:number|null},
): PredictionGroupFeatureContext {
  if (!isRecord(value)
    || !hasExactKeys(value,['group_id','run_id','match_id','model_version_id','play_type','predict_time','context_status','feature_context'])
    || value.group_id!==expected.groupId
    || typeof value.run_id!=='string'
    || value.match_id!==expected.matchId
    || value.model_version_id!==expected.modelVersionId
    || value.play_type!==expected.playType
    || value.predict_time!==expected.predictTime
    || !['recorded','not_recorded','invalid_integrity'].includes(String(value.context_status))) throw new Error('预测组上下文身份或范围不匹配');
  if (value.context_status!=='recorded') {
    if (value.feature_context!==null) throw new Error('未验证上下文不应返回特征元数据');
    return value as unknown as PredictionGroupFeatureContext;
  }
  const context=value.feature_context;
  if (!isRecord(context)
    || !hasExactKeys(context,['schema_version','match_id','model_version_id','predict_time','legacy_feature_snapshot_id','observation_batch','consumption'])
    || context.schema_version!=='prediction-feature-context/v1'
    || context.match_id!==expected.matchId
    || context.model_version_id!==expected.modelVersionId
    || context.predict_time!==expected.predictTime
    || context.legacy_feature_snapshot_id!==expected.featureSnapshotId
    || context.consumption!=='context_only_not_used_for_probability') throw new Error('预测组特征上下文未通过身份校验');
  const batch=context.observation_batch;
  if (!isRecord(batch)
    || !hasExactKeys(batch,['id','cutoff_id','cutoff_as_of','builder_version','feature_schema_version','status','content_hash','required_fields_count','feature_fields_count','value_fields_count','unknown_fields_count','newest_attempt_id','newest_attempt_status','selection_reason','metadata_integrity'])
    || !['complete','no_complete_batch','read_failed'].includes(String(batch.status))
    || [batch.required_fields_count,batch.feature_fields_count,batch.value_fields_count,batch.unknown_fields_count].some(n=>typeof n!=='number'||!Number.isSafeInteger(n)||n<0)
    || (batch.status==='complete'&&(typeof batch.id!=='number'||batch.id<=0||typeof batch.cutoff_as_of!=='string'||typeof batch.content_hash!=='string'||!/^[0-9a-f]{64}$/.test(batch.content_hash)))
    || (batch.status!=='complete'&&batch.id!==null)) throw new Error('预测组批次摘要格式无效');
  return value as PredictionGroupFeatureContext;
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
  const [groupContext,setGroupContext]=useState<{groupId:string|null;data:PredictionGroupFeatureContext|null;loading:boolean;error:string|null}>({groupId:null,data:null,loading:false,error:null});
  const rows=predictions.slice(0,200);
  const selected=rows.find(row=>row.id===predictionId) ?? rows[0];
  const selectedGroupId=selected?.research_evidence?.prediction_group_id ?? null;
  const agent=bindings.data?.bindings.find(row=>row.agentCode===agentCode) ?? bindings.data?.bindings[0];
  const state=overview.data?.models.find(row=>row.code===selected?.model_name);
  const graph=useMemo(()=>mode==='prediction' ? selected ? predictionGraph(selected,state) : {nodes:[],edges:[]} : agent ? bindingGraph(agent) : {nodes:[],edges:[]},[mode,selected,state,agent]);
  const node=graph.nodes.find(row=>row.key===nodeKey) ?? graph.nodes.find(row=>row.kind==='output'||row.kind==='llm') ?? graph.nodes[0];
  const safePage=Math.min(page,Math.max(0,Math.ceil(rows.length/10)-1));
  useEffect(()=>{if (!rows.some(row=>row.id===predictionId)) {setPredictionId(null);setPage(0);}},[predictions,predictionId]);
  useEffect(()=>{if (!bindings.data?.bindings.some(row=>row.agentCode===agentCode)) setAgentCode(null);},[bindings.data,agentCode]);
  useEffect(()=>{setNodeKey(current=>graph.nodes.some(row=>row.key===current)?current:null);},[graph]);
  useEffect(()=>{
    if(mode!=='prediction'||!selected||!selectedGroupId){setGroupContext({groupId:selectedGroupId,data:null,loading:false,error:null});return;}
    let current=true;
    setGroupContext({groupId:selectedGroupId,data:null,loading:true,error:null});
    const expected={groupId:selectedGroupId,matchId:selected.match_id,modelVersionId:selected.research_evidence?.model_version_id??0,playType:selected.play_type,predictTime:selected.predict_time,featureSnapshotId:selected.research_evidence?.feature_snapshot_id??null};
    api.predictionGroupFeatureContext(selectedGroupId)
      .then(value=>checkedPredictionGroupContext(value,expected))
      .then(data=>{if(current)setGroupContext({groupId:selectedGroupId,data,loading:false,error:null});})
      .catch(reason=>{if(current)setGroupContext({groupId:selectedGroupId,data:null,loading:false,error:reason instanceof Error?reason.message:'读取失败'});});
    return ()=>{current=false;};
  },[mode,selected?.id,selectedGroupId,selected?.match_id,selected?.play_type,selected?.predict_time,selected?.research_evidence?.model_version_id,selected?.research_evidence?.feature_snapshot_id]);
  const comparable=selected ? comparableRows(selected,rows) : [];
  const reasons=selected ? [...new Set(rows.filter(row=>row.id!==selected.id).map(row=>comparisonReason(selected,row)).filter((reason):reason is string=>!!reason))] : [];
  const choosePrediction=(id:number)=>{setPredictionId(id);setNodeKey(null);};
  const selectedContext=groupContext.groupId===selectedGroupId?groupContext:{groupId:selectedGroupId,data:null,loading:!!selectedGroupId,error:null};
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
    {mode==='prediction'&&selected&&<section className="mr-run-context" aria-labelledby="mr-run-context-title"><h3 id="mr-run-context-title">本条预测的 run 输入引用</h3>{!selectedGroupId?<p role="status">该条预测没有 run-aware 预测组 ID，无法追溯 run 级观测批次；不以当前最新批次代替。</p>:selectedContext.loading?<p role="status">正在读取该预测组保存的输入上下文…</p>:selectedContext.error?<p role="alert">预测组上下文读取失败：{selectedContext.error}</p>:selectedContext.data?.context_status==='invalid_integrity'?<p role="alert">预测组完整性校验失败，已拒绝展示其输入上下文。</p>:selectedContext.data?.context_status==='not_recorded'?<p role="status">该预测组未记录 P107 run 级上下文（旧版 manifest）；不能据此推断是否使用了 P104。</p>:selectedContext.data?.feature_context?<><p>预测组 {selectedContext.data.group_id} · run {selectedContext.data.run_id} · 模型版本 #{selectedContext.data.model_version_id} · cutoff {selectedContext.data.predict_time}</p><dl className="mr-context-grid"><div><dt>旧特征快照</dt><dd>{selectedContext.data.feature_context.legacy_feature_snapshot_id?`#${selectedContext.data.feature_context.legacy_feature_snapshot_id}`:'未记录'}</dd></div><div><dt>P104 批次</dt><dd>{selectedContext.data.feature_context.observation_batch.status==='complete'?`P104 批次 #${selectedContext.data.feature_context.observation_batch.id}`:selectedContext.data.feature_context.observation_batch.status==='read_failed'?'读取失败':'无完整批次'}</dd></div><div><dt>批次 cutoff</dt><dd>{selectedContext.data.feature_context.observation_batch.cutoff_as_of??'—'}</dd></div><div><dt>批次状态 / Schema</dt><dd>{selectedContext.data.feature_context.observation_batch.status} · {selectedContext.data.feature_context.observation_batch.feature_schema_version??'—'}</dd></div><div><dt>字段计数</dt><dd>{selectedContext.data.feature_context.observation_batch.value_fields_count} 有值 / {selectedContext.data.feature_context.observation_batch.feature_fields_count} 已记录 / {selectedContext.data.feature_context.observation_batch.required_fields_count} 必需</dd></div><div><dt>存储 hash</dt><dd>{selectedContext.data.feature_context.observation_batch.content_hash?`${selectedContext.data.feature_context.observation_batch.content_hash.slice(0,12)}…（未在此重算）`:'—'}</dd></div></dl><p className="mr-context-boundary">仅为输入上下文记录，未参与本次概率计算。</p></>:null}</section>}
    {mode==='prediction'&&selected&&<section className="mr-comparison" aria-labelledby="mr-comparison-title"><h3 id="mr-comparison-title">同口径输出对照</h3><p>仅对照同赛事、玩法、原始选项、预测时刻、特征与赔率快照；保留返回顺序，不据此产生模型排名或投注建议。</p>{comparable.length>0?<div className="mr-table-scroll"><table aria-label="同口径模型概率"><thead><tr><th>模型</th><th>记录/版本</th><th>最终概率</th></tr></thead><tbody>{comparable.map(row=><tr key={row.id}><th>{modelNameLabel(row.model_name)}</th><td>#{row.id} / {row.research_evidence?.model_version}</td><td>{metric(row.model_probability,true)}</td></tr>)}</tbody></table></div>:<p role="status">不可比较：{evidenceReason(selected)||'缺少至少两个模型的唯一同口径输出，或存在重复模型记录'}。</p>}{reasons.length>0&&<p>其他已获取记录的不可比原因：{reasons.join('；')}。</p>}</section>}
  </section>;
}
