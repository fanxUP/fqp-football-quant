import { useEffect, useRef, useState } from 'react';
import { api } from '../core/apiClient';
import { ApiError, type PoolAnalysis, type PoolIssue, type PoolParameters, type SavedPoolPlan } from '../core/types';
import Card from '../shared/components/Card';
import PageHeader from '../shared/components/PageHeader';
import PoolFixtureCatalog from '../features/pool/PoolFixtureCatalog';

const STATUS: Record<string, string> = {
  ready: '可生成', missing_predictions: '预测未齐', identity_pending: '比赛身份待核实',
  cutoff_pending: '停售时间待核实', issue_pending: '独立官方期次待采集', missing_issue: '官方期次待采集',
  suspended: '销售暂停', not_started: '尚未开售', conflict: '销售证据冲突',
};
const STRATEGY_LABEL: Record<string, string> = { conservative: '单选', balanced: '重点覆盖', aggressive: '扩大覆盖' };
const controlStyle = { minHeight: 44, maxWidth: '100%', marginTop: 6 };
const fieldStyle = { flex: '1 1 180px', maxWidth: 280 };
const stateLabel: Record<string, string> = { selling: '在售', closed: '已停售', unknown: '截止待核实', conflict: '销售证据冲突', suspended: '销售暂停', not_started: '未开售', missing_issue: '官方期次待采集' };
const probability = (p: number | null | undefined) => p == null ? '未知' : p === 0 ? '0%' : `${(p * 100).toPrecision(4)}%`;
const message = (e: unknown) => e instanceof ApiError || e instanceof Error ? e.message : '请求失败';
const controlsStyle = { display: 'flex', flexWrap: 'wrap' as const, gap: 16, alignItems: 'end' };

