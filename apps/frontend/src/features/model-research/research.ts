import type { AgentModelBinding } from '../../core/apiClient';
import type { Prediction, PredictionModelRuntimeState } from '../../core/types';
import { modelNameLabel, optionLabel, playTypeLabel } from '../../shared/constants';

export const CATEGORY_LABELS: Record<string, string> = {strength:'球队实力',lineup:'阵容',absence:'伤停',rest:'赛程与休息',travel:'旅行与地理',weather:'天气',motivation:'战意',tournament:'赛制'};
const positive = (value: unknown): value is number => Number.isSafeInteger(value) && Number(value)>0;
const text = (value: unknown): value is string => typeof value==='string' && !!value.trim();
function clock(value: unknown) {
  if (typeof value!=='string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$/.test(value)) return null;
  const zoned = /(?:Z|[+-]\d{2}:\d{2})$/.test(value);
  const time = Date.parse(zoned ? value : `${value}Z`);
  return Number.isFinite(time) ? {time,zoned} : null;
}
function before(snapshot: unknown, prediction: unknown) {
  const a=clock(snapshot), b=clock(prediction);
  return !!a && !!b && a.zoned===b.zoned && a.time<=b.time;
}
export function evidenceReason(row: Prediction): string | null {
  const e=row.research_evidence;
  if (!positive(row.id) || !positive(row.match_id) || !text(row.model_name) || !text(row.play_type) || !text(row.option_code) || !clock(row.predict_time) || !e || !positive(e.model_version_id) || !text(e.model_version) || !text(e.model_type)) return '版本或预测身份的证据缺失';
  if (!positive(e.feature_snapshot_id) || !positive(e.odds_snapshot_id) || !text(e.feature_version) || !Array.isArray(e.feature_categories) || e.feature_categories.some(key=>!Object.prototype.hasOwnProperty.call(CATEGORY_LABELS,key))) return '特征或赔率快照证据缺失';
  if (!before(e.feature_snapshot_time,row.predict_time) || !before(e.odds_snapshot_time,row.predict_time)) return '快照时刻缺失、晚于预测或时区口径不同';
  return null;
}
export function comparisonReason(left: Prediction, right: Prediction): string | null {
  const missing=evidenceReason(left) || evidenceReason(right);
  if (missing) return missing;
  if (left.match_id!==right.match_id) return '赛事不同';
  if (left.play_type!==right.play_type) return '玩法不同';
  if (left.option_code!==right.option_code) return '原始选项不同';
  if (left.predict_time!==right.predict_time) return '预测时刻不同';
  const a=left.research_evidence!,b=right.research_evidence!;
  if (a.feature_snapshot_id!==b.feature_snapshot_id || a.feature_version!==b.feature_version || a.feature_snapshot_time!==b.feature_snapshot_time) return '特征快照不同';
  if (a.odds_snapshot_id!==b.odds_snapshot_id || a.odds_snapshot_time!==b.odds_snapshot_time) return '赔率快照不同';
  if ([left.model_probability,right.model_probability].some(p=>typeof p!=='number'||!Number.isFinite(p)||p<0||p>1)) return '概率缺失或非法';
  return null;
}
export function comparableRows(selected: Prediction, rows: Prediction[]): Prediction[] {
  const matches=rows.filter(row=>!comparisonReason(selected,row));
  const models=new Set(matches.map(row=>row.model_name));
  if (models.size<2 || models.size!==matches.length) return [];
  return matches;
}
export type ResearchNode = {key:string;kind:'prediction'|'version'|'feature'|'category'|'output'|'odds'|'policy'|'llm'|'agent';label:string;detail:string;position:[number,number,number]};
export type ResearchGraph = {nodes:ResearchNode[];edges:{source:string;target:string;configured?:boolean}[]};
export function predictionGraph(row: Prediction, state?: PredictionModelRuntimeState): ResearchGraph {
  const e=row.research_evidence;
  if (evidenceReason(row) || !e) return {nodes:[],edges:[]};
  const version=`version:${e.model_version_id}`, feature=`feature:${e.feature_snapshot_id}`, output=`output:${row.id}`;
  const nodes:ResearchNode[]=[
    {key:`model:${row.model_name}`,kind:'prediction',label:modelNameLabel(row.model_name),detail:`数据库模型类型：${e.model_type}；预测记录 #${row.id}`,position:[-22,0,-32]},
    {key:version,kind:'version',label:`版本 ${e.model_version}`,detail:`真实版本 #${e.model_version_id}；训练特征集版本 ${e.feature_set_version || '未记录'}；不使用当前版本覆盖历史`,position:[22,0,-32]},
    {key:feature,kind:'feature',label:`特征快照 #${e.feature_snapshot_id}`,detail:`${e.feature_version} · ${e.feature_snapshot_time}；仅证明快照关联，不能证明全部字段被模型使用`,position:[-22,0,-10]},
    {key:`odds:${e.odds_snapshot_id}`,kind:'odds',label:`赔率快照 #${e.odds_snapshot_id}`,detail:`${e.odds_snapshot_time}；同赛事、玩法、原始选项并且不晚于预测`,position:[22,0,-10]},
    {key:output,kind:'output',label:`${playTypeLabel(row.play_type)} · ${optionLabel(row.play_type,row.option_code)}`,detail:`赛事 #${row.match_id} · 预测 #${row.id} · ${row.predict_time}；概率与EV见二维表`,position:[0,0,30]},
  ];
  const edges:ResearchGraph['edges']=[{source:nodes[0].key,target:version},{source:version,target:output},{source:feature,target:output},{source:nodes[3].key,target:output}];
  const categories=Object.keys(CATEGORY_LABELS).filter(key=>e.feature_categories.includes(key));
  categories.forEach((key,i)=>{const id=`category:${e.feature_snapshot_id}:${key}`;nodes.push({key:id,kind:'category',label:CATEGORY_LABELS[key],detail:`快照 #${e.feature_snapshot_id} 的该类字段至少一个非空（包括0或false）；不是权重或重要性`,position:[(i-(categories.length-1)/2)*8,0,10]});edges.push({source:feature,target:id});});
  if (state?.code===row.model_name && text(state.metadata?.role?.['zh-CN'])) {
    nodes.push({key:`policy:${state.code}`,kind:'policy',label:'目录角色说明',detail:`当前目录配置：${state.metadata.role['zh-CN']}；未提供实际推荐/彩票策略关联，不能证明历史执行`,position:[28,0,30]});
    edges.push({source:nodes[0].key,target:nodes[nodes.length-1].key,configured:true});
  }
  return {nodes,edges};
}
export function bindingGraph(binding: AgentModelBinding): ResearchGraph {
  if (!text(binding.agentCode)||!text(binding.providerCode)||!text(binding.model)) return {nodes:[],edges:[]};
  const nodes:ResearchNode[]=[
    {key:`agent:${binding.agentCode}`,kind:'agent',label:binding.agentName || binding.agentCode,detail:`当前Agent绑定配置；${binding.enabled?'绑定启用':'绑定停用'}；不代表实际调用或执行成功`,position:[-18,0,0]},
    {key:`llm:${binding.providerCode}:${binding.model}`,kind:'llm',label:`${binding.providerName||binding.providerCode} · ${binding.model}`,detail:`语言模型配置；${binding.providerEnabled?'供应商启用':'供应商停用'}；测试状态 ${binding.providerTestStatus||'未知'}；不参与统计预测排名`,position:[18,0,0]},
  ];
  return {nodes,edges:[{source:nodes[0].key,target:nodes[1].key,configured:true}]};
}
export function metric(value: unknown, percent=false) { return typeof value==='number'&&Number.isFinite(value) && (!percent || (value>=0&&value<=1)) ? percent ? `${(value*100).toFixed(1)}%` : value.toFixed(4) : '—'; }