export default function PoolPage() {
  const [analysis, setAnalysis] = useState<PoolAnalysis | null>(null);
  const [issues, setIssues] = useState<PoolIssue[]>([]);
  const [plans, setPlans] = useState<SavedPoolPlan[]>([]);
  const [budget, setBudget] = useState(256);
  const [strategy, setStrategy] = useState('balanced');
  const [issueId, setIssueId] = useState('');
  const [pins, setPins] = useState<number[]>([]);
  const [excludes, setExcludes] = useState<number[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState('');
  const [tab, setTab] = useState<'sf14' | 'rx9'>('sf14');
  const [savedView, setSavedView] = useState<{ id: number; stale: boolean } | null>(null);
  const sequence = useRef(0);
  const parameters = (): PoolParameters => ({ budget, strategy, issue_id: issueId || undefined, pinned_orders: pins, excluded_orders: excludes });
  const params = analysis?.parameters;
  const dirty = !!analysis && !savedView && !!params && (params.budget !== budget || params.strategy !== strategy
    || (!!issueId && params.issue_id !== issueId) || JSON.stringify(params.pinned_orders ?? []) !== JSON.stringify(pins)
    || JSON.stringify(params.excluded_orders ?? []) !== JSON.stringify(excludes));
  const stale = dirty || !!savedView?.stale || !!error;

  async function load(p: PoolParameters) {
    const id = ++sequence.current;
    setLoading(true); setError(null); setNotice('');
    try {
      const result = await api.pool.analyze(p);
      if (id === sequence.current) { setAnalysis(result); setSavedView(null); }
    } catch (e) {
      if (id === sequence.current) setError(message(e));
    } finally { if (id === sequence.current) setLoading(false); }
  }
  useEffect(() => {
    void load({ budget: 256, strategy: 'balanced', pinned_orders: [], excluded_orders: [] });
    void api.pool.issues().then(r => setIssues(r.issues.filter(i => i.game_type === 't14c'))).catch(e => setNotice(`期次列表加载失败：${message(e)}`));
    void api.pool.plans().then(r => setPlans(r.plans)).catch(e => setNotice(`保存列表加载失败：${message(e)}`));
    return () => { sequence.current++; };
  }, []);

  async function save() {
    if (!analysis?.input_hash || !params?.issue_id) return;
    setBusy(true); setNotice('');
    try {
      const saved = await api.pool.save({ ...params, issue_id: params.issue_id, input_hash: analysis.input_hash });
      setNotice(`方案 #${saved.id} 已保存，仅作研究记录，未创建票据或扣款。`);
      const r = await api.pool.plans(); setPlans(r.plans);
    } catch (e) { setNotice(`保存失败：${message(e)}`); }
    finally { setBusy(false); }
  }
  async function openPlan(id: number) {
    const requestId = ++sequence.current;
    setBusy(true); setError(null); setLoading(false);
    try {
      const r = await api.pool.plan(id);
      if (requestId === sequence.current) { setAnalysis(r.snapshot); setSavedView({ id, stale: r.stale }); setNotice(''); }
    } catch (e) { if (requestId === sequence.current) setNotice(`读取失败：${message(e)}`); }
    finally { if (requestId === sequence.current) setBusy(false); }
  }
  function exportPlan() {
    if (!analysis) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify({ saved_plan: savedView, snapshot: analysis }, null, 2)], { type: 'application/json' }));
    const link = document.createElement('a'); link.href = url; link.download = `pool-${analysis.issue?.issue_no ?? 'unknown'}-${analysis.input_hash?.slice(0, 12) ?? 'research'}.json`;
    link.click(); URL.revokeObjectURL(url);
  }
  const portfolio = tab === 'sf14' ? analysis?.full_combinations : analysis?.rx9 && {
    count: analysis.rx9.combinations_count, total_cost: analysis.rx9.total_cost, combinations: analysis.rx9.combinations,
  };
  const shownMatches = tab === 'rx9' && analysis?.rx9?.selected_matches.length ? analysis.rx9.selected_matches : analysis?.matches ?? [];
  const status = tab === 'sf14' ? analysis?.sf14_status : analysis?.rx9_status;
  const hasPlan = !!analysis?.full_combinations?.count || !!analysis?.rx9?.combinations_count;

  return <div className="fqp-page" style={{ display: 'flex', flexDirection: 'column', gap: 16, minWidth: 0 }}>
    <PageHeader title="传统足彩彩池" subtitle="四玩法官方选场目录 · 14场与任九研究方案" />
    <PoolFixtureCatalog />
    <Card title="分析参数">
      <form onSubmit={e => { e.preventDefault(); if (!Number.isInteger(budget) || budget < 2 || budget > 10000 || budget % 2) { setError('预算须为2至10000元之间的偶数整数'); return; } void load(parameters()); }}>
        <div style={controlsStyle}>
          <label style={fieldStyle}>官方14场期次<br /><select className="fqp-select" style={controlStyle} aria-label="官方14场期次" value={issueId} onChange={e => setIssueId(e.target.value)} disabled={busy}>
            <option value="">当前／最近期次</option>{issues.map(i => <option key={i.id} value={String(i.id)}>{i.issue_no} · {stateLabel[i.state ?? ''] ?? i.state}</option>)}
          </select></label>
          <label style={fieldStyle}>每种玩法预算（元）<br /><input className="fqp-input" style={controlStyle} aria-label="每种玩法预算（元）" type="number" min={2} max={10000} step={2} value={budget} onChange={e => setBudget(Number(e.target.value))} disabled={busy} /></label>
          <label style={fieldStyle}>选项覆盖策略<br /><select className="fqp-select" style={controlStyle} aria-label="选项覆盖策略" value={strategy} onChange={e => setStrategy(e.target.value)} disabled={busy}>
            <option value="conservative">单选</option><option value="balanced">重点覆盖</option><option value="aggressive">扩大覆盖</option>
          </select></label>
          <button style={{ minHeight: 44 }} type="submit" className="fqp-btn fqp-btn-primary" disabled={loading || busy}>{loading ? '正在更新…' : '重新生成'}</button>
        </div>
      </form>
      <p style={{ color: 'var(--fqp-text-muted)' }}>任九支持复式，每场多选后展开为不同单注；两种玩法分别使用预算，并列展示不代表同时购买。</p>
    </Card>
    {error && <div role="alert" className="fqp-alert fqp-alert-warning">{error}{analysis && '。更新失败，下面保留的是上一份结果。'}</div>}
    {notice && <p role="status">{notice}</p>}
    {analysis && <>
      <Card title={savedView ? `已保存方案 #${savedView.id}` : analysis.analysis_mode === 'historical' ? '历史期次复盘' : analysis.analysis_mode === 'research' ? '研究参考' : '当前期次分析'}>
        <p>期号 {analysis.issue?.issue_no ?? '待采集'} · {stateLabel[analysis.issue_state] ?? analysis.issue_state}</p>
        {analysis.analysis_mode === 'historical' && <p>停售前证据的重建参考，不是当前投注推荐，也不冒充当时原始方案。</p>}
        <p>本结果预算 {params?.budget ?? '—'} 元／玩法 · 策略 {STRATEGY_LABEL[params?.strategy ?? ''] ?? '—'} · 数据时点 {analysis.data_as_of ?? '未知'}</p>
        <p>14场停售：{analysis.issue?.sale_stop ?? '未知'}；任九停售：{analysis.rx9?.issue?.sale_stop ?? '未知'}</p>
        {(stale || loading) && <p role="status" style={{ color: 'var(--fqp-warning)' }}>{loading ? '正在更新；当前仍为上一份结果。' : '此结果已过期或与当前参数不同，请重新生成。'}</p>}
        <p>14场：{STATUS[analysis.sf14_status] ?? analysis.sf14_status}；任九：{STATUS[analysis.rx9_status] ?? analysis.rx9_status}</p>
        <div style={controlsStyle}>
          <button style={{ minHeight: 44 }} className="fqp-btn" onClick={() => void save()} disabled={!hasPlan || stale || loading || busy || !!savedView}>保存完整方案</button>
          <button style={{ minHeight: 44 }} className="fqp-btn" onClick={exportPlan} disabled={!hasPlan || loading || busy}>导出完整 JSON</button>
        </div>
      </Card>
      <Card title="比赛与预测证据">
        <div role="group" aria-label="玩法" style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
          <button style={{ minHeight: 44 }} className="fqp-btn" aria-pressed={tab === 'sf14'} onClick={() => setTab('sf14')}>14场</button>
          <button style={{ minHeight: 44 }} className="fqp-btn" aria-pressed={tab === 'rx9'} onClick={() => setTab('rx9')}>任九</button>
        </div>
        <p>{STATUS[status ?? ''] ?? status}。{tab === 'rx9' && '自动建议按概率集中程度与熵排序，属于启发式选场。固定／排除修改后需重新生成。'}</p>
        <div style={{ overflowX: 'auto' }}>
          <table className="fqp-table" style={{ width: '100%' }}>
            <thead><tr><th>官方场序</th><th>对阵</th><th>胜／平／负</th><th>结果不确定性</th><th>证据</th><th>任九调整</th></tr></thead>
            <tbody>{(tab === 'rx9' ? analysis.rx9?.candidate_matches ?? analysis.matches : shownMatches).map(m => {
              const selected = analysis.rx9?.selected_matches.some(s => s.match_order === m.match_order);
              const source = m;
              return <tr key={m.match_order}>
                <td>{m.match_order}{tab === 'rx9' && selected ? ' · 已选' : ''}</td><td>{m.home_team} vs {m.away_team}<br /><small>{m.match_date || '开赛时间未知'}</small></td>
                <td>{probability(source.prob_home)}／{probability(source.prob_draw)}／{probability(source.prob_away)}</td>
                <td>{source.entropy == null ? '未知' : `${source.entropy.toFixed(3)} bit`}</td>
                <td>{source.evidence.model_count ?? 0} 个合格模型；{source.evidence.disagreement == null ? '无法比较模型间分歧' : `最大概率分歧 ${probability(source.evidence.disagreement)}`}<br />阵容／伤停证据：按模型留存记录核实</td>
                <td><select className="fqp-select" style={controlStyle} aria-label={`第${m.match_order}场任九调整`} value={pins.includes(m.match_order) ? 'pin' : excludes.includes(m.match_order) ? 'exclude' : 'auto'} disabled={loading || busy} onChange={e => {
                  setSavedView(null); setPins(p => [...p.filter(n => n !== m.match_order), ...(e.target.value === 'pin' ? [m.match_order] : [])].sort((a,b) => a-b));
                  setExcludes(p => [...p.filter(n => n !== m.match_order), ...(e.target.value === 'exclude' ? [m.match_order] : [])].sort((a,b) => a-b));
                }}><option value="auto">自动</option><option value="pin">固定选入</option><option value="exclude">排除</option></select></td>
              </tr>;
            })}</tbody>
          </table>
        </div>
        {(tab === 'rx9' ? analysis.rx9?.missing_inputs ?? analysis.missing_inputs : analysis.missing_inputs).map((m, i) => <p key={i}>缺口：{m.match_order ? `第${m.match_order}场 ` : ''}{m.reason}</p>)}
      </Card>
      <Card title={`${tab === 'sf14' ? '14场' : '任九'}组合`}>
        <p>完整方案 {portfolio?.count ?? 0} 注 · 实际成本 {portfolio?.total_cost ?? 0} 元</p>
        <p>至少一注全中理论概率：{probability(tab === 'sf14' ? analysis.probabilities?.hit14_prob : analysis.probabilities?.rx9_prob)}</p>
        {tab === 'sf14' && <p>至少一注命中13场及以上理论概率：{probability(analysis.probabilities?.hit13_or_more_prob)}</p>}
        <p>以下仅预览前10注；完整组合与输入证据通过 JSON 导出。</p>
        <div style={{ overflowX: 'auto' }}><table className="fqp-table" style={{ width: '100%' }}><thead><tr><th>注号</th><th>选项（按官方场序）</th><th>整注全中理论概率</th><th>期望命中场次</th></tr></thead>
          <tbody>{portfolio?.combinations.slice(0, 10).map((c, i) => <tr key={c.selections.join('')}><td>{i+1}</td><td>{c.selections.join(' · ')}</td><td>{probability(c.all_correct_prob)}</td><td>{c.expected_hits.toFixed(2)} 场</td></tr>)}</tbody>
        </table></div>
        {analysis.warnings.map((w, i) => <p key={i} style={{ color: 'var(--fqp-text-muted)' }}>{w}</p>)}
      </Card>
    </>}
    <Card title="已保存方案（最近50份）">
      {plans.length === 0 && <p>暂无保存记录。保存只保留研究快照，奖金未知，不记作零收益。</p>}
      {plans.map(p => <p key={p.id}><button style={{ minHeight: 44 }} className="fqp-btn" onClick={() => void openPlan(p.id)} disabled={busy || loading}>查看 #{p.id} · {p.issue.issue_no} · {p.parameters.budget} 元／玩法 · {p.created_at}</button></p>)}
    </Card>
  </div>;
}
